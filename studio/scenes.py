"""Reusable scene components. Each scene type is a function
    render(ctx, t, dur, params, env)
where t is seconds since the scene started. Numeric params accept keyframes
(see ease.kf). Scripts pick and configure these; new types are added here."""
import math

import cairo
import numpy as np

from . import bodies, brand, draw
from .ease import clamp, kf, out_back, out_cubic, in_expo, smooth, window, in_out_cubic

SCENES = {}


def scene(name):
    def deco(fn):
        SCENES[name] = fn
        return fn
    return deco


class Env:
    """Per-render shared state (palette, starfield, seed)."""

    def __init__(self, palette_variant="deep_space", seed=1):
        self.pal = brand.palette(palette_variant)
        self.stars = draw.Starfield(seed=seed)
        self.seed = seed


# ------------------------------------------------------------ camera helpers
class Camera:
    def __init__(self, x=0.0, y=0.0, zoom=1.0, shake=0.0, t=0.0):
        self.x, self.y, self.zoom = x, y, zoom
        if shake > 0:
            self.x += shake * math.sin(t * 47.0) * 6
            self.y += shake * math.cos(t * 39.0) * 6

    def to_screen(self, wx, wy):
        return ((wx - self.x) * self.zoom + brand.W / 2, (wy - self.y) * self.zoom + brand.H / 2)


def _camera(p, t):
    c = kf(p.get("camera", [0, 0, 1]), t)
    return Camera(c[0], c[1], c[2], kf(p.get("shake", 0.0), t), t)


# ------------------------------------------------------------ body drawing
def _draw_star(ctx, sx, sy, rpx, light, env, seed, t):
    if rpx < 0.5:
        return
    draw.glow(ctx, sx, sy, rpx * 2.8, (1.0, 0.45, 0.10), 0.42 * min(light, 1.5))
    rq = max(2, int(rpx))
    rgb, a = bodies.render_sphere("star", rq, rot=t * 0.02, emissive=True, seed=seed, light=light)
    draw.paint_array(ctx, rgb, a, sx, sy, rpx / rq)
    ctx.set_operator(cairo.OPERATOR_ADD)
    draw.glow(ctx, sx, sy, rpx * 1.28, (1.0, 0.70, 0.35), 0.30 * light, (0.70, 0.84, 1.0))
    ctx.set_operator(cairo.OPERATOR_OVER)


def _draw_black_hole(ctx, sx, sy, rpx, t, disk=1.0, spin=1.0):
    rq = max(3, int(rpx))
    rgb, a = bodies.render_black_hole(rq, t=t, disk=disk, spin=spin)
    draw.paint_array(ctx, rgb, a, sx, sy, rpx / rq)


def _light_dir(sx, sy, lx, ly):
    dx, dy = lx - sx, ly - sy
    n = math.hypot(dx, dy) or 1
    return (dx / n * 0.95, dy / n * 0.95, 0.30)


def _draw_planet(ctx, b, sx, sy, rpx, t, light_pos, light):
    ld = _light_dir(sx, sy, *light_pos) if light_pos else tuple(b.get("light_dir", (-0.8, -0.2, 0.55)))
    rq = max(2, int(rpx))
    rgb, a = bodies.render_sphere(b.get("planet", "earth"), rq, rot=b.get("rot0", 0.0) + t * b.get("spin", 0.05),
                                  light_dir=ld, light=light, seed=b.get("seed", 3), cloud_rot=t * 0.012,
                                  frozen=kf(b.get("frozen", 0.0), t),
                                  atmo_strength=b.get("atmo", 0.9 if b.get("planet", "earth") == "earth" else 0.35))
    draw.paint_array(ctx, rgb, a, sx, sy, rpx / rq)


def _body_pos(b, t):
    if "orbit" in b:
        o = b["orbit"]
        ang = o.get("phase", 0.0) + 2 * math.pi * t / o.get("period", 20.0)
        return o["cx"] + o["r"] * math.cos(ang), o["cy"] + o["r"] * math.sin(ang) * o.get("squash", 1.0)
    return kf(b.get("x", 0), t), kf(b.get("y", 0), t)


@scene("cosmos")
def cosmos(ctx, t, dur, p, env):
    """Free camera over a 2D world of stars, planets and black holes.
    bodies: [{kind: star|planet|black_hole, x, y, r, ...}]"""
    cam = _camera(p, t)
    draw.background(ctx, env.pal)
    env.stars.draw(ctx, (cam.x, cam.y, cam.zoom), t, kf(p.get("star_alpha", 1.0), t))
    light_pos = None
    # first pass: guides (orbits, trails)
    for b in p.get("bodies", []):
        if "orbit" in b and (b.get("ghost_orbit") or b.get("trail")):
            o = b["orbit"]
            cx, cy = cam.to_screen(o["cx"], o["cy"])
            if b.get("ghost_orbit"):
                draw.dashed_circle(ctx, cx, cy, o["r"] * cam.zoom, env.pal["muted"], 0.35 * kf(b.get("ghost_alpha", 1.0), t), 2.0, (8, 12))
            if b.get("trail"):
                ang = o.get("phase", 0.0) + 2 * math.pi * t / o.get("period", 20.0)
                for i in range(40):
                    a0 = ang - i * 0.03
                    ctx.set_source_rgba(*env.pal["cool"], 0.55 * (1 - i / 40))
                    ctx.set_line_width(3)
                    ctx.arc(cx, cy, o["r"] * cam.zoom, a0 - 0.03, a0)
                    ctx.stroke()
    for b in p.get("bodies", []):
        wx, wy = _body_pos(b, t)
        sx, sy = cam.to_screen(wx, wy)
        r = kf(b.get("r", 50), t) * cam.zoom
        kind = b["kind"]
        if kind == "star":
            col = b.get("collapse")
            if col:
                at, cd = col["at"], col.get("dur", 1.2)
                u = window(t, at, cd)
                if u < 1:
                    rr = r * (1 - in_expo(u) * 0.995)
                    _draw_star(ctx, sx, sy, rr, kf(b.get("light", 1.0), t) * (1 + u * 0.8), env, b.get("seed", 5), t)
                v = window(t, at + cd, col.get("grow", 2.5))
                if t >= at + cd:
                    _draw_black_hole(ctx, sx, sy, col.get("bh_r", 40) * cam.zoom, t, disk=out_cubic(v), spin=1.0)
                    fl = max(0.0, 1 - (t - at - cd) / 0.9)
                    if fl > 0:
                        ctx.set_operator(cairo.OPERATOR_ADD)
                        draw.glow(ctx, sx, sy, 900 * fl + 200, (1.0, 0.9, 0.75), 0.9 * fl)
                        ctx.set_operator(cairo.OPERATOR_OVER)
                light_pos = (sx, sy)
            else:
                _draw_star(ctx, sx, sy, r, kf(b.get("light", 1.0), t), env, b.get("seed", 5), t)
                light_pos = (sx, sy)
        elif kind == "black_hole":
            _draw_black_hole(ctx, sx, sy, r, t, disk=kf(b.get("disk", 1.0), t))
            light_pos = light_pos or None
        elif kind == "planet":
            light = kf(b.get("light", 1.0), t)
            if b.get("light_dir"):
                _draw_planet(ctx, b, sx, sy, r, t, None, light)
            else:
                _draw_planet(ctx, b, sx, sy, r, t, light_pos or cam.to_screen(*b.get("light_from", (-5000, 0))), light)
        if b.get("label"):
            la = kf(b.get("label_alpha", 1.0), t)
            if la > 0.01:
                _label(ctx, sx, sy + r + 46, b["label"], env, la)
    draw.vignette(ctx)


def _label(ctx, x, y, s, env, alpha, size=30):
    draw.text(ctx, s, x, y, size, brand.FONT, env.pal["muted"], alpha, tracking=0.08)


# ------------------------------------------------------------ light travel diagram
@scene("light_travel")
def light_travel(ctx, t, dur, p, env):
    """Light (or any signal) crossing a distance, with a timer.
    params: start, end (s), counter_to (seconds shown), from_label, to_label, distance_label"""
    draw.background(ctx, env.pal)
    env.stars.draw(ctx, (0, 0, 1), t, 0.7)
    x0, x1, y = 300, 1600, 560
    start = p.get("start", 0.6)
    travel = max(0.5, p.get("end", start + 6.0) - start)
    u = window(t, start, travel)
    front = x0 + (x1 - x0) * u
    # dimension line
    a = smooth(window(t, 0.2, 0.8))
    ctx.set_source_rgba(*env.pal["muted"], 0.6 * a)
    ctx.set_line_width(2)
    for xx in (x0, x1):
        ctx.move_to(xx, y + 190); ctx.line_to(xx, y + 230); ctx.stroke()
    ctx.move_to(x0, y + 210); ctx.line_to(x0 + (x1 - x0) * a, y + 210); ctx.stroke()
    draw.text(ctx, p.get("distance_label", ""), (x0 + x1) / 2, y + 270, 32, brand.FONT, env.pal["muted"], a, tracking=0.06)
    # lit region ahead of the front, darkness behind it
    if 0 < u < 1:
        rr = max(1, front - x0)
        for k in range(10):  # soft glowing wavefront: stacked arcs fading behind the front
            ctx.set_source_rgba(1.0, 0.82, 0.50, 0.16 * (1 - k / 10) ** 2)
            ctx.set_line_width(26 - k * 2)
            ctx.new_path()
            ctx.arc(x0, y, max(1, rr - k * 14), -0.30, 0.30)
            ctx.stroke()
        ctx.set_source_rgba(1.0, 0.90, 0.65, 0.9)
        ctx.set_line_width(3)
        ctx.new_path()
        ctx.arc(x0, y, rr, -0.30, 0.30)
        ctx.stroke()
    # source (black hole) and Earth
    _draw_black_hole(ctx, x0, y, 46, t)
    earth_light = 1.0 - smooth(window(t, start + travel - 0.05, 1.6)) * 0.97
    b = {"planet": "earth", "spin": 0.08, "rot0": 2.0}
    _draw_planet(ctx, b, x1, y, 120, t, (x0, y), earth_light)
    _label(ctx, x0, y + 150, p.get("from_label", ""), env, a)
    _label(ctx, x1, y + 175, p.get("to_label", ""), env, a)
    # counter
    secs = int(p.get("counter_to", 499) * u)
    draw.text(ctx, p.get("counter_label", "TIME SINCE COLLAPSE"), brand.W / 2, 170, 28, brand.FONT, env.pal["muted"], a, tracking=0.18)
    draw.text(ctx, f"{secs // 60:02d}:{secs % 60:02d}", brand.W / 2, 270, 104, brand.FONT_MONO, env.pal["accent"], a)
    draw.vignette(ctx)


# ------------------------------------------------------------ title card
@scene("title_card")
def title_card(ctx, t, dur, p, env):
    draw.background(ctx, env.pal)
    env.stars.draw(ctx, (t * 6, 0, 1.0 + t * 0.01), t, 0.8)
    bh = p.get("backdrop", "black_hole")
    if bh == "black_hole":
        _draw_black_hole(ctx, brand.W / 2, 250, 62 + t * 2, t)
        g = cairo.LinearGradient(0, 330, 0, 520)
        g.add_color_stop_rgba(0, 0, 0, 0, 0)
        g.add_color_stop_rgba(1, 0, 0, 0, 0.6)
        ctx.set_source(g)
        ctx.rectangle(0, 330, brand.W, brand.H)
        ctx.fill()
    lines = p.get("lines", ["WHAT IF"])
    size = p.get("size", 110)
    y0 = brand.H / 2 + 110 - (len(lines) - 1) * size * 0.55
    for i, line in enumerate(lines):
        u = out_cubic(window(t, 0.25 + i * 0.25, 0.7))
        col = env.pal["accent"] if i == p.get("accent_line", -1) else env.pal["text"]
        draw.text(ctx, line, brand.W / 2, y0 + i * size * 1.1 + (1 - u) * 40, size, brand.FONT_HEAVY, col, u, tracking=0.02)
    u = window(t, 1.2, 0.8)
    draw.text(ctx, brand.CHANNEL_NAME, brand.W / 2, brand.H - 90, 28, brand.FONT, env.pal["muted"], u * 0.9, tracking=0.5)
    draw.vignette(ctx, 0.7)


# ------------------------------------------------------------ line chart
@scene("chart")
def chart(ctx, t, dur, p, env):
    """Animated line chart. params: title, x_label, y_label, points [[x,y],...],
    y_range [lo,hi], x_range, annotations [{x, text}], source (shown small)."""
    draw.background(ctx, env.pal)
    env.stars.draw(ctx, (0, 0, 1), t, 0.35)
    L, R, T, B = 260, 1680, 220, 860
    pts = p["points"]
    xr = p.get("x_range", [pts[0][0], pts[-1][0]])
    yr = p.get("y_range", [min(q[1] for q in pts), max(q[1] for q in pts)])
    X = lambda v: L + (v - xr[0]) / (xr[1] - xr[0]) * (R - L)
    Y = lambda v: B - (v - yr[0]) / (yr[1] - yr[0]) * (B - T)
    a = smooth(window(t, 0.1, 0.6))
    draw.text(ctx, p.get("title", ""), L, 150, 48, brand.FONT_HEAVY, env.pal["text"], a, align="left")
    ctx.set_line_width(2)
    for i in range(5):
        yy = T + (B - T) * i / 4
        ctx.set_source_rgba(*env.pal["muted"], 0.18 * a)
        ctx.move_to(L, yy); ctx.line_to(R, yy); ctx.stroke()
        val = yr[1] - (yr[1] - yr[0]) * i / 4
        draw.text(ctx, p.get("y_fmt", "{:.0f}").format(val), L - 24, yy + 10, 26, brand.FONT_MONO, env.pal["muted"], a, align="right", shadow=False)
    draw.text(ctx, p.get("x_label", ""), (L + R) / 2, B + 80, 28, brand.FONT, env.pal["muted"], a)
    prog = in_out_cubic(window(t, 0.6, p.get("draw_time", 3.0)))
    n = len(pts)
    upto = prog * (n - 1)
    ctx.set_line_width(6)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_source_rgba(*env.pal["accent"], 1)
    ctx.move_to(X(pts[0][0]), Y(pts[0][1]))
    last = (X(pts[0][0]), Y(pts[0][1]))
    for i in range(1, n):
        if i <= upto:
            last = (X(pts[i][0]), Y(pts[i][1]))
        else:
            f = upto - (i - 1)
            if f <= 0:
                break
            last = (X(pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f), Y(pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f))
        ctx.line_to(*last)
    ctx.stroke()
    draw.glow(ctx, last[0], last[1], 40, env.pal["accent"], 0.8)
    for an in p.get("annotations", []):
        u = window(upto / max(n - 1, 1) * (xr[1] - xr[0]) + xr[0], an["x"], 0.001)
        if u > 0:
            ax = X(an["x"])
            ctx.set_source_rgba(*env.pal["text"], 0.5)
            ctx.set_line_width(2)
            ctx.move_to(ax, T); ctx.line_to(ax, B); ctx.stroke()
            draw.text(ctx, an["text"], ax + 14, T + 40, 28, brand.FONT, env.pal["text"], 0.9, align="left")
    if p.get("source"):
        draw.text(ctx, "Source: " + p["source"], R, B + 140, 22, brand.FONT, env.pal["muted"], 0.7 * a, align="right", shadow=False)
    draw.vignette(ctx)


# ------------------------------------------------------------ overlays (on top of any scene)
def overlay(ctx, t, items, env):
    """Kinetic typography and callouts: [{at, dur, text, style, x, y, size, color}]"""
    for it in items:
        at, d = it["at"], it.get("dur", 2.5)
        if not (at <= t <= at + d + 0.5):
            continue
        u_in = window(t, at, 0.45)
        u_out = 1 - window(t, at + d, 0.4)
        alpha = min(out_cubic(u_in), u_out)
        if alpha <= 0:
            continue
        style = it.get("style", "pop")
        x, y = it.get("x", brand.W / 2), it.get("y", brand.H * 0.78)
        col = env.pal.get(it.get("color", "text"), env.pal["text"])
        size = it.get("size", 72)
        if style == "pop":
            s = 0.75 + 0.25 * out_back(u_in)
            ctx.save()
            ctx.translate(x, y)
            ctx.scale(s, s)
            draw.text(ctx, it["text"], 0, 0, size, brand.FONT_HEAVY, col, alpha, tracking=0.03)
            ctx.restore()
        elif style == "label":
            draw.text(ctx, it["text"], x, y, it.get("size", 32), brand.FONT, col, alpha, tracking=0.12)
        elif style == "stat":
            draw.text(ctx, it.get("kicker", ""), x, y - size * 1.05, size * 0.36, brand.FONT, env.pal["muted"], alpha, tracking=0.2)
            draw.text(ctx, it["text"], x, y, size, brand.FONT_HEAVY, col, alpha)
        elif style == "lower":
            ctx.set_source_rgba(0, 0, 0, 0.45 * alpha)
            draw.rounded_rect(ctx, 80, brand.H - 300, 760, 110, 14)
            ctx.fill()
            ctx.set_source_rgba(*env.pal["accent"], alpha)
            ctx.rectangle(80, brand.H - 300, 8, 110)
            ctx.fill()
            draw.text(ctx, it["text"], 116, brand.H - 232, 40, brand.FONT_HEAVY, env.pal["text"], alpha, align="left")


# ------------------------------------------------------------ statement card
@scene("statement")
def statement(ctx, t, dur, p, env):
    """Big kinetic text beat. params: lines [str], accent_line, kicker, backdrop: stars|grid|pulse"""
    draw.background(ctx, env.pal)
    bd = p.get("backdrop", "stars")
    if bd == "stars":
        env.stars.draw(ctx, (t * 12, 0, 1.0 + t * 0.015), t, 0.8)
    elif bd == "grid":
        ctx.set_line_width(1)
        off = (t * 30) % 80
        for x in range(-80, brand.W + 80, 80):
            ctx.set_source_rgba(*env.pal["cool"], 0.07)
            ctx.move_to(x + off, 0); ctx.line_to(x + off, brand.H); ctx.stroke()
        for y in range(-80, brand.H + 80, 80):
            ctx.move_to(0, y + off); ctx.line_to(brand.W, y + off); ctx.stroke()
    elif bd == "pulse":
        for k in range(5):
            r = ((t * 140 + k * 220) % 1100)
            ctx.set_source_rgba(*env.pal["accent"], 0.18 * (1 - r / 1100))
            ctx.set_line_width(3); ctx.new_path()
            ctx.arc(brand.W / 2, brand.H / 2, r, 0, 2 * math.pi); ctx.stroke()
    lines = p.get("lines", [])
    size = p.get("size", 96 if brand.W > brand.H else 84)
    y0 = brand.H / 2 + size * 0.35 - (len(lines) - 1) * size * 0.58
    if p.get("kicker"):
        u = out_cubic(window(t, 0.05, 0.5))
        draw.text(ctx, p["kicker"], brand.W / 2, y0 - size * 1.1, size * 0.3, brand.FONT, env.pal["muted"], u, tracking=0.25)
    for i, line in enumerate(lines):
        u = out_cubic(window(t, 0.15 + i * p.get("stagger", 0.35), 0.55))
        col = env.pal["accent"] if i == p.get("accent_line", -1) else env.pal["text"]
        draw.text(ctx, line, brand.W / 2, y0 + i * size * 1.16 + (1 - u) * 30, size, brand.FONT_HEAVY, col, u, tracking=0.01)
    draw.vignette(ctx)


# ------------------------------------------------------------ comparison (bars or circles)
@scene("compare")
def compare(ctx, t, dur, p, env):
    """Animated comparison. params: title, mode: bars|circles, scale: diameter(default)|area, items: [{label, value, display, color}],
    log: bool (log scale for huge ranges), source, reveal_at (per-item times optional)"""
    draw.background(ctx, env.pal)
    env.stars.draw(ctx, (0, 0, 1), t, 0.3)
    items = p["items"]
    a = smooth(window(t, 0.05, 0.5))
    draw.text(ctx, p.get("title", ""), brand.W / 2, 150, 54, brand.FONT_HEAVY, env.pal["text"], a)
    vals = [it["value"] for it in items]
    f = (lambda v: math.log10(max(v, 1e-9))) if p.get("log") else (lambda v: v)
    lo = min(0, min(f(v) for v in vals)) if not p.get("log") else min(f(v) for v in vals) - 0.3
    hi = max(f(v) for v in vals)
    n = len(items)
    if p.get("mode", "bars") == "bars":
        top, bottom = 260, brand.H - 200
        bw = min(220, (brand.W - 300) / n * 0.6)
        for i, it in enumerate(items):
            at = it.get("at", 0.4 + i * 0.5)
            u = in_out_cubic(window(t, at, 1.1))
            x = 150 + (brand.W - 300) * (i + 0.5) / n
            h = (bottom - top) * (f(it["value"]) - lo) / (hi - lo + 1e-9) * u
            col = env.pal.get(it.get("color", "accent"), env.pal["accent"])
            g = cairo.LinearGradient(0, bottom - h, 0, bottom)
            g.add_color_stop_rgba(0, *col, 0.95); g.add_color_stop_rgba(1, *col, 0.45)
            ctx.set_source(g)
            draw.rounded_rect(ctx, x - bw / 2, bottom - h, bw, max(h, 1), min(14, bw / 4)); ctx.fill()
            ua = window(t, at + 0.6, 0.4)
            draw.text(ctx, it.get("display", f"{it['value']:,}"), x, bottom - h - 24, 44, brand.FONT_MONO, env.pal["text"], ua)
            draw.text(ctx, it["label"], x, bottom + 60, 30, brand.FONT, env.pal["muted"], a, tracking=0.06)
    else:  # circles side by side, area-true
        maxr = min(brand.H * 0.32, brand.W / (2.4 * n))
        for i, it in enumerate(items):
            at = it.get("at", 0.4 + i * 0.6)
            u = out_back(window(t, at, 0.9))
            frac = it["value"] / max(vals)
            r = max(maxr * (math.sqrt(frac) if p.get("scale") == "area" else frac), 3.0) * u
            x = brand.W * (i + 0.5) / n
            col = env.pal.get(it.get("color", "accent"), env.pal["accent"])
            draw.glow(ctx, x, brand.H / 2 + 40, max(r, 2) * 1.5, col, 0.25)
            ctx.set_source_rgba(*col, 0.9); ctx.new_path(); ctx.arc(x, brand.H / 2 + 40, max(r, 1.5), 0, 2 * math.pi); ctx.fill()
            ua = window(t, at + 0.5, 0.4)
            draw.text(ctx, it.get("display", str(it["value"])), x, brand.H / 2 + 40 + maxr + 70, 44, brand.FONT_MONO, env.pal["text"], ua)
            draw.text(ctx, it["label"], x, brand.H / 2 + 40 + maxr + 115, 28, brand.FONT, env.pal["muted"], ua, tracking=0.06)
    if p.get("source"):
        draw.text(ctx, "Source: " + p["source"], brand.W - 60, brand.H - 50, 20, brand.FONT, env.pal["muted"], 0.7 * a, align="right", shadow=False)
    draw.vignette(ctx)


# ------------------------------------------------------------ timeline
@scene("timeline")
def timeline(ctx, t, dur, p, env):
    """Horizontal timeline that pans as events appear.
    params: title, events: [{at (scene s), label, when, color}], span: [start_label, end_label]"""
    draw.background(ctx, env.pal)
    env.stars.draw(ctx, (t * 10, 0, 1), t, 0.4)
    ev = p["events"]
    n = len(ev)
    spacing = p.get("spacing", 520)
    a = smooth(window(t, 0, 0.5))
    if p.get("title"):
        draw.text(ctx, p["title"], brand.W / 2, 160, 50, brand.FONT_HEAVY, env.pal["text"], a)
    # camera follows the most recent revealed event
    shown = [i for i, e in enumerate(ev) if t >= e.get("at", 0.5 + i * 2.0)]
    focus = shown[-1] if shown else 0
    cam_x = 0.0
    for i in range(focus + 1):
        e0 = ev[i].get("at", 0.5 + i * 2.0)
        cam_x = cam_x + (i * spacing - cam_x) * in_out_cubic(window(t, e0, 0.8))
    y = brand.H / 2 + 40
    x_of = lambda i: brand.W / 2 + i * spacing - cam_x
    ctx.set_source_rgba(*env.pal["muted"], 0.5 * a); ctx.set_line_width(3)
    ctx.move_to(x_of(0) - 400, y); ctx.line_to(x_of(n - 1) + 400, y); ctx.stroke()
    for i, e in enumerate(ev):
        at = e.get("at", 0.5 + i * 2.0)
        u = out_back(window(t, at, 0.6))
        if u <= 0:
            continue
        x = x_of(i)
        col = env.pal.get(e.get("color", "accent"), env.pal["accent"])
        draw.glow(ctx, x, y, 40 * u, col, 0.6)
        ctx.set_source_rgba(*col, 1); ctx.new_path(); ctx.arc(x, y, 12 * u, 0, 2 * math.pi); ctx.fill()
        up = i % 2 == 0
        draw.text(ctx, e.get("when", ""), x, y + (-70 if up else 95), 40, brand.FONT_MONO, col, min(u, 1))
        for k, line in enumerate(draw.wrap(ctx, e["label"], spacing * 0.85, 32)[:3]):
            yy = y + (-130 - 40 * (len(draw.wrap(ctx, e["label"], spacing * 0.85, 32)[:3]) - 1 - k) if up else 150 + 40 * k)
            draw.text(ctx, line, x, yy, 32, brand.FONT, env.pal["text"], min(u, 1))
    draw.vignette(ctx)


# ------------------------------------------------------------ figures (life, animals, human body)
def _fill_subpaths(ctx):
    """Fill every sub-path of the current path on its own, so overlapping parts
    always merge into one silhouette whatever their winding direction."""
    path = list(ctx.copy_path())
    ctx.new_path()
    started = False
    for kind, pts in path:
        if kind == cairo.PATH_MOVE_TO:
            if started:
                ctx.fill()
            ctx.move_to(*pts)
            started = True
        elif kind == cairo.PATH_LINE_TO:
            ctx.line_to(*pts)
        elif kind == cairo.PATH_CURVE_TO:
            ctx.curve_to(*pts)
        elif kind == cairo.PATH_CLOSE_PATH:
            ctx.close_path()
    if started:
        ctx.fill()


def _color(env, c, default="accent"):
    if isinstance(c, (list, tuple)):
        return tuple(c)
    return env.pal.get(c or default, env.pal[default])


def draw_figure(ctx, shape, x, y, size, col, alpha, t, env, flip=False, rot=0.0, detail=None, glow=0.22):
    """Draw one silhouette from studio.figures.SHAPES as a single shaded form."""
    from .figures import SHAPES
    if alpha <= 0.003 or size <= 0.5:
        return
    fn = SHAPES[shape]
    if glow:
        draw.glow(ctx, x, y, size * 0.75, col, glow * alpha)
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rot)
    ctx.scale(-size if flip else size, size)
    ctx.push_group()
    ctx.set_source_rgb(1, 1, 1)
    fn(ctx, "base", t)
    _fill_subpaths(ctx)
    base = ctx.pop_group()
    ctx.push_group()
    ctx.set_source_rgb(1, 1, 1)
    fn(ctx, "detail", t)
    _fill_subpaths(ctx)
    det = ctx.pop_group()
    ctx.push_group()
    g = cairo.LinearGradient(-0.3, -0.5, 0.3, 0.5)
    g.add_color_stop_rgb(0, *draw.mix(col, (1, 1, 1), 0.28))
    g.add_color_stop_rgb(0.55, *col)
    g.add_color_stop_rgb(1, *[c * 0.62 for c in col])
    ctx.set_source(g)
    ctx.mask(base)
    dcol = detail if detail is not None else tuple(c * 0.42 for c in col)
    ctx.push_group()
    ctx.set_source_rgb(*dcol)
    ctx.mask(det)
    dg = ctx.pop_group()
    ctx.set_source(dg)
    ctx.mask(base)
    hl = cairo.RadialGradient(-0.18, -0.3, 0.0, -0.18, -0.3, 0.7)
    hl.add_color_stop_rgba(0, 1, 1, 1, 0.16)
    hl.add_color_stop_rgba(1, 1, 1, 1, 0.0)
    ctx.set_source(hl)
    ctx.mask(base)
    grp = ctx.pop_group()
    ctx.set_source(grp)
    ctx.paint_with_alpha(alpha)
    ctx.restore()


def _life(t, at, out, fade=0.5):
    """(alpha, scale, rise) for a figure that pops in at `at` and vanishes at `out`."""
    u_in = window(t, at, fade)
    a, s = out_cubic(u_in), 0.6 + 0.4 * out_back(u_in)
    rise = 0.0
    if out is not None:
        u_out = window(t, out, fade * 1.4)
        a *= 1 - u_out
        s *= 1 - 0.35 * u_out
        rise = 40 * smooth(u_out)
    return a, s, rise


@scene("figures")
def figures(ctx, t, dur, p, env):
    """Clean vector silhouettes of living things (see studio/figures.py SHAPES:
    person, head, bee, butterfly, beetle, flower, leaf, bird, dolphin, sea_slug, sun).
    params:
      backdrop: stars (default) | pulse | none
      title, kicker: optional heading near the top (y ~ 230)
      figures: [{shape, x, y, size (px tall), color (palette key or rgb), at, out,
                 to_color + tint_at (+ tint_dur) to recolour, detail_color, flip, rot,
                 bob (px), glow (0..1), label, label_color}]  x/y/size accept keyframes
      grid: {shape, cols, rows, x, y, cell, size, at, stagger, color,
             hi (first n icons), hi_color, hi_at, rest: dim|vanish}  (icon array, e.g. "87 of 115")
      swarm: {shapes, count, seed, area [x0,y0,x1,y1], size, color, at, out}
             (many small drifting figures; `out` makes them blink away one by one)
    Keep important figures in the upper 60% of vertical frames."""
    draw.background(ctx, env.pal)
    bd = p.get("backdrop", "stars")
    if bd == "stars":
        env.stars.draw(ctx, (t * 8, 0, 1.0 + t * 0.01), t, 0.5)
    elif bd == "pulse":
        for k in range(4):
            r = ((t * 120 + k * 260) % 1100)
            ctx.set_source_rgba(*env.pal["accent"], 0.14 * (1 - r / 1100))
            ctx.set_line_width(3); ctx.new_path()
            ctx.arc(brand.W / 2, brand.H * 0.4, r, 0, 2 * math.pi); ctx.stroke()
    ta = smooth(window(t, 0.05, 0.5))
    if p.get("kicker"):
        draw.text(ctx, p["kicker"], brand.W / 2, 170, 28, brand.FONT, env.pal["muted"], ta, tracking=0.25)
    if p.get("title"):
        draw.text(ctx, p["title"], brand.W / 2, 240, 56, brand.FONT_HEAVY, env.pal["text"], ta)

    sw = p.get("swarm")
    if sw:
        rng = np.random.default_rng(sw.get("seed", 7))
        x0, y0, x1, y1 = sw.get("area", [80, 300, brand.W - 80, brand.H * 0.6])
        shapes = sw.get("shapes", ["bee", "butterfly", "beetle"])
        n = sw.get("count", 24)
        out = sw.get("out")
        for i in range(n):
            px, py = rng.uniform(x0, x1), rng.uniform(y0, y1)
            ph, sp = rng.uniform(0, 6.28), rng.uniform(0.4, 0.9)
            sz = sw.get("size", 60) * rng.uniform(0.7, 1.25)
            shp = shapes[i % len(shapes)]
            o = None if out is None else out + rng.uniform(0, sw.get("out_spread", 1.2))
            a, s, _ = _life(t, sw.get("at", 0) + rng.uniform(0, 0.6), o, 0.35)
            if o is not None and t >= o:
                draw.glow(ctx, px, py, sz * (0.6 + window(t, o, 0.5)), env.pal["text"], 0.35 * (1 - window(t, o, 0.6)))
            xx = px + 26 * math.sin(t * sp + ph)
            yy = py + 18 * math.sin(t * sp * 1.3 + ph * 2)
            draw_figure(ctx, shp, xx, yy, sz * s, _color(env, sw.get("color"), "accent"), a,
                        t + ph, env, flip=(math.cos(t * sp + ph) < 0), rot=0.15 * math.sin(ph), glow=0.12)

    gr = p.get("grid")
    if gr:
        cols, rows = gr.get("cols", 10), gr.get("rows", 5)
        cell = gr.get("cell", 88)
        gx = gr.get("x", brand.W / 2) - cell * (cols - 1) / 2
        gy = gr.get("y", 520) - cell * (rows - 1) / 2
        hi_at = gr.get("hi_at")
        for i in range(cols * rows):
            r_, c_ = divmod(i, cols)
            a, s, _ = _life(t, gr.get("at", 0.2) + i * gr.get("stagger", 0.02), None, 0.4)
            col = _color(env, gr.get("color"), "muted")
            if hi_at is not None:
                u = window(t, hi_at + 0.01 * i, 0.5)
                if i < gr.get("hi", 0):
                    col = draw.mix(col, _color(env, gr.get("hi_color"), "accent"), u)
                elif gr.get("rest", "dim") == "vanish":
                    a *= 1 - u; s *= 1 - 0.4 * u
                else:
                    a *= 1 - 0.65 * u
            draw_figure(ctx, gr.get("shape", "flower"), gx + c_ * cell, gy + r_ * cell,
                        gr.get("size", cell * 0.8) * s, col, a, t + i, env, glow=0)

    for f in p.get("figures", []):
        a, s, rise = _life(t, f.get("at", 0.0), f.get("out"))
        if a <= 0:
            continue
        col = _color(env, f.get("color"), "accent")
        if f.get("to_color") is not None:
            u = smooth(window(t, f.get("tint_at", 1.0), f.get("tint_dur", 1.2)))
            col = draw.mix(col, _color(env, f["to_color"]), u)
        x, y, size = kf(f.get("x", brand.W / 2), t), kf(f.get("y", brand.H * 0.4), t), kf(f.get("size", 400), t)
        y += f.get("bob", 0) * math.sin(t * 1.4 + x * 0.01) - rise
        det = f.get("detail_color")
        draw_figure(ctx, f["shape"], x, y, size * s, col, a * f.get("alpha", 1.0), t, env,
                    flip=f.get("flip", False), rot=kf(f.get("rot", 0.0), t),
                    detail=_color(env, det) if det is not None else None, glow=f.get("glow", 0.22))
        if f.get("label"):
            draw.text(ctx, f["label"], x, y + size * 0.62, f.get("label_size", 34), brand.FONT_HEAVY,
                      _color(env, f.get("label_color"), "text"), a, tracking=0.08)
    draw.vignette(ctx)
