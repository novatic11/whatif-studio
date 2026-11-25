"""Original procedurally generated score and sound effects (we own all rights),
plus the final mix: ducking under narration and two-pass loudness
normalisation to YouTube's -14 LUFS."""
import json
import re
import subprocess

import numpy as np
from scipy import signal

SR = 48000

NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name):
    m = re.match(r"([A-G]#?)(-?\d)", name)
    n, octv = NOTE[m.group(1)], int(m.group(2))
    return 440.0 * 2 ** ((n - 9) / 12 + (octv - 4))


MOODS = {
    # chord progressions (one chord per bar)
    "awe":     [["D3", "A3", "E4", "F#4"], ["B2", "F#3", "D4", "A4"], ["G2", "D3", "B3", "F#4"], ["A2", "E3", "C#4", "E4"]],
    "mystery": [["D3", "A3", "C4", "F4"], ["A#2", "F3", "A3", "D4"], ["G2", "D3", "A#3", "F4"], ["A2", "E3", "G3", "C#4"]],
    "tense":   [["C3", "G3", "D#4", "G4"], ["C3", "G3", "D4", "G#4"], ["G#2", "D#3", "C4", "G4"], ["G2", "D3", "B3", "F4"]],
    "warm":    [["F2", "C3", "A3", "E4"], ["D3", "A3", "C4", "F4"], ["A#2", "F3", "D4", "A4"], ["C3", "G3", "E4", "G4"]],
}


def _osc(freq, n, sr=SR, harmonics=6, detune=0.0, phase=0.0):
    t = np.arange(n) / sr
    out = np.zeros(n, np.float32)
    f = freq * (1 + detune)
    for h in range(1, harmonics + 1):
        if f * h > sr / 2.2:
            break
        out += (np.sin(2 * np.pi * f * h * t + phase * h) / h ** 1.6).astype(np.float32)
    return out


def _reverb_ir(seconds=3.2, seed=0):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = rng.normal(size=(2, n)) * np.exp(-t / (seconds / 6.5))
    ir[:, : int(0.012 * SR)] *= np.linspace(0, 1, int(0.012 * SR))
    b, a = signal.butter(2, 5000 / (SR / 2))
    ir = signal.lfilter(b, a, ir, axis=1)
    return (ir / np.sqrt((ir ** 2).sum(axis=1, keepdims=True))).astype(np.float32)


def music(duration, mood="awe", seed=1, bar=8.0, intensity=None):
    """Ambient score: evolving pads, sub drone, sparse plucked motif, reverb.
    intensity: optional function t->0..1 controlling density/brightness."""
    rng = np.random.default_rng(seed)
    n = int((duration + 4) * SR)
    pad = np.zeros(n, np.float32)
    plucks = np.zeros((2, n), np.float32)
    prog = MOODS.get(mood, MOODS["awe"])
    rot = int(rng.integers(0, len(prog)))
    prog = prog[rot:] + prog[:rot]
    blen = int(bar * SR)
    fade = int(2.5 * SR)
    nb = int(np.ceil(n / blen)) + 1
    for b in range(nb):
        chord = prog[b % len(prog)]
        s = max(0, b * blen - fade)
        e = min(n, (b + 1) * blen + fade)
        if s >= n:
            break
        L = e - s
        env = np.ones(L, np.float32)
        env[:fade] = np.linspace(0, 1, fade) ** 1.5 if L > fade else env[:fade]
        env[-fade:] = np.minimum(env[-fade:], np.linspace(1, 0, fade) ** 1.5)
        seg = np.zeros(L, np.float32)
        for note in chord:
            f = hz(note)
            for d in (-0.004, 0.0, 0.0045):
                seg += _osc(f, L, detune=d, phase=rng.uniform(0, 6.28), harmonics=5) * 0.06
        root = hz(chord[0]) / 2
        seg += _osc(root, L, harmonics=2) * 0.10
        pad[s:e] += seg * env
        # sparse motif: a few chord tones an octave up
        for _ in range(int(rng.integers(2, 5))):
            when = b * blen + int(rng.uniform(0, bar - 1) * SR)
            if when >= n - SR:
                continue
            if intensity is not None and rng.uniform() > 0.25 + 0.75 * intensity(when / SR):
                continue
            f = hz(chord[int(rng.integers(1, len(chord)))]) * 2
            ln = int(2.5 * SR)
            ln = min(ln, n - when)
            tt = np.arange(ln) / SR
            note = (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt)) * np.exp(-tt * 2.2) * 0.09
            pan = rng.uniform(0.25, 0.75)
            plucks[0, when:when + ln] += note * (1 - pan)
            plucks[1, when:when + ln] += note * pan
    # gentle low-pass that opens with intensity
    b_, a_ = signal.butter(2, 1800 / (SR / 2))
    pad = signal.lfilter(b_, a_, pad).astype(np.float32)
    lfo = 1 + 0.08 * np.sin(2 * np.pi * np.arange(n) / SR / 11.0)
    st = np.stack([pad * lfo, pad * (2 - lfo)]) * 0.9 + plucks
    ir = _reverb_ir(seed=seed)
    wet = np.stack([signal.fftconvolve(st[c], ir[c])[:n] for c in range(2)])
    out = st * 0.55 + wet * 0.45
    if intensity is not None:
        g = np.array([0.55 + 0.45 * intensity(i / 10) for i in range(int(n / SR * 10) + 1)])
        out *= np.interp(np.arange(n) / SR, np.arange(len(g)) / 10, g)
    out = out[:, : int(duration * SR)]
    fl = int(1.5 * SR)
    out[:, :fl] *= np.linspace(0, 1, fl)
    out[:, -fl * 2:] *= np.linspace(1, 0, fl * 2)
    return (out / (np.max(np.abs(out)) + 1e-6) * 0.7).astype(np.float32)


# ------------------------------------------------------------ sound effects
def _noise(n, seed):
    return np.random.default_rng(seed).normal(size=n).astype(np.float32)


def sfx(name, seed=0):
    t_ = lambda d: np.arange(int(d * SR)) / SR
    if name == "impact":
        t = t_(3.0)
        f = 30 + 45 * np.exp(-t * 2.5)
        body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.4)
        b, a = signal.butter(2, 400 / (SR / 2))
        crack = signal.lfilter(b, a, _noise(len(t), seed)) * np.exp(-t * 6) * 0.9
        x = body + crack
    elif name == "whoosh":
        t = t_(1.2)
        x = np.zeros(len(t))
        nz = _noise(len(t), seed)
        for i, fc in enumerate([500, 900, 1600, 2800]):
            b, a = signal.butter(2, [fc * 0.7 / (SR / 2), fc * 1.3 / (SR / 2)], btype="band")
            band = signal.lfilter(b, a, nz)
            center = 0.35 + i * 0.12
            x += band * np.exp(-((t - center) / 0.22) ** 2)
        x *= 1.4
    elif name == "riser":
        t = t_(2.5)
        b, a = signal.butter(2, 2000 / (SR / 2), btype="high")
        x = signal.lfilter(b, a, _noise(len(t), seed)) * (t / t[-1]) ** 2 * 0.5
        x += np.sin(2 * np.pi * np.cumsum(200 + 500 * (t / t[-1]) ** 2) / SR) * (t / t[-1]) ** 2 * 0.3
    elif name == "tick":
        t = t_(0.06)
        x = np.sin(2 * np.pi * 2600 * t) * np.exp(-t * 120) * 0.6
    elif name == "shimmer":
        t = t_(3.0)
        x = sum(np.sin(2 * np.pi * f * t) for f in (1760, 2217, 2637, 3520)) * np.exp(-t * 1.2) * 0.12
        x *= 0.7 + 0.3 * np.sin(2 * np.pi * 7 * t)
    elif name == "drone_drop":
        t = t_(4.0)
        x = np.sin(2 * np.pi * np.cumsum(90 * np.exp(-t * 0.5)) / SR) * np.minimum(t * 3, 1) * np.exp(-t * 0.7) * 0.8
    else:
        raise ValueError(name)
    x = x.astype(np.float32)
    return x / (np.max(np.abs(x)) + 1e-6) * 0.8


# ------------------------------------------------------------ mix
def write_wav(path, data, sr):
    import soundfile as sf
    sf.write(path, data.T if data.ndim == 2 else data, sr, subtype="PCM_16" if data.ndim == 1 else "FLOAT")


def master(voice_wav, music_wav, sfx_wav, out_path, target_lufs=-14.0):
    """Duck music under voice, mix, two-pass loudnorm."""
    graph = ("[0:a]aresample=48000,pan=stereo|c0=c0|c1=c0,asplit=2[v][vsc];"
             "[1:a]volume=0.32[m];"
             "[m][vsc]sidechaincompress=threshold=0.02:ratio=5:attack=60:release=700:makeup=1[md];"
             "[2:a]volume=0.75[fx];"
             "[v][md][fx]amix=inputs=3:normalize=0:duration=longest[mix]")
    base = ["ffmpeg", "-y", "-hide_banner", "-i", voice_wav, "-i", music_wav, "-i", sfx_wav]
    p1 = subprocess.run(base + ["-filter_complex", graph + ";[mix]loudnorm=I=%s:TP=-1.5:LRA=11:print_format=json[o]" % target_lufs,
                                "-map", "[o]", "-f", "null", "-"], capture_output=True, text=True)
    m = json.loads(p1.stderr[p1.stderr.rindex("{"):p1.stderr.rindex("}") + 1])
    ln = ("loudnorm=I={t}:TP=-1.5:LRA=11:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:"
          "measured_thresh={input_thresh}:offset={target_offset}:linear=true").format(t=target_lufs, **m)
    subprocess.run(base + ["-filter_complex", graph + ";[mix]" + ln + ",aresample=48000[o]", "-map", "[o]",
                           "-c:a", "pcm_s16le", out_path], check=True, capture_output=True)
    return m
