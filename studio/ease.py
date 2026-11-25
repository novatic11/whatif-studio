"""Easing and keyframe helpers. Any numeric scene parameter may be either a
constant or a list of keyframes: [[t, value], [t, value, "ease"], ...]."""
import math


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def in_out_cubic(t):
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def in_cubic(t):
    t = clamp(t)
    return t ** 3


def out_back(t, s=1.70158):
    t = clamp(t)
    return 1 + (s + 1) * (t - 1) ** 3 + s * (t - 1) ** 2


def out_expo(t):
    t = clamp(t)
    return 1.0 if t >= 1 else 1 - 2 ** (-10 * t)


def in_expo(t):
    t = clamp(t)
    return 0.0 if t <= 0 else 2 ** (10 * t - 10)


EASES = {
    "linear": clamp, "smooth": smooth, "in_out": in_out_cubic, "out": out_cubic,
    "in": in_cubic, "back": out_back, "out_expo": out_expo, "in_expo": in_expo,
}


def window(t, start, dur):
    """0..1 progress of t through [start, start+dur]."""
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / dur)


def kf(value, t, default_ease="in_out"):
    """Evaluate a constant or keyframe list at time t (seconds)."""
    if not isinstance(value, list) or not value or not isinstance(value[0], list):
        return value
    frames = value
    if t <= frames[0][0]:
        return frames[0][1]
    for i in range(1, len(frames)):
        t1 = frames[i][0]
        if t <= t1:
            t0, v0 = frames[i - 1][0], frames[i - 1][1]
            v1 = frames[i][1]
            e = EASES[frames[i][2] if len(frames[i]) > 2 else default_ease]
            u = e((t - t0) / (t1 - t0)) if t1 > t0 else 1.0
            if isinstance(v0, (list, tuple)):
                return [lerp(a, b, u) for a, b in zip(v0, v1)]
            return lerp(v0, v1, u)
    return frames[-1][1]


def pulse(t, period=2.0):
    return 0.5 + 0.5 * math.sin(2 * math.pi * t / period)
