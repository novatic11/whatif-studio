"""Episode renderer: plan.json -> narration -> timeline -> frames -> mixed,
loudness-normalised 1080p MP4 + SRT captions."""
import copy
import json
import math
import multiprocessing as mp
import os
import re
import subprocess
import sys
import time

import cairo
import numpy as np

from . import audio, brand, scenes, tts
from .ease import smooth, window

TRANSITION = 0.5  # seconds


# ------------------------------------------------------------ anchors
def _resolve(obj, words):
    """Replace "@word", "@word#2", "@word+0.4" strings with scene-relative seconds."""
    if isinstance(obj, str) and obj.startswith("@"):
        m = re.match(r"@([^#+\-]+)(?:#(\d+))?([+\-][\d.]+)?$", obj)
        if not m:
            raise ValueError(f"bad anchor {obj}")
        target, nth, off = m.group(1).lower(), int(m.group(2) or 1), float(m.group(3) or 0)
        hits = [w for w in words if re.sub(r"\W", "", w[0].lower()) == re.sub(r"\W", "", target)]
        if len(hits) < nth:
            raise ValueError(f"anchor {obj} not found in narration")
        return round(hits[nth - 1][1] + off, 3)
    if isinstance(obj, list):
        return [_resolve(x, words) for x in obj]
    if isinstance(obj, dict):
        return {k: _resolve(v, words) for k, v in obj.items()}
    return obj


# ------------------------------------------------------------ build timeline
def build(plan, work):
    os.makedirs(work, exist_ok=True)
    voice = plan.get("voice", brand.VOICE)
    speed = plan.get("speed", brand.VOICE_SPEED)
    timeline, voice_parts, cursor, all_words = [], [], 0.0, []
    for i, sc in enumerate(plan["scenes"]):
        lead = sc.get("lead", 0.35 if i else 0.8)
        narr = sc.get("narration", "").strip()
        if narr:
            a, words = tts.synthesize(narr, voice, speed)
        else:
            a, words = np.zeros(0, np.float32), []
        words = [(w, s + lead, e + lead) for w, s, e in words]
        dur = max(sc.get("min_dur", 0), lead + len(a) / tts.SR + sc.get("tail", 0.45))
        entry = copy.deepcopy(sc)
        entry["params"] = _resolve(sc.get("params", {}), words)
        entry["overlays"] = _resolve(sc.get("overlays", []), words)
        entry["sfx"] = _resolve(sc.get("sfx", []), words)
        entry.update(start=cursor, dur=dur, words=words)
        timeline.append(entry)
        voice_parts.append((cursor + lead, a))
        all_words += [(w, s + cursor, e + cursor) for w, s, e in words]
        cursor += dur
    total = cursor
    vtrack = np.zeros(int(math.ceil(total * tts.SR)) + tts.SR, np.float32)
    for st, a in voice_parts:
        k = int(st * tts.SR)
        vtrack[k:k + len(a)] += a
    return timeline, total, vtrack, all_words


# ------------------------------------------------------------ frames
_G = {}


def _render_scene(ctx, entry, t):
    fn = scenes.SCENES[entry["type"]]
    lt = t - entry["start"]
    fn(ctx, lt, entry["dur"], entry["params"], _G["env"])
    scenes.overlay(ctx, lt, entry.get("overlays", []), _G["env"])


def render_frame(fi):
    tl = _G["timeline"]
    t = fi / brand.FPS
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, brand.W, brand.H)
    ctx = cairo.Context(surf)
    idx = max(i for i, e in enumerate(tl) if e["start"] <= t + 1e-9) if t >= tl[0]["start"] else 0
    cur = tl[idx]
    nxt = tl[idx + 1] if idx + 1 < len(tl) else None
    prv = tl[idx - 1] if idx > 0 else None
    # transition window straddles boundaries
    if prv is not None and t - cur["start"] < TRANSITION / 2 and cur.get("transition", "crossfade") != "cut":
        a, b, u = prv, cur, 0.5 + (t - cur["start"]) / TRANSITION
    elif nxt is not None and cur["start"] + cur["dur"] - t < TRANSITION / 2 and nxt.get("transition", "crossfade") != "cut":
        a, b, u = cur, nxt, 0.5 - (cur["start"] + cur["dur"] - t) / TRANSITION
    else:
        a, b, u = cur, None, 0
    _render_scene(ctx, a, t)
    if b is not None:
        kind = b.get("transition", "crossfade")
        layer = cairo.ImageSurface(cairo.FORMAT_ARGB32, brand.W, brand.H)
        lctx = cairo.Context(layer)
        _render_scene(lctx, b, t)
        if kind == "dip":
            if u >= 0.5:
                ctx.set_source_surface(layer)
                ctx.paint()
            ctx.set_source_rgba(0, 0, 0, 1 - abs(u - 0.5) * 2)
            ctx.paint()
        elif kind == "flash":
            if u >= 0.5:
                ctx.set_source_surface(layer)
                ctx.paint()
            ctx.set_source_rgba(1, 0.97, 0.9, max(0.0, 1 - abs(u - 0.5) * 3) * 0.9)
            ctx.paint()
        else:
            ctx.set_source_surface(layer)
            ctx.paint_with_alpha(smooth(u))
    # global fade in/out
    total = _G["total"]
    f = min(window(t, 0, 0.6), 1 - window(t, total - 0.8, 0.8))
    if f < 1:
        ctx.set_source_rgba(0, 0, 0, 1 - f)
        ctx.paint()
    return bytes(surf.get_data())


def _encode_chunk(args):
    lo, hi, path = args
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
           "-s", f"{brand.W}x{brand.H}", "-r", str(brand.FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-g", str(brand.FPS * 2), path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for fi in range(lo, hi):
        p.stdin.write(render_frame(fi))
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for chunk {path}")
    return path


def render_video(timeline, total, work, workers=None, seed=1, palette="deep_space", frames=None):
    from . import bodies
    _G.update(timeline=timeline, total=total, env=scenes.Env(palette, seed))
    # warm texture caches before forking so workers share them
    for k, s in (("earth", 3), ("star", 5)):
        bodies.planet_texture(k, s)
    n = frames or int(round(total * brand.FPS))
    workers = workers or os.cpu_count() or 2
    nchunks = max(workers * 3, 1)
    step = math.ceil(n / nchunks)
    jobs = [(i, min(n, i + step), os.path.join(work, f"chunk_{k:04d}.mp4")) for k, i in enumerate(range(0, n, step))]
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        done = pool.map(_encode_chunk, jobs, chunksize=1)
    lst = os.path.join(work, "chunks.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in done)
    out = os.path.join(work, "video_noaudio.mp4")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", out], check=True)
    for p in done:
        os.remove(p)
    return out


# ------------------------------------------------------------ audio
def build_audio(plan, timeline, total, vtrack, work):
    seed = plan.get("seed", 1)
    inten = [(e["start"], e.get("music_intensity", 0.5)) for e in timeline]

    def intensity(t):
        v = inten[0][1]
        for s, x in inten:
            if t >= s:
                v = x
        return v

    mus = audio.music(total, plan.get("music_mood", "awe"), seed=seed, intensity=intensity)
    fx = np.zeros((2, int(total * audio.SR) + audio.SR), np.float32)
    for i, e in enumerate(timeline):
        events = list(e.get("sfx", []))
        if i and e.get("transition", "crossfade") != "cut" and e.get("whoosh", True):
            events.append({"at": -0.3, "name": "whoosh", "gain": -12})
        for ev in events:
            clip = audio.sfx(ev["name"], seed=i)
            g = 10 ** (ev.get("gain", -6) / 20)
            k = int((e["start"] + ev["at"]) * audio.SR)
            if k < 0:
                continue
            m = min(len(clip), fx.shape[1] - k)
            fx[:, k:k + m] += clip[:m] * g
    vw, mw, fw = (os.path.join(work, x) for x in ("voice.wav", "music.wav", "sfx.wav"))
    audio.write_wav(vw, vtrack, tts.SR)
    audio.write_wav(mw, mus, audio.SR)
    audio.write_wav(fw, fx, audio.SR)
    out = os.path.join(work, "mix.wav")
    stats = audio.master(vw, mw, fw, out)
    return out, stats


# ------------------------------------------------------------ captions
def srt(words, path, max_chars=42, max_dur=3.0):
    def ts(x):
        h, r = divmod(x, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}".replace(",1000", ",999")
    cues, cur = [], []
    for w in words:
        line = " ".join(x[0] for x in cur + [w])
        if cur and (len(line) > max_chars or w[2] - cur[0][1] > max_dur or w[1] - cur[-1][2] > 0.6):
            cues.append(cur)
            cur = []
        cur.append(w)
    if cur:
        cues.append(cur)
    with open(path, "w") as f:
        for i, c in enumerate(cues, 1):
            text = " ".join(x[0] for x in c)
            text = re.sub(r"\s+([,.;:!?])", r"\1", text)
            f.write(f"{i}\n{ts(c[0][1])} --> {ts(c[-1][2] + 0.15)}\n{text}\n\n")


# ------------------------------------------------------------ main
def render_episode(plan_path, out_dir, workers=None):
    t0 = time.time()
    plan = json.load(open(plan_path))
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)
    timeline, total, vtrack, words = build(plan, work)
    print(f"[timeline] {len(timeline)} scenes, {total:.1f}s ({time.time() - t0:.0f}s)", flush=True)
    json.dump([{k: v for k, v in e.items() if k != "words"} for e in timeline], open(os.path.join(out_dir, "timeline.json"), "w"), indent=1)
    mix, stats = build_audio(plan, timeline, total, vtrack, work)
    print(f"[audio] mixed ({time.time() - t0:.0f}s)", flush=True)
    video = render_video(timeline, total, work, workers, plan.get("seed", 1), plan.get("palette", "deep_space"))
    print(f"[video] rendered ({time.time() - t0:.0f}s)", flush=True)
    final = os.path.join(out_dir, "final.mp4")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-i", mix, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", final], check=True)
    srt(words, os.path.join(out_dir, "captions.srt"))
    json.dump({"duration": total, "loudness_in": stats, "render_seconds": time.time() - t0},
              open(os.path.join(out_dir, "render_report.json"), "w"), indent=1)
    print(f"[done] {final} ({time.time() - t0:.0f}s)", flush=True)
    return final


if __name__ == "__main__":
    render_episode(sys.argv[1], sys.argv[2])
