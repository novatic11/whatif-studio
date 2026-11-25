"""Writer's self-check for an episode package (run before marking it ready):
  python tools/validate.py episodes/0002-some-topic
- plan QC (structure, length, variety, sources)
- narration synthesis: resolves every "@word" anchor and measures real durations
- duration rules: long-form >= 8:00, Shorts 60-75 s
- preview stills (one per scene) -> out/preview/<slug>/sheet.jpg to LOOK at
Exit code 0 = ready."""
import glob
import json
import os
import sys

import cairo
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from studio import brand, qc, render, scenes  # noqa: E402


def preview(plan, timeline, out):
    os.makedirs(out, exist_ok=True)
    env = scenes.Env(plan.get("palette", "deep_space"), plan.get("seed", 1))
    tiles = []
    for e in timeline:
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, brand.W, brand.H)
        c = cairo.Context(s)
        t = e["dur"] * 0.6
        scenes.SCENES[e["type"]](c, t, e["dur"], e["params"], env)
        scenes.overlay(c, t, e.get("overlays", []), env)
        p = os.path.join(out, f"{e['id']}.png")
        s.write_to_png(p)
        tiles.append(Image.open(p).convert("RGB").resize((brand.W // 4, brand.H // 4)))
    cols = 5 if brand.W > brand.H else 6
    rows = (len(tiles) + cols - 1) // cols
    tw, th = tiles[0].size
    sheet = Image.new("RGB", (tw * cols, th * rows))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    sheet.save(os.path.join(out, "sheet.jpg"), quality=85)
    return os.path.join(out, "sheet.jpg")


def check(path, stills=True):
    plan = json.load(open(path))
    fmt = plan.get("format", "landscape")
    brand.set_format(fmt)
    issues = qc.check_plan(plan, fmt)
    slug = plan.get("slug", os.path.basename(path))
    work = os.path.join(ROOT, "out", "validate", slug)
    try:
        timeline, total, _, words = render.build(plan, work)
    except Exception as e:  # unresolved anchor, bad params
        return {"file": path, "ok": False, "issues": issues + [f"build failed: {e}"]}
    if fmt == "landscape" and total < qc.LONG_MIN_S:
        issues.append(f"duration {total:.0f}s < 480s: add ~{(qc.LONG_MIN_S - total) * 2.6 + 40:.0f} words")
    if fmt == "vertical" and not (qc.SHORT_MIN_S <= total <= qc.SHORT_MAX_S):
        issues.append(f"Short duration {total:.1f}s outside 60-75s")
    long_scenes = [f"{e['id']} ({e['dur']:.0f}s)" for e in timeline if e["dur"] > (45 if fmt == "landscape" else 12)]
    if long_scenes:
        issues.append(f"scenes too long on one visual: {long_scenes}")
    sheet = preview(plan, timeline, os.path.join(ROOT, "out", "preview", slug)) if stills else None
    return {"file": os.path.relpath(path, ROOT), "ok": not issues, "duration_s": round(total, 1),
            "scenes": len(timeline), "issues": issues, "preview_sheet": sheet}


if __name__ == "__main__":
    ep = sys.argv[1]
    files = [f for f in [os.path.join(ep, "plan.json")] if os.path.exists(f)] + sorted(glob.glob(os.path.join(ep, "shorts", "*.json")))
    results = [check(f, stills="--no-stills" not in sys.argv) for f in files]
    print(json.dumps(results, indent=1))
    sys.exit(0 if all(r["ok"] for r in results) else 1)
