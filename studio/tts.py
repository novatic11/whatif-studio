"""Narration with Kokoro-82M (Apache-2.0, runs on CPU). Synthesises sentence by
sentence so pauses are controlled, and returns word-level timestamps."""
import re

import numpy as np

from . import brand

SR = 24000
_PIPE = None


def _pipe():
    global _PIPE
    if _PIPE is None:
        from kokoro import KPipeline
        _PIPE = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    return _PIPE


def _apply_pronunciations(text):
    for word, repl in brand.PRONUNCIATIONS.items():
        text = re.sub(rf"\b{re.escape(word)}\b", repl, text)
    return text


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|(?<=\.\.\.)\s*|\n+", text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def pause_after(sentence):
    if sentence.endswith("..."):
        return 0.55
    if sentence.endswith("?"):
        return 0.42
    if sentence.endswith(":") or sentence.endswith("—"):
        return 0.25
    return 0.34


def synthesize(text, voice=None, speed=None):
    """Returns (audio float32 @24k, words [(word, start_s, end_s)])."""
    voice = voice or brand.VOICE
    speed = speed or brand.VOICE_SPEED
    pipe = _pipe()
    chunks, words, cursor = [], [], 0.0
    for sent in split_sentences(text):
        spoken = sent.replace("...", ",")
        for res in pipe(_apply_pronunciations(spoken), voice=voice, speed=speed):
            audio = res.audio.numpy() if hasattr(res.audio, "numpy") else np.asarray(res.audio)
            audio = _trim(audio)
            for tok in (res.tokens or []):
                if tok.start_ts is None or not re.search(r"\w", tok.text):
                    continue
                words.append((tok.text, cursor + tok.start_ts - _trim.lead, cursor + tok.end_ts - _trim.lead))
            chunks.append(audio)
            cursor += len(audio) / SR
        gap = np.zeros(int(pause_after(sent) * SR), dtype=np.float32)
        chunks.append(gap)
        cursor += len(gap) / SR
    audio = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(1, np.float32)
    peak = np.max(np.abs(audio)) or 1.0
    audio = audio / peak * 0.89  # -1 dBFS peak; loudness is normalised in the final mix
    return audio, words


def _trim(audio, thresh=0.004):
    """Trim leading/trailing near-silence (keeps a short natural tail)."""
    idx = np.where(np.abs(audio) > thresh)[0]
    if len(idx) == 0:
        _trim.lead = 0.0
        return audio
    start = max(0, idx[0] - int(0.02 * SR))
    end = min(len(audio), idx[-1] + int(0.08 * SR))
    _trim.lead = start / SR
    return audio[start:end]


_trim.lead = 0.0
