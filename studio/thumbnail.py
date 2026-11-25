"""Thumbnail generator: renders several concepts (hero visual x text x layout
x accent) and picks the best by measurable criteria: text contrast against
its local background, text size, legibility at phone size, colourfulness,
brightness, and subject contrast."""
import itertools
import json
import os

import cairo
import numpy as np
from PIL import Image

from . import brand, draw, scenes

TW, TH = 1280, 720


def _render_concept(hero, text_lines, layout, accent, env):
    brand.set_format("landscape")
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, brand.W, brand.H)
    c = cairo.Context(s)
    shift = {"text_left": 330, "text_right": -330, "text_bottom": 0}[layout]
    c.save()
    c.translate(shift, -120 if layout == "text_bottom" else 0)
    scenes.SCENES[hero["type"]](c, hero.get("t", 3.0), 10.0, hero.get("params", {}), env)
    c.restore()
    # contrast panel behind text: soft gradient, not a box
    if layout == "text_left":
        g = cairo.LinearGradient(0, 0, brand.W * 0.6, 0)
        g.add_color_stop_rgba(0, 0, 0, 0, 0.75); g.add_color_stop_rgba(1, 0, 0, 0, 0)
    elif layout == "text_right":
        g = cairo.LinearGradient(brand.W, 0, brand.W * 0.4, 0)
        g.add_color_stop_rgba(0, 0, 0, 0, 0.75); g.add_color_stop_rgba(1, 0, 0, 0, 0)
    else:
        g = cairo.LinearGradient(0, brand.H, 0, brand.H * 0.45)
        g.add_color_stop_rgba(0, 0, 0, 0, 0.8); g.add_color_stop_rgba(1, 0, 0, 0, 0)
    c.set_source(g)
    c.paint()
    size = 150 if max(len(x) for x in text_lines) <= 10 else 124
    n = len(text_lines)
    if layout == "text_bottom":
        x, align, y0 = brand.W / 2, "center", brand.H - 90 - (n - 1) * size * 1.02
    elif layout == "text_left":
        x, align, y0 = 90, "left", brand.H / 2 + size * 0.35 - (n - 1) * size * 0.51
    else:
        x, align, y0 = brand.W - 90, "right", brand.H / 2 + size * 0.35 - (n - 1) * size * 0.51
    boxes = []
    for i, line in enumerate(text_lines):
        y = y0 + i * size * 1.02
        col = accent if i == n - 1 else (1, 1, 1)
        c.select_font_face(brand.FONT_HEAVY, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        c.set_font_size(size)
        w = c.text_extents(line).x_advance
        x0 = x - w / 2 if align == "center" else (x - w if align == "right" else x)
        c.new_path(); c.move_to(x0, y); c.text_path(line)
        c.set_source_rgba(0, 0, 0, 0.95); c.set_line_width(size * 0.12); c.set_line_join(cairo.LINE_JOIN_ROUND)
        c.stroke_preserve()
        c.set_source_rgb(*col); c.fill()
        boxes.append((x0, y - size * 0.75, w, size * 0.8))
    buf = np.frombuffer(s.get_data(), np.uint8).reshape(brand.H, brand.W, 4)[..., [2, 1, 0]].copy()
    img = Image.fromarray(buf).resize((TW, TH), Image.LANCZOS)
    sc = TW / brand.W
    return img, [(bx * sc, by * sc, bw * sc, bh * sc) for bx, by, bw, bh in boxes], size * sc


def _lum(a):
    a = a.astype(float) / 255
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def score(img, boxes, text_px):
    a = np.asarray(img)
    L = _lum(a)
    # text contrast: text pixels vs a ring around the text box
    contr = []
    for x, y, w, h in boxes:
        x0, y0, x1, y1 = int(max(0, x)), int(max(0, y)), int(min(TW, x + w)), int(min(TH, y + h))
        if x1 <= x0 or y1 <= y0:
            return {"total": -1, "why": "text off-canvas"}
        inner = L[y0:y1, x0:x1]
        bright = np.percentile(inner, 90)
        X0, Y0, X1, Y1 = max(0, x0 - 40), max(0, y0 - 40), min(TW, x1 + 40), min(TH, y1 + 40)
        ring = np.concatenate([L[Y0:y0, X0:X1].ravel(), L[y1:Y1, X0:X1].ravel()]) if Y1 > y1 or y0 > Y0 else inner.ravel()
        contr.append((bright + 0.05) / (np.median(ring) + 0.05))
    contrast = float(min(contr))
    off = any(x < 20 or x + w > TW - 20 for x, y, w, h in boxes)
    # phone-size legibility: text height at 168px-wide preview (YouTube mobile list)
    phone_px = text_px * 168 / TW
    # colourfulness (Hasler & Suesstrunk)
    rg = a[..., 0].astype(float) - a[..., 1]
    yb = 0.5 * (a[..., 0].astype(float) + a[..., 1]) - a[..., 2]
    colourful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    brightness = float(L.mean())
    subject = float(np.percentile(L, 99) - np.percentile(L, 50))
    total = (min(contrast, 12) / 12 * 35 + min(phone_px, 16) / 16 * 20 + min(colourful, 70) / 70 * 20
             + min(brightness, 0.25) / 0.25 * 10 + min(subject, 0.8) / 0.8 * 15 - (40 if off else 0))
    return {"total": round(total, 2), "contrast": round(contrast, 2), "phone_text_px": round(phone_px, 1),
            "colourfulness": round(colourful, 1), "brightness": round(brightness, 3), "subject_contrast": round(subject, 3),
            "text_off_edge": off}


def make(plan, out_dir, max_concepts=8):
    """plan['thumbnail'] = {"texts": [["SUN →", "BLACK HOLE?"], ...], "heroes": [scene-like dicts]}"""
    os.makedirs(out_dir, exist_ok=True)
    spec = plan.get("thumbnail", {})
    env = scenes.Env(plan.get("palette", "deep_space"), plan.get("seed", 1))
    accents = [env.pal["accent"], (1.0, 0.86, 0.25), env.pal["cool"]]
    combos = list(itertools.product(range(len(spec["heroes"])), range(len(spec["texts"])),
                                    ["text_left", "text_right", "text_bottom"], range(len(accents))))
    rng = np.random.default_rng(plan.get("seed", 1))
    rng.shuffle(combos)
    results = []
    for k, (hi, ti, layout, ai) in enumerate(combos[:max_concepts]):
        img, boxes, tpx = _render_concept(spec["heroes"][hi], spec["texts"][ti], layout, accents[ai], env)
        sc = score(img, boxes, tpx)
        p = os.path.join(out_dir, f"concept_{k}.jpg")
        img.save(p, quality=92)
        results.append({"file": p, "hero": hi, "text": spec["texts"][ti], "layout": layout, "accent": ai, **sc})
    results.sort(key=lambda r: -r["total"])
    best = os.path.join(out_dir, "thumbnail.jpg")
    Image.open(results[0]["file"]).save(best, quality=90)
    json.dump(results, open(os.path.join(out_dir, "thumbnail_scores.json"), "w"), indent=1)
    return best, results
