"""Low-level drawing helpers on top of Cairo + numpy."""
import math
import cairo
import numpy as np

from . import brand
from .ease import clamp


# ---------------------------------------------------------------- surfaces
def rgba_to_surface(rgb, alpha):
    """rgb: HxWx3 float 0..1 (straight), alpha: HxW float 0..1 -> Cairo surface."""
    h, w = alpha.shape
    a = np.clip(alpha, 0, 1)[..., None]
    pre = np.clip(rgb, 0, 1) * a
    buf = np.empty((h, w, 4), dtype=np.uint8)
    buf[..., 0] = (pre[..., 2] * 255).astype(np.uint8)  # B
    buf[..., 1] = (pre[..., 1] * 255).astype(np.uint8)  # G
    buf[..., 2] = (pre[..., 0] * 255).astype(np.uint8)  # R
    buf[..., 3] = (a[..., 0] * 255).astype(np.uint8)
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_ARGB32, w)
    if stride != w * 4:
        padded = np.zeros((h, stride // 4, 4), dtype=np.uint8)
        padded[:, :w] = buf
        buf = padded
    return cairo.ImageSurface.create_for_data(memoryview(np.ascontiguousarray(buf)), cairo.FORMAT_ARGB32, w, h, stride)


def paint_array(ctx, rgb, alpha, cx, cy, scale=1.0, opacity=1.0, op=None):
    """Paint a numpy RGBA image centred at (cx, cy) in current user space."""
    surf = rgba_to_surface(rgb, alpha)
    h, w = alpha.shape
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(scale, scale)
    ctx.translate(-w / 2, -h / 2)
    ctx.set_source_surface(surf, 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_GOOD)
    if op is not None:
        ctx.set_operator(op)
    ctx.paint_with_alpha(opacity)
    ctx.restore()


# ---------------------------------------------------------------- basics
def background(ctx, pal, t=0.0):
    g = cairo.LinearGradient(0, 0, 0, brand.H)
    g.add_color_stop_rgb(0, *pal["bg_top"])
    g.add_color_stop_rgb(1, *pal["bg_bottom"])
    ctx.set_source(g)
    ctx.paint()


def vignette(ctx, strength=0.55):
    g = cairo.RadialGradient(brand.W / 2, brand.H / 2, brand.H * 0.35, brand.W / 2, brand.H / 2, brand.W * 0.75)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0, 0, 0, strength)
    ctx.set_source(g)
    ctx.paint()


def glow(ctx, x, y, r, color, alpha=1.0, falloff=(0.0, 0.35, 1.0)):
    g = cairo.RadialGradient(x, y, 0, x, y, r)
    g.add_color_stop_rgba(falloff[0], *color, alpha)
    g.add_color_stop_rgba(falloff[1], *color, alpha * 0.35)
    g.add_color_stop_rgba(falloff[2], *color, 0)
    ctx.set_source(g)
    ctx.new_path()
    ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.fill()


class Starfield:
    """Deterministic star layers with parallax relative to the scene camera."""

    def __init__(self, seed=7, count=900):
        rng = np.random.default_rng(seed)
        self.x = rng.uniform(-1.2, 1.2, count) * brand.W
        self.y = rng.uniform(-1.2, 1.2, count) * brand.H
        self.depth = rng.choice([0.05, 0.12, 0.25], count, p=[0.6, 0.3, 0.1])
        self.size = rng.gamma(1.6, 0.55, count) + 0.35
        self.bright = rng.uniform(0.25, 1.0, count)
        self.phase = rng.uniform(0, 6.28, count)
        tint = rng.uniform(0, 1, count)
        self.col = np.stack([0.80 + 0.2 * tint, 0.86 + 0.1 * tint, 1.0 - 0.15 * tint], 1)

    def draw(self, ctx, cam, t, alpha=1.0):
        cx, cy, z = cam
        for i in range(len(self.x)):
            d = self.depth[i]
            zz = 1 + (z - 1) * d
            sx = (self.x[i] - cx * d) * zz
            sy = (self.y[i] - cy * d) * zz
            sx = (sx + brand.W * 1.2) % (brand.W * 2.4) - brand.W * 1.2 + brand.W / 2
            sy = (sy + brand.H * 1.2) % (brand.H * 2.4) - brand.H * 1.2 + brand.H / 2
            if not (-4 < sx < brand.W + 4 and -4 < sy < brand.H + 4):
                continue
            tw = 0.75 + 0.25 * math.sin(t * 1.7 + self.phase[i])
            a = self.bright[i] * tw * alpha
            ctx.set_source_rgba(*self.col[i], a)
            ctx.new_path()
            ctx.arc(sx, sy, self.size[i] * (0.7 + 0.6 * d * 4) * min(zz, 2.5), 0, 2 * math.pi)
            ctx.fill()


# ---------------------------------------------------------------- text
def text(ctx, s, x, y, size=64, font=None, color=(1, 1, 1), alpha=1.0, align="center",
         tracking=0.0, weight_bold=True, shadow=True):
    """Draw single-line text. align: left|center|right. y is the baseline."""
    font = font or brand.FONT
    ctx.select_font_face(font, cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if weight_bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)
    width = text_width(ctx, s, tracking * size)
    if align == "center":
        x0 = x - width / 2
    elif align == "right":
        x0 = x - width
    else:
        x0 = x
    if shadow:
        _draw_chars(ctx, s, x0 + size * 0.03, y + size * 0.05, tracking * size, (0, 0, 0), alpha * 0.55)
    _draw_chars(ctx, s, x0, y, tracking * size, color, alpha)
    return width


def text_width(ctx, s, track_px=0.0):
    if not track_px:
        return ctx.text_extents(s).x_advance
    return sum(ctx.text_extents(c).x_advance for c in s) + track_px * (len(s) - 1)


def _draw_chars(ctx, s, x, y, track_px, color, alpha):
    ctx.set_source_rgba(*color, alpha)
    if not track_px:
        ctx.move_to(x, y)
        ctx.show_text(s)
        return
    for c in s:
        ctx.move_to(x, y)
        ctx.show_text(c)
        x += ctx.text_extents(c).x_advance + track_px


def wrap(ctx, s, max_width, size, font=None):
    ctx.select_font_face(font or brand.FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if ctx.text_extents(trial).x_advance > max_width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def rounded_rect(ctx, x, y, w, h, r):
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.close_path()


def dashed_circle(ctx, x, y, r, color, alpha, width=2.0, dash=(10, 10), offset=0.0):
    ctx.save()
    ctx.set_dash(dash, offset)
    ctx.set_line_width(width)
    ctx.set_source_rgba(*color, alpha)
    ctx.new_path()
    ctx.arc(x, y, r, 0, 2 * math.pi)
    ctx.stroke()
    ctx.restore()


def mix(c1, c2, t):
    t = clamp(t)
    return tuple(a + (b - a) * t for a, b in zip(c1, c2))
