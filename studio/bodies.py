"""Procedural celestial bodies rendered as single shaded objects (numpy
'shaders'), so every planet/star/black hole reads as one coherent form."""
import math
from functools import lru_cache

import numpy as np

TEX_W, TEX_H = 1024, 512


# ------------------------------------------------------------ noise on sphere
def _sphere_points(w, h):
    lon = (np.arange(w) + 0.5) / w * 2 * np.pi
    lat = np.pi / 2 - (np.arange(h) + 0.5) / h * np.pi
    lon, lat = np.meshgrid(lon, lat)
    return np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], -1)


def _fbm(p, seed, octaves=6, base_freq=1.6, waves=24):
    """Seamless fractal noise on the sphere from sums of random plane waves."""
    rng = np.random.default_rng(seed)
    out = np.zeros(p.shape[:-1])
    amp, freq, total = 1.0, base_freq, 0.0
    flat = p.reshape(-1, 3)
    for _ in range(octaves):
        d = rng.normal(size=(waves, 3))
        d /= np.linalg.norm(d, axis=1, keepdims=True)
        ph = rng.uniform(0, 2 * np.pi, waves)
        out += amp * np.sin(flat @ d.T * freq * 2 + ph).sum(1).reshape(out.shape) / math.sqrt(waves)
        total += amp
        amp *= 0.52
        freq *= 2.05
    return out / total


def _ramp(x, stops):
    """Map scalar field x to colours via [(pos, (r,g,b)), ...]."""
    xs = np.array([s[0] for s in stops])
    cs = np.array([s[1] for s in stops], dtype=float)
    return np.stack([np.interp(x, xs, cs[:, i]) for i in range(3)], -1)


@lru_cache(maxsize=16)
def planet_texture(kind="earth", seed=3):
    """Returns (rgb HxWx3, ocean_mask HxW, clouds HxW, night_lights HxW)."""
    p = _sphere_points(TEX_W, TEX_H)
    lat = np.abs(p[..., 1])
    zeros = np.zeros(p.shape[:-1])
    if kind == "earth":
        h = _fbm(p, seed, octaves=7, base_freq=1.3)
        h = (h - h.mean()) / h.std()
        land = h > 0.15
        ocean_col = _ramp(h, [(-2.5, (0.01, 0.06, 0.20)), (0.0, (0.03, 0.18, 0.42)), (0.15, (0.10, 0.42, 0.62))])
        moist = _fbm(p, seed + 11, octaves=4, base_freq=2.0)
        land_col = _ramp(h, [(0.15, (0.80, 0.74, 0.52)), (0.35, (0.22, 0.45, 0.18)), (1.3, (0.16, 0.33, 0.13)),
                             (2.0, (0.42, 0.36, 0.28)), (2.6, (0.85, 0.85, 0.85))])
        desert = np.clip((0.35 - np.abs(p[..., 1] - 0.0) ) * 3 - moist * 4, 0, 1)[..., None] * (1 - lat[..., None])
        land_col = land_col * (1 - desert * 0.6) + np.array([0.78, 0.62, 0.38]) * desert * 0.6
        rgb = np.where(land[..., None], land_col, ocean_col)
        ice = np.clip((lat - 0.80) * 12 + _fbm(p, seed + 5, 3, 3.0) * 1.5, 0, 1)[..., None]
        rgb = rgb * (1 - ice) + np.array([0.93, 0.96, 1.0]) * ice
        c = _fbm(p, seed + 21, octaves=6, base_freq=4.5, waves=32)
        band = 0.5 + 0.5 * np.cos(np.arcsin(p[..., 1]) * 6)  # cloud belts
        clouds = np.clip((c * 1.4 + band * 0.25 - 0.32) * 2.4, 0, 0.85)
        lights = np.where(land & (lat < 0.75), np.clip(_fbm(p, seed + 31, 5, 6.0) * 3 - 0.6, 0, 1), 0.0)
        return rgb, (~land).astype(float), clouds, lights
    if kind == "rocky":
        h = _fbm(p, seed, octaves=7, base_freq=1.8)
        h = (h - h.mean()) / h.std()
        rgb = _ramp(h, [(-2.5, (0.35, 0.16, 0.08)), (0, (0.66, 0.34, 0.18)), (1.5, (0.82, 0.55, 0.36)), (2.5, (0.9, 0.85, 0.8))])
        return rgb, zeros, zeros, zeros
    if kind == "moon":
        h = _fbm(p, seed, octaves=7, base_freq=2.0)
        h = (h - h.mean()) / h.std()
        rgb = _ramp(h, [(-2.5, (0.30, 0.30, 0.32)), (0, (0.55, 0.55, 0.56)), (2.5, (0.82, 0.82, 0.82))])
        return rgb, zeros, zeros, zeros
    if kind == "gas":
        turb = _fbm(p, seed, octaves=5, base_freq=2.5)
        band = np.sin(p[..., 1] * 18 + turb * 2.2)
        rgb = _ramp(band, [(-1, (0.62, 0.45, 0.30)), (0, (0.86, 0.76, 0.60)), (1, (0.95, 0.90, 0.80))])
        return rgb, zeros, zeros, zeros
    if kind == "venus":  # thick sulfuric cloud deck: soft, creamy, swirled bands
        turb = _fbm(p, seed, octaves=6, base_freq=2.2)
        band = np.sin(p[..., 1] * 7 + turb * 3.2 + np.abs(p[..., 1]) * 4)
        rgb = _ramp(band + turb * 0.6, [(-1.6, (0.66, 0.52, 0.30)), (-0.4, (0.84, 0.70, 0.44)),
                                        (0.6, (0.93, 0.84, 0.60)), (1.6, (0.98, 0.94, 0.80))])
        return rgb, zeros, zeros, zeros
    if kind in ("star", "red_dwarf"):
        g = _fbm(p, seed, octaves=5, base_freq=14.0, waves=32)
        g2 = _fbm(p, seed + 1, octaves=3, base_freq=3.0)
        v = 0.9 + 0.07 * g + 0.05 * g2
        return np.stack([v, v, v], -1), zeros, zeros, zeros
    raise ValueError(kind)


# ------------------------------------------------------------ sphere shader
def render_sphere(kind, radius, rot=0.0, light_dir=(-0.8, -0.2, 0.55), light=1.0, seed=3,
                  atmosphere=(0.35, 0.65, 1.0), atmo_strength=0.9, cloud_rot=0.0, tilt=0.35,
                  emissive=False, frozen=0.0):
    """Render a sphere of `radius` px. Returns (rgb, alpha) arrays incl. halo."""
    tex, ocean, clouds, lights = planet_texture(kind, seed)
    pad = 1.10 if atmo_strength > 0 and not emissive else 1.0
    R = int(math.ceil(radius * pad)) + 2
    ys, xs = np.mgrid[-R:R, -R:R].astype(float) + 0.5
    nx, ny = xs / radius, ys / radius
    d2 = nx * nx + ny * ny
    d = np.sqrt(d2)
    inside = d2 < 1.0
    nz = np.sqrt(np.clip(1 - d2, 0, 1))
    # axial tilt: rotate the view normal around z
    ct, st = math.cos(tilt), math.sin(tilt)
    tx, ty = nx * ct - ny * st, nx * st + ny * ct
    lat = np.arcsin(np.clip(-ty, -1, 1))
    lon = np.arctan2(tx, nz)

    def sample(arr, r):
        u = ((((lon + r) / (2 * np.pi)) % 1.0) * TEX_W).astype(int) % TEX_W
        v = np.clip(((0.5 - lat / np.pi) * TEX_H).astype(int), 0, TEX_H - 1)
        return arr[v, u]

    col = sample(tex, rot)
    edge_alpha = np.clip((1 - d) * radius + 0.5, 0, 1)
    if emissive:
        limb = 0.35 + 0.65 * np.power(nz, 0.5)
        v = col[..., 0] * limb * light
        if kind == "red_dwarf":  # cool M-dwarf: deep red to orange, never white-hot
            rgb = _ramp(v, [(0.0, (0.20, 0.01, 0.0)), (0.45, (0.70, 0.10, 0.03)), (0.75, (0.92, 0.25, 0.08)),
                            (0.95, (1.0, 0.45, 0.20)), (1.3, (1.0, 0.65, 0.40))])
            return rgb, edge_alpha
        rgb = _ramp(v, [(0.0, (0.35, 0.05, 0.0)), (0.45, (0.95, 0.35, 0.05)), (0.7, (1.0, 0.62, 0.18)),
                        (0.88, (1.0, 0.86, 0.52)), (1.05, (1.0, 0.97, 0.88)), (1.6, (1, 1, 1))])
        return rgb, edge_alpha
    L = np.array(light_dir, float)
    L /= np.linalg.norm(L)
    ndl = nx * L[0] + ny * L[1] + nz * L[2]
    shade = np.clip((ndl + 0.12) / 0.55, 0, 1) ** 1.2 * light
    if frozen > 0:  # oceans freezing over
        ice_col = np.array([0.86, 0.92, 0.98])
        oc = sample(ocean, rot)[..., None] * frozen
        col = col * (1 - oc) + ice_col * oc
    if clouds.any():
        cl = sample(clouds, rot + cloud_rot)[..., None]
        col = col * (1 - cl) + np.array([0.97, 0.98, 1.0]) * cl
    else:
        cl = 0
    ambient = 0.025
    rgb = col * (ambient + (1 - ambient) * shade[..., None])
    # specular glint on oceans
    if ocean.any():
        H = L + np.array([0, 0, 1.0])
        H /= np.linalg.norm(H)
        spec = np.clip(nx * H[0] + ny * H[1] + nz * H[2], 0, 1) ** 40
        rgb += (spec * sample(ocean, rot) * light * 0.5)[..., None] * (1 - cl) * (1 - frozen)
    if lights.any():
        night = np.clip(1 - shade * 3, 0, 1)
        lit = sample(lights, rot) * night * (1 - (cl if np.ndim(cl) == 0 else cl[..., 0]))
        rgb += lit[..., None] * np.array([1.0, 0.75, 0.40]) * 0.9
    alpha = edge_alpha
    if atmo_strength > 0:
        atm = np.array(atmosphere)
        lit_side = np.clip((ndl + 0.3) / 0.8, 0, 1) * light
        rim = np.power(1 - nz, 2.5) * inside
        rgb = rgb * (1 - rim[..., None] * 0.6 * lit_side[..., None]) + atm * (rim * lit_side * atmo_strength)[..., None]
        halo = np.exp(-np.clip(d - 1, 0, None) / 0.025) * (d >= 1)
        # halo lit by the light direction projected on screen
        hl = np.clip((nx / np.maximum(d, 1e-6) * L[0] + ny / np.maximum(d, 1e-6) * L[1]) * 0.8 + 0.45, 0, 1) * light
        halo_a = halo * hl * atmo_strength * 0.85
        rgb = np.where(inside[..., None], rgb, atm)
        alpha = np.maximum(alpha, halo_a)
    return np.clip(rgb, 0, 1), alpha


# ------------------------------------------------------------ black hole shader
def _heat(x):
    return _ramp(np.clip(x, 0, 1.5), [(0, (0.0, 0.0, 0.0)), (0.15, (0.45, 0.06, 0.02)), (0.45, (0.95, 0.36, 0.08)),
                                      (0.8, (1.0, 0.72, 0.35)), (1.2, (1.0, 0.95, 0.85)), (1.5, (1, 1, 1))])


def render_black_hole(rs, t=0.0, tilt=0.16, disk=1.0, brightness=1.0, spin=1.0):
    """Schwarzschild-style black hole with lensed accretion disk.
    rs: shadow radius in px. disk: 0..1 disk presence (for spin-up)."""
    Wd, Hd = int(rs * 6.2), int(rs * 3.6)
    ys, xs = np.mgrid[-Hd:Hd, -Wd:Wd].astype(float) + 0.5
    x, y = xs / rs, ys / rs
    r = np.sqrt(x * x + y * y)
    theta = np.arctan2(y, x)
    shadow = np.clip((1.0 - r) * rs + 0.5, 0, 1)

    # thin disk seen nearly edge-on
    e = tilt
    yd = y / e
    rd = np.sqrt(x * x + yd * yd)
    ang = np.arctan2(yd, x)
    rin, rout = 1.9, 5.4
    radial = np.clip((rd - rin) * 3, 0, 1) * np.clip((rout - rd) * 0.9, 0, 1) * np.power(rin / np.maximum(rd, rin), 1.6)
    swirl = 0.84 + 0.16 * np.sin(9 * ang + 16 * np.log(np.maximum(rd, 0.1)) - t * 3.0 * spin) \
        * (0.6 + 0.4 * np.sin(23 * ang - 30 * np.log(np.maximum(rd, 0.1)) + t * 1.7 * spin))
    doppler = 1.0 + 0.55 * np.cos(ang - np.pi)  # approaching side (left) is brighter
    disk_I = radial * swirl * doppler * disk
    front = (y > 0)
    disk_front = disk_I * front
    disk_back = disk_I * (~front) * (1 - shadow)

    # lensed image of the far side of the disk wrapping over and under the shadow
    lens_top = np.exp(-((r - 1.32) / 0.22) ** 2) * np.clip(-np.sin(theta) * 1.2 + 0.25, 0, 1)
    lens_bot = np.exp(-((r - 1.12) / 0.10) ** 2) * np.clip(np.sin(theta) * 1.2 + 0.1, 0, 1) * 0.55
    lens = (lens_top + lens_bot) * (0.8 + 0.35 * np.cos(theta - np.pi) * 0.6) * disk
    lens *= 0.85 + 0.15 * np.sin(14 * theta - t * 2.0 * spin)
    ring = np.exp(-((r - 1.035) / 0.035) ** 2) * (0.55 + 0.45 * disk)  # photon ring
    halo = np.exp(-np.clip(r - 1, 0, None) / 1.6) * 0.10 * (0.3 + 0.7 * disk)

    I_back = (disk_back + lens * (1 - shadow) + ring + halo * (1 - shadow)) * brightness
    I_front = disk_front * brightness
    col_back = _heat(I_back * 1.05)
    col_front = _heat(I_front * 1.05)
    a_back = np.clip(I_back * 1.6, 0, 1)
    a_front = np.clip(I_front * 1.6, 0, 1)
    # composite: back glow -> black shadow -> front disk
    C = col_back * a_back[..., None]
    A = a_back
    C = C * (1 - shadow[..., None])
    A = shadow + A * (1 - shadow)
    C = col_front * a_front[..., None] + C * (1 - a_front[..., None])
    A = a_front + A * (1 - a_front)
    rgb = C / np.maximum(A, 1e-4)[..., None]
    return np.clip(rgb, 0, 1), np.clip(A, 0, 1)
