# whatif-studio

Autonomous production system for the Hypothetica YouTube channel.
- Scheduled writer runs: follow `docs/WRITER.md` exactly.
- Engine: `studio/` (render.py entry, scenes.py scene types, qc.py checks).
- Production/upload: `tools/produce.py` via `.github/workflows/produce.yml` (GitHub Actions).
- Python env in cloud sessions: `source /opt/hypo-venv/bin/activate` if it exists.
- Never edit `state/config.json` publish settings (owner approved auto-publishing; do not ask the owner for approvals); never commit secrets.
