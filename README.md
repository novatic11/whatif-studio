# whatif-studio

Autonomous studio for an animated "What if...?" YouTube channel (working name: HYPOTHETICA).

Everything is free and open source:
- **Narration:** Kokoro-82M TTS (Apache-2.0), CPU-only, word-level timestamps
- **Animation:** custom Python/Cairo/numpy engine (`studio/`): procedural planets, stars, black holes, diagrams, charts, kinetic type
- **Music & SFX:** synthesised procedurally (original, owned by the channel)
- **Mix:** FFmpeg ducking + two-pass loudness normalisation to -14 LUFS

## Render an episode
```bash
pip install -r requirements.txt
python -m studio.render episodes/0001-sun-black-hole/plan.json out/0001
```
Each episode is a `plan.json`: scenes with narration, a scene type, parameters
(keyframeable, and times can be anchored to spoken words like `"@collapses+0.5"`),
overlays, sound effects and transitions.
