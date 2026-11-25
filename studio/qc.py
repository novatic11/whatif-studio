"""Measurable pre-upload quality control. Every check returns pass/fail with
numbers, so failures are explainable and repairable. Nothing here relies on an
AI 'quality score'."""
import glob
import json
import math
import os
import re
import subprocess
from collections import Counter

from . import scenes

LONG_MIN_S = 8 * 60
SHORT_MIN_S, SHORT_MAX_S = 60.0, 75.0
CLICKBAIT = re.compile(r"\b(you won'?t believe|shocking|gone wrong|100% real|not clickbait|must watch|insane)\b", re.I)


def _ff(args):
    return subprocess.run(["ffmpeg", "-hide_banner", "-nostats"] + args, capture_output=True, text=True).stderr


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
                         capture_output=True, text=True).stdout
    return json.loads(out)


# ------------------------------------------------------------ plan checks (before rendering)
def check_plan(plan, fmt):
    issues = []
    sc = plan.get("scenes", [])
    if not sc:
        issues.append("plan has no scenes")
    for s in sc:
        if s.get("type") not in scenes.SCENES:
            issues.append(f"scene {s.get('id')}: unknown type {s.get('type')}")
    narr = " ".join(s.get("narration", "") for s in sc)
    words = len(narr.split())
    if fmt == "landscape" and words < 1150:
        issues.append(f"script too short for 8+ min ({words} words; need ~1150+)")
    if fmt == "vertical" and not (130 <= words <= 230):
        issues.append(f"Short script length {words} words is outside 130-230")
    if not plan.get("sources") and fmt == "landscape":
        issues.append("no sources listed")
    # repeated sentences / filler
    sents = [x.strip().lower() for x in re.split(r"[.!?]", narr) if len(x.split()) > 4]
    dup = [k for k, v in Counter(sents).items() if v > 1]
    if dup:
        issues.append(f"repeated sentences: {dup[:2]}")
    # visual variety: no scene type should dominate a long video completely
    if fmt == "landscape" and len(sc) >= 10:
        types = Counter(s["type"] for s in sc)
        if len(types) < 3:
            issues.append(f"low visual variety: only {dict(types)}")
        longest = max((len(s.get("narration", "").split()) for s in sc), default=0)
        if longest > 120:
            issues.append(f"a scene has {longest} words of narration (>~45s on one visual)")
    return issues


# ------------------------------------------------------------ media checks (after rendering)
def check_media(video, fmt, srt=None):
    res = {}
    info = probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    dur = float(info["format"]["duration"])
    w, h = int(v["width"]), int(v["height"])
    want = (1920, 1080) if fmt == "landscape" else (1080, 1920)
    res["resolution"] = {"ok": (w, h) == want, "value": f"{w}x{h}"}
    res["has_audio"] = {"ok": a is not None}
    if fmt == "landscape":
        res["duration"] = {"ok": dur >= LONG_MIN_S, "value": round(dur, 1), "rule": ">= 480s"}
    else:
        res["duration"] = {"ok": SHORT_MIN_S <= dur <= SHORT_MAX_S, "value": round(dur, 1), "rule": "60-75s"}
    # black frames (ignore the intentional fade in/out and 'dip' transitions under 0.6s)
    log = _ff(["-i", video, "-vf", "blackdetect=d=0.6:pix_th=0.06", "-an", "-f", "null", "-"])
    blacks = [(float(m.group(1)), float(m.group(2))) for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    blacks = [b for b in blacks if b[0] > 1.0 and b[1] < dur - 1.5]
    res["black_frames"] = {"ok": not blacks, "value": blacks[:5]}
    # frozen video (no motion for >4s means a broken animation)
    log = _ff(["-i", video, "-vf", "freezedetect=n=0.0008:d=4", "-an", "-f", "null", "-"])
    freezes = re.findall(r"freeze_start: ([\d.]+)", log)
    res["frozen_video"] = {"ok": not freezes, "value": freezes[:5]}
    # loudness and true peak
    log = _ff(["-i", video, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
    m_i = re.findall(r"I:\s+(-?[\d.]+) LUFS", log)
    m_p = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)
    lufs = float(m_i[-1]) if m_i else None
    peak = float(m_p[-1]) if m_p else None
    res["loudness"] = {"ok": lufs is not None and -16.0 <= lufs <= -12.5, "value": lufs, "rule": "-14 LUFS +/-1.5"}
    res["clipping"] = {"ok": peak is not None and peak <= -0.5, "value": peak, "rule": "true peak <= -0.5 dBFS"}
    # long silences (narration dropouts)
    log = _ff(["-i", video, "-vn", "-af", "silencedetect=n=-45dB:d=2.5", "-f", "null", "-"])
    sil = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    sil = [s for s in sil if 1.0 < s < dur - 6]
    res["silence_gaps"] = {"ok": not sil, "value": sil[:5]}
    if srt and os.path.exists(srt):
        cues = re.findall(r"(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})", open(srt).read())
        t = lambda g: int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3]) / 1000
        bad = [i for i, c in enumerate(cues) if t(c[4:]) <= t(c[:4]) or t(c[4:]) > dur + 0.5]
        overl = [i for i in range(1, len(cues)) if t(cues[i][:4]) < t(cues[i - 1][4:]) - 0.01]
        res["captions"] = {"ok": bool(cues) and not bad and not overl, "value": {"cues": len(cues), "bad": bad[:5], "overlaps": overl[:5]}}
    return res


# ------------------------------------------------------------ metadata checks
def check_metadata(meta, fmt):
    issues = []
    t = meta.get("title", "")
    if not (10 <= len(t) <= 100):
        issues.append(f"title length {len(t)} (10-100)")
    if CLICKBAIT.search(t) or CLICKBAIT.search(meta.get("description", "")):
        issues.append("clickbait phrasing in title/description")
    if sum(1 for c in t if c.isupper()) > 0.6 * max(1, sum(1 for c in t if c.isalpha())):
        issues.append("title is mostly capitals")
    d = meta.get("description", "")
    if len(d) > 4900:
        issues.append(f"description too long ({len(d)})")
    if "<" in d or ">" in d:
        issues.append("description contains < or > (rejected by YouTube)")
    tags = meta.get("tags", [])
    if sum(len(x) + 2 for x in tags) > 480:
        issues.append("tags exceed 500 chars")
    if fmt == "landscape" and "Sources" not in d:
        issues.append("description has no Sources section")
    return issues


# ------------------------------------------------------------ similarity to past videos
def _tokens(text):
    stop = set("the a an of to and in is it that this would be for on with as at by from or if what was are were its".split())
    return [w for w in re.findall(r"[a-z']+", text.lower()) if w not in stop and len(w) > 2]


def _cos(a, b):
    ca, cb = Counter(a), Counter(b)
    dot = sum(ca[k] * cb[k] for k in ca)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    return dot / (na * nb) if na and nb else 0.0


def similarity(plan_path, root="episodes"):
    me = json.load(open(plan_path))
    mine = _tokens(" ".join(s.get("narration", "") for s in me["scenes"]))
    best = (0.0, None)
    for p in glob.glob(os.path.join(root, "*", "plan.json")):
        if os.path.abspath(p) == os.path.abspath(plan_path):
            continue
        other = json.load(open(p))
        if other.get("status") == "sample":
            continue
        c = _cos(mine, _tokens(" ".join(s.get("narration", "") for s in other["scenes"])))
        if c > best[0]:
            best = (c, other.get("slug"))
    return {"ok": best[0] < 0.55, "value": round(best[0], 3), "closest": best[1], "rule": "cosine < 0.55"}


def summarize(results):
    fails = [k for k, v in results.items() if isinstance(v, dict) and not v.get("ok", True)]
    return {"passed": not fails, "failed": fails, "checks": results}
