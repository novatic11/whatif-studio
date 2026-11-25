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
