"""Channel-wide look and sound. Episodes may pick a palette variant so videos
stay recognisably on-brand without looking identical."""

CHANNEL_NAME = "HYPOTHETICA"  # working name; change here once the channel name is final
W, H = 1920, 1080
FPS = 30


def set_format(fmt):
    """'landscape' (1920x1080) or 'vertical' (1080x1920, Shorts)."""
    global W, H
    W, H = (1080, 1920) if fmt == "vertical" else (1920, 1080)


FONT = "Inter"
FONT_HEAVY = "Inter Black"
FONT_DISPLAY = "Inter Display"
FONT_MONO = "JetBrains Mono"

# Base palette (RGB 0-1). Variants shift the background and accent so each
# episode has its own mood.
BASE = {
    "text": (0.95, 0.96, 1.00),
    "muted": (0.62, 0.68, 0.82),
    "cool": (0.33, 0.80, 1.00),
    "accent": (1.00, 0.68, 0.26),
    "danger": (1.00, 0.36, 0.30),
    "good": (0.45, 0.95, 0.62),
}

VARIANTS = {
    "deep_space": {"bg_top": (0.012, 0.016, 0.045), "bg_bottom": (0.035, 0.045, 0.11), "accent": (1.00, 0.68, 0.26)},
    "ember":      {"bg_top": (0.030, 0.012, 0.020), "bg_bottom": (0.10, 0.035, 0.04), "accent": (1.00, 0.55, 0.22)},
    "abyss":      {"bg_top": (0.005, 0.020, 0.035), "bg_bottom": (0.01, 0.07, 0.10), "accent": (0.35, 0.95, 0.85)},
    "verdant":    {"bg_top": (0.010, 0.030, 0.020), "bg_bottom": (0.03, 0.09, 0.06), "accent": (0.75, 0.95, 0.35)},
    "violet":     {"bg_top": (0.025, 0.012, 0.045), "bg_bottom": (0.07, 0.035, 0.12), "accent": (0.95, 0.55, 1.00)},
}


def palette(variant: str = "deep_space") -> dict:
    p = dict(BASE)
    p.update(VARIANTS.get(variant, VARIANTS["deep_space"]))
    return p


# Narrator: one consistent synthetic voice (Kokoro, Apache-2.0). Not a clone of any real person.
VOICE = "am_michael"
VOICE_SPEED = 1.0

# Words Kokoro tends to mispronounce -> Kokoro inline phoneme override syntax.
PRONUNCIATIONS = {
    "Schwarzschild": "[Schwarzschild](/ʃwˈɑɹtsʃɪld/)",
    "Hypothetica": "[Hypothetica](/hˌIpəθˈɛtɪkə/)",
}
