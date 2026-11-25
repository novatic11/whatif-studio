"""Vector silhouette library for the `figures` scene (life, animals, the human body).

Each shape is drawn in unit space (about 1.0 tall, centred on 0,0, facing right)
as a set of sub-paths. The scene renders the sub-paths as ONE merged mask and
fills it with a single shaded gradient, so every figure reads as one clean
silhouette. Optional "detail" paths (stripes, veins, a brain...) are drawn as a
second mask in a darker or custom tone, clipped to the silhouette.

Shape functions: fn(ctx, layer, t) with layer in {"base", "detail"}; t drives
gentle idle motion (wing beats, swaying). Add new shapes to SHAPES.
"""
import math


# ------------------------------------------------------------ primitives
def ellipse(ctx, x, y, rx, ry, rot=0.0):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rot)
    ctx.scale(rx, ry)
    ctx.new_sub_path()
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()


def circle(ctx, x, y, r):
    ctx.new_sub_path()
    ctx.arc(x, y, r, 0, 2 * math.pi)


def capsule(ctx, x1, y1, x2, y2, r):
    a = math.atan2(y2 - y1, x2 - x1)
    ctx.new_sub_path()
    ctx.arc(x2, y2, r, a - math.pi / 2, a + math.pi / 2)
    ctx.arc(x1, y1, r, a + math.pi / 2, a + 3 * math.pi / 2)
    ctx.close_path()


def poly(ctx, pts):
    ctx.new_sub_path()
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)
    ctx.close_path()


# ------------------------------------------------------------ shapes
def person(ctx, layer, t):
    """Standing human, front view."""
    if layer != "base":
        return
    circle(ctx, 0, -0.405, 0.085)
    capsule(ctx, 0, -0.33, 0, -0.30, 0.035)          # neck
    ctx.new_sub_path()                                # torso
    ctx.move_to(-0.15, -0.27)
    ctx.curve_to(-0.17, -0.10, -0.12, 0.02, -0.105, 0.08)
    ctx.line_to(0.105, 0.08)
    ctx.curve_to(0.12, 0.02, 0.17, -0.10, 0.15, -0.27)
    ctx.curve_to(0.08, -0.31, -0.08, -0.31, -0.15, -0.27)
    ctx.close_path()
    sw = 0.012 * math.sin(t * 1.3)
    capsule(ctx, -0.155, -0.24, -0.20 - sw, 0.05, 0.038)   # arms
    capsule(ctx, 0.155, -0.24, 0.20 + sw, 0.05, 0.038)
    capsule(ctx, -0.055, 0.06, -0.07, 0.46, 0.05)     # legs
    capsule(ctx, 0.055, 0.06, 0.07, 0.46, 0.05)


def head(ctx, layer, t):
    """Human head in profile facing right; detail layer is the brain."""
    if layer == "base":
        ctx.new_sub_path()
        ctx.move_to(-0.05, 0.48)                       # back of neck
        ctx.curve_to(-0.06, 0.32, -0.30, 0.22, -0.30, -0.05)
        ctx.curve_to(-0.30, -0.36, -0.05, -0.48, 0.10, -0.46)
        ctx.curve_to(0.27, -0.44, 0.33, -0.26, 0.31, -0.10)   # forehead
        ctx.curve_to(0.31, -0.06, 0.30, -0.03, 0.33, 0.04)    # brow -> nose
        ctx.line_to(0.37, 0.12)
        ctx.curve_to(0.37, 0.14, 0.33, 0.15, 0.31, 0.15)
        ctx.curve_to(0.32, 0.18, 0.31, 0.21, 0.32, 0.23)      # lips
        ctx.curve_to(0.30, 0.27, 0.27, 0.30, 0.22, 0.31)      # chin
        ctx.curve_to(0.18, 0.32, 0.12, 0.31, 0.10, 0.34)
        ctx.line_to(0.12, 0.48)
        ctx.close_path()
    else:
        ellipse(ctx, 0.0, -0.20, 0.22, 0.155, -0.12)


def bee(ctx, layer, t):
    """Honeybee, side view; detail = abdomen stripes."""
    if layer == "base":
        ellipse(ctx, -0.13, 0.06, 0.25, 0.175, 0.12)            # abdomen
        poly(ctx, [(-0.36, 0.08), (-0.46, 0.13), (-0.35, 0.14)])  # sting
        circle(ctx, 0.13, 0.0, 0.125)                          # thorax
        circle(ctx, 0.30, 0.03, 0.09)                          # head
        capsule(ctx, 0.33, -0.04, 0.42, -0.17, 0.012)          # antenna
        flap = 0.75 + 0.25 * math.sin(t * 9.0)
        ellipse(ctx, 0.0, -0.20, 0.19, 0.085 * flap, -0.45)    # wings
        ellipse(ctx, 0.12, -0.23, 0.15, 0.07 * flap, -0.85)
        for dx in (0.06, 0.14, 0.22):                          # legs
            capsule(ctx, dx, 0.08, dx - 0.04, 0.27, 0.014)
    else:
        ctx.save()
        ellipse(ctx, -0.13, 0.06, 0.25, 0.175, 0.12)
        ctx.clip()
        for x in (-0.25, -0.12, 0.01):
            ctx.rectangle(x, -0.3, 0.055, 0.7)
        ctx.fill()
        ctx.restore()


def butterfly(ctx, layer, t):
    """Butterfly, top view, slow wing beats; detail = wing spots."""
    f = 0.62 + 0.38 * abs(math.cos(t * 2.4))
    if layer == "base":
        capsule(ctx, 0, -0.22, 0, 0.24, 0.032)
        circle(ctx, 0, -0.25, 0.045)
        capsule(ctx, -0.01, -0.28, -0.09, -0.44, 0.01)
        capsule(ctx, 0.01, -0.28, 0.09, -0.44, 0.01)
        for s in (-1, 1):
            ctx.save()
            ctx.scale(f, 1)
            ellipse(ctx, s * 0.25, -0.10, 0.25, 0.19, s * -0.45)
            ellipse(ctx, s * 0.17, 0.16, 0.16, 0.15, s * 0.5)
            ctx.restore()
    else:
        for s in (-1, 1):
            ctx.save()
            ctx.scale(f, 1)
            circle(ctx, s * 0.30, -0.14, 0.06)
            circle(ctx, s * 0.19, 0.18, 0.04)
            ctx.restore()


def beetle(ctx, layer, t):
    """Beetle, top view; detail = wing-case seam."""
    if layer == "base":
        ellipse(ctx, 0, 0.10, 0.22, 0.30)
        ellipse(ctx, 0, -0.22, 0.15, 0.09)
        circle(ctx, 0, -0.33, 0.07)
        for s in (-1, 1):
            capsule(ctx, s * 0.03, -0.38, s * 0.12, -0.49, 0.012)
            for (y0, x1, y1) in ((-0.16, 0.32, -0.28), (0.0, 0.34, 0.02), (0.14, 0.31, 0.34)):
                capsule(ctx, s * 0.12, y0, s * x1, y1, 0.016)
    else:
        capsule(ctx, 0, -0.14, 0, 0.38, 0.009)


def flower(ctx, layer, t):
    """Flower on a stem; detail = flower centre."""
    sway = 0.03 * math.sin(t * 1.1)
    cx, cy = sway, -0.22
    if layer == "base":
        ctx.new_sub_path()
        ctx.move_to(-0.02, 0.5)
        ctx.curve_to(-0.02, 0.2, cx - 0.02, 0.0, cx - 0.02, cy)
        ctx.line_to(cx + 0.02, cy)
        ctx.curve_to(cx + 0.02, 0.0, 0.02, 0.2, 0.02, 0.5)
        ctx.close_path()
        ellipse(ctx, 0.10, 0.22, 0.10, 0.04, -0.5)
        for k in range(6):
            a = k * math.pi / 3 + t * 0.15
            ellipse(ctx, cx + 0.12 * math.cos(a), cy + 0.12 * math.sin(a), 0.11, 0.065, a)
    else:
        circle(ctx, cx, cy, 0.075)


def leaf(ctx, layer, t):
    """Single leaf, tip up; detail = midrib and veins."""
    if layer == "base":
        ctx.new_sub_path()
        ctx.move_to(0, -0.48)
        ctx.curve_to(0.30, -0.30, 0.30, 0.18, 0, 0.36)
        ctx.curve_to(-0.30, 0.18, -0.30, -0.30, 0, -0.48)
        ctx.close_path()
        capsule(ctx, 0, 0.30, 0.02, 0.49, 0.018)
    else:
        capsule(ctx, 0, -0.40, 0, 0.34, 0.009)
        for k in range(4):
            y = -0.22 + k * 0.13
            capsule(ctx, 0, y + 0.07, 0.15 - k * 0.01, y - 0.02, 0.006)
            capsule(ctx, 0, y + 0.07, -0.15 + k * 0.01, y - 0.02, 0.006)


def bird(ctx, layer, t):
    """Small bird in flight, side view, wing beats."""
    if layer != "base":
        return
    w = math.sin(t * 4.0)
    ellipse(ctx, 0, 0.05, 0.26, 0.085, -0.05)
    circle(ctx, 0.25, 0.0, 0.07)
    poly(ctx, [(0.30, -0.025), (0.42, 0.01), (0.30, 0.03)])
    poly(ctx, [(-0.20, 0.03), (-0.46, -0.04), (-0.44, 0.10), (-0.20, 0.09)])
    tip_y = -0.40 * w
    ctx.new_sub_path()
    ctx.move_to(-0.10, 0.02)
    ctx.curve_to(-0.10, tip_y * 0.5, -0.20, tip_y, -0.24, tip_y - 0.02)
    ctx.curve_to(-0.05, tip_y * 0.8, 0.08, tip_y * 0.4, 0.12, 0.02)
    ctx.close_path()


def dolphin(ctx, layer, t):
    """Dolphin, side view."""
    if layer != "base":
        return
    ctx.new_sub_path()
    ctx.move_to(0.49, 0.035)                                    # beak tip
    ctx.curve_to(0.45, 0.01, 0.40, 0.005, 0.36, 0.0)            # top of beak
    ctx.curve_to(0.35, -0.08, 0.30, -0.14, 0.18, -0.15)         # rounded melon
    ctx.curve_to(0.02, -0.16, -0.20, -0.12, -0.36, -0.02)       # back -> tail stock
    ctx.line_to(-0.38, 0.01)
    ctx.curve_to(-0.22, 0.06, -0.05, 0.11, 0.12, 0.10)          # belly
    ctx.curve_to(0.28, 0.09, 0.40, 0.06, 0.49, 0.045)           # jaw
    ctx.close_path()
    ctx.new_sub_path()                                          # falcate dorsal fin
    ctx.move_to(0.08, -0.13)
    ctx.curve_to(0.02, -0.22, -0.04, -0.28, -0.12, -0.30)
    ctx.curve_to(-0.08, -0.24, -0.08, -0.17, -0.15, -0.09)
    ctx.close_path()
    ctx.new_sub_path()                                          # swept-back flipper
    ctx.move_to(0.16, 0.08)
    ctx.curve_to(0.12, 0.14, 0.06, 0.19, 0.0, 0.21)
    ctx.curve_to(0.04, 0.15, 0.06, 0.10, 0.06, 0.09)
    ctx.close_path()
    k = 0.03 * math.sin(t * 2.0)
    poly(ctx, [(-0.35, -0.02), (-0.47, -0.08 + k), (-0.50, -0.06 + k), (-0.45, 0.005 + k),
               (-0.50, 0.07 + k), (-0.47, 0.09 + k), (-0.35, 0.03)])  # tail flukes


def sea_slug(ctx, layer, t):
    """Leaf-shaped sea slug (like Elysia), side/top blend; detail = veins."""
    if layer == "base":
        ctx.new_sub_path()
        ctx.move_to(0.30, 0.0)
        ctx.curve_to(0.15, -0.30, -0.35, -0.25, -0.45, 0.02)
        ctx.curve_to(-0.35, 0.22, 0.15, 0.28, 0.30, 0.0)
        ctx.close_path()
        capsule(ctx, 0.20, 0.0, 0.36, -0.02, 0.06)                # head
        capsule(ctx, 0.36, -0.04, 0.44, -0.16, 0.018)             # rhinophores
        capsule(ctx, 0.36, -0.02, 0.47, -0.10, 0.018)
    else:
        capsule(ctx, 0.22, 0.0, -0.38, 0.02, 0.008)
        for k in range(5):
            x = 0.12 - k * 0.11
            capsule(ctx, x, 0.0, x - 0.08, -0.15 + 0.01 * k, 0.005)
            capsule(ctx, x, 0.01, x - 0.08, 0.16 - 0.01 * k, 0.005)


def sun(ctx, layer, t):
    """Sun disc with slowly turning rays."""
    if layer != "base":
        return
    circle(ctx, 0, 0, 0.27)
    for k in range(12):
        a = k * math.pi / 6 + t * 0.12
        ca, sa = math.cos(a), math.sin(a)
        c2, s2 = math.cos(a + 0.11), math.sin(a + 0.11)
        c3, s3 = math.cos(a - 0.11), math.sin(a - 0.11)
        poly(ctx, [(0.31 * c3, 0.31 * s3), (0.48 * ca, 0.48 * sa), (0.31 * c2, 0.31 * s2)])


SHAPES = {
    "person": person, "head": head, "bee": bee, "butterfly": butterfly, "beetle": beetle,
    "flower": flower, "leaf": leaf, "bird": bird, "dolphin": dolphin, "sea_slug": sea_slug,
    "sun": sun,
}
