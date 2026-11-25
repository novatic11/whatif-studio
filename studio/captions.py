"""Burned-in, word-synchronised subtitles.

longform: one clean line at the bottom, the spoken word highlighted.
shorts:   1-3 big words at a time, pop-in, heavy outline, active word in accent.
Timing comes from Kokoro's word timestamps, so captions never drift."""
import math
import re

import cairo

from . import brand
from .ease import out_back, window

STYLES = {
    "longform": {"max_chars": 40, "max_words": 9, "max_dur": 3.2, "size": 46, "font": brand.FONT,
                 "upper": False, "y": -78, "box": True, "outline": 0},
    "shorts":   {"max_chars": 16, "max_words": 3, "max_dur": 1.4, "size": 96, "font": brand.FONT_HEAVY,
                 "upper": True, "y": 0.66, "box": False, "outline": 14},
}


def _sentences(words):
    out, cur = [], []
    for i, w in enumerate(words):
        if cur and w[1] - cur[-1][2] > 0.45:
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?]$", w[0]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _split_balanced(ws, n):
    """Split a word list into n lines of near-equal length, preferring breaks after commas."""
    if n <= 1 or len(ws) <= 1:
        return [ws]
    lens = [len(w[0]) + 1 for w in ws]
    total = sum(lens)
    best, best_cost = None, None
    for k in range(1, len(ws)):
        left = sum(lens[:k])
        cost = abs(left - total / n) - (6 if re.search(r"[,;:—]$", ws[k - 1][0]) else 0)
        if len(ws) - k < 2 and n == 2:
            cost += 50  # avoid orphan word
        if best_cost is None or cost < best_cost:
            best, best_cost = k, cost
    return [ws[:best]] + _split_balanced(ws[best:], n - 1)


def group_words(words, style="longform"):
    """words: [(text, start, end)] absolute seconds -> [(start, end, [words])]."""
    st = STYLES[style]
    groups = []
    for sent in _sentences(words):
        chars = sum(len(w[0]) + 1 for w in sent)
        n = max(math.ceil(chars / st["max_chars"]), math.ceil(len(sent) / st["max_words"]),
                math.ceil((sent[-1][2] - sent[0][1]) / st["max_dur"]), 1)
        groups += [g for g in _split_balanced(sent, n) if g]
    out = []
    for i, g in enumerate(groups):
        end = g[-1][2] + 0.25
        if i + 1 < len(groups):
            end = min(end, groups[i + 1][0][1])
        out.append((g[0][1], end, g))
    return out


def _set_font(ctx, st):
    ctx.select_font_face(st["font"], cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(st["size"])


def draw(ctx, t, groups, pal, style="longform"):
    st = STYLES[style]
    g = next((g for g in groups if g[0] <= t < g[1]), None)
    if g is None:
        return
    start, end, words = g
    _set_font(ctx, st)
    toks = [(w[0].upper() if st["upper"] else w[0], w[1], w[2]) for w in words]
    space = ctx.text_extents(" ").x_advance
    widths = [ctx.text_extents(x[0]).x_advance for x in toks]
    total = sum(widths) + space * (len(toks) - 1)
    y = st["y"] + brand.H if st["y"] < 0 else st["y"] * brand.H
    x = brand.W / 2 - total / 2
    fade = min(window(t, start, 0.08), 1 - window(t, end - 0.06, 0.06))
    ctx.save()
    if style == "shorts":
        s = 0.8 + 0.2 * out_back(window(t, start, 0.18))
        ctx.translate(brand.W / 2, y)
        ctx.scale(s, s)
        ctx.translate(-brand.W / 2, -y)
    if st["box"]:
        pad = st["size"] * 0.38
        asc = st["size"] * 0.78
        ctx.set_source_rgba(0, 0, 0, 0.50 * fade)
        _round(ctx, x - pad, y - asc - pad * 0.55, total + pad * 2, asc + pad * 1.45, 12)
        ctx.fill()
    for (txt, ws, we), wdt in zip(toks, widths):
        active = ws - 0.03 <= t < we + 0.08
        spoken = t >= ws - 0.03
        if style == "longform":
            col = pal["accent"] if active else pal["text"]
            a = fade * (1.0 if spoken else 0.72)
        else:
            col = pal["accent"] if active else (1, 1, 1)
            a = fade
        if st["outline"]:
            ctx.new_path()
            ctx.move_to(x, y)
            ctx.text_path(txt)
            ctx.set_source_rgba(0, 0, 0, 0.9 * a)
            ctx.set_line_width(st["outline"])
            ctx.set_line_join(cairo.LINE_JOIN_ROUND)
            ctx.stroke_preserve()
            ctx.set_source_rgba(*col, a)
            ctx.fill()
        else:
            ctx.set_source_rgba(0, 0, 0, 0.6 * a)
            ctx.move_to(x + 2, y + 3)
            ctx.show_text(txt)
            ctx.set_source_rgba(*col, a)
            ctx.move_to(x, y)
            ctx.show_text(txt)
        x += wdt + space
    ctx.restore()


def _round(ctx, x, y, w, h, r):
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.close_path()
