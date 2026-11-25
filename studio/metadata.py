"""Builds YouTube title/description/tags from a plan: chapters from scene
'chapter' markers, numbered sources, and the channel's standing disclosures."""
from . import brand

DISCLOSURE = (
    "About this video: an animated thought experiment. The script was researched and written with AI "
    "assistance and checked against the sources above; scenarios beyond established science are "
    "framed as speculation. Narration uses a synthetic voice (Kokoro TTS). All animation, music "
    "and sound effects are original and computer-generated; nothing depicts real footage."
)


def _ts(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def chapters(timeline):
    ch = [(e["start"], e["chapter"]) for e in timeline if e.get("chapter")]
    if not ch:
        return []
    if ch[0][0] > 0.5:
        ch.insert(0, (0.0, "Intro"))
    else:
        ch[0] = (0.0, ch[0][1])
    # YouTube needs >= 3 chapters, each >= 10 s
    clean = [ch[0]]
    for t, name in ch[1:]:
        if t - clean[-1][0] >= 10:
            clean.append((t, name))
    return clean if len(clean) >= 3 else []


def build(plan, timeline, kind="long", long_video_id=None):
    m = plan.get("meta", {})
    title = m.get("title") or plan.get("title")
    parts = [m.get("summary", "").strip()]
    if kind == "short":
        if long_video_id:
            parts.append(f"Full story: https://www.youtube.com/watch?v={long_video_id}")
        parts.append("#Shorts #WhatIf #Science")
    else:
        ch = chapters(timeline)
        if ch:
            parts.append("Chapters\n" + "\n".join(f"{_ts(t)} {n}" for t, n in ch))
    src = plan.get("sources", [])
    if src:
        lines = []
        for i, s in enumerate(src, 1):
            lines.append(f"[{i}] {s['title']}: {s['url']}" if isinstance(s, dict) else f"[{i}] {s}")
        parts.append("Sources\n" + "\n".join(lines))
    parts.append(DISCLOSURE)
    if kind == "long":
        parts.append(f"New thought experiments every week. Subscribe: https://www.youtube.com/{brand.CHANNEL_HANDLE}\n#WhatIf #Science #Hypothetical")
    desc = "\n\n".join(p for p in parts if p).replace("<", "‹").replace(">", "›")
    tags = list(dict.fromkeys(m.get("tags", []) + ["what if", "hypothetical", "science", "Hypothetica"]))
    while sum(len(t) + 2 for t in tags) > 480:
        tags.pop()
    return {"title": title[:100], "description": desc[:4900], "tags": tags, "playlist": m.get("playlist")}
