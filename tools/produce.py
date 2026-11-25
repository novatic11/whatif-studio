"""Production run (GitHub Actions): pick the next ready episode package,
render long-form + Shorts, run QC (repairing what can be repaired), make
thumbnails and metadata, upload, and record everything in state/.

  python tools/produce.py            # full run
  python tools/produce.py --no-upload  # render + QC only
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import traceback
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from studio import metadata, qc, render, thumbnail, youtube  # noqa: E402

STATE = os.path.join(ROOT, "state")
OUT = os.path.join(ROOT, "out")
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def load(name, default):
    p = os.path.join(STATE, name)
    return json.load(open(p)) if os.path.exists(p) else default


def save(name, data):
    os.makedirs(STATE, exist_ok=True)
    json.dump(data, open(os.path.join(STATE, name), "w"), indent=1, ensure_ascii=False)


def log_event(msg, **kw):
    ev = load("events.json", [])
    ev.append({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "msg": msg, **kw})
    save("events.json", ev[-300:])
    print(f"[event] {msg} {kw if kw else ''}", flush=True)


def plan_hash(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


def next_slot(cfg, kind, ledger):
    tz = ZoneInfo(cfg["timezone"])
    now = dt.datetime.now(tz) + dt.timedelta(hours=3)
    taken = {v.get("publish_at") for v in ledger.values() if v.get("publish_at")}
    slots = cfg["long_slots"] if kind == "long" else cfg["short_slots"]
    for d in range(0, 28):
        day = (now + dt.timedelta(days=d)).date()
        for wd, hm in slots:
            if DAYS[day.weekday()] != wd:
                continue
            h, m = map(int, hm.split(":"))
            t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            iso = t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if t > now and iso not in taken:
                return iso
    return None


def pending_items(cfg, ledger, failures):
    """Ready items not yet uploaded. Shorts carry their own "status": "ready";
    long-form plans only count when long_form_enabled is true."""
    items = []
    if cfg.get("long_form_enabled", False):
        for p in sorted(glob.glob(os.path.join(ROOT, "episodes", "*", "plan.json"))):
            items.append(("long", p))
    for p in sorted(glob.glob(os.path.join(ROOT, "episodes", "*", "shorts", "*.json"))):
        items.append(("short", p))
    out = []
    for kind, path in items:
        plan = json.load(open(path))
        if plan.get("status") != "ready":
            continue
        key = os.path.relpath(path, ROOT)
        f = failures.get(key)
        if key in ledger or (f and f["hash"] == plan_hash(path)):
            continue
        out.append((kind, path))
    return out


def repair_audio(video):
    """Re-normalise loudness/peaks in place (fixes loudness/clipping failures)."""
    tmp = video + ".fix.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video, "-c:v", "copy",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", tmp], check=True)
    os.replace(tmp, video)


def produce_item(kind, path, cfg, ledger, failures, token, long_ids, upload):
    key = os.path.relpath(path, ROOT)
    plan = json.load(open(path))
    fmt = plan.get("format", "landscape")
    slug = plan.get("slug") or os.path.splitext(os.path.basename(path))[0]
    out = os.path.join(OUT, slug)
    shutil.rmtree(out, ignore_errors=True)
    issues = qc.check_plan(plan, fmt)
    if issues:
        failures[key] = {"hash": plan_hash(path), "stage": "plan", "issues": issues}
        log_event("QC failed (plan)", item=key, issues=issues)
        return None
    final = render.render_episode(path, out)
    timeline = json.load(open(os.path.join(out, "timeline.json")))
    srt = os.path.join(out, "captions.srt")
    media = qc.check_media(final, fmt, srt)
    if not media["loudness"]["ok"] or not media["clipping"]["ok"]:
        repair_audio(final)
        media = qc.check_media(final, fmt, srt)
    if kind == "long":
        media["similarity"] = qc.similarity(path)
    meta = metadata.build(plan, timeline, kind, long_ids.get(os.path.dirname(os.path.dirname(path))) if kind == "short" else None)
    mi = qc.check_metadata(meta, fmt)
    media["metadata"] = {"ok": not mi, "value": mi}
    report = qc.summarize(media)
    json.dump(report, open(os.path.join(out, "qc_report.json"), "w"), indent=1)
    if not report["passed"]:
        failures[key] = {"hash": plan_hash(path), "stage": "media", "failed": report["failed"],
                         "details": {k: report["checks"][k] for k in report["failed"]}}
        log_event("QC failed (media)", item=key, failed=report["failed"])
        return None
    thumb = None
    if kind == "long" and plan.get("thumbnail"):
        thumb, _ = thumbnail.make(plan, os.path.join(out, "thumbs"))
    if not upload:
        log_event("Rendered and passed QC (upload disabled)", item=key)
        return {"dry_run": True}
    # duplicate guard: same title already on channel?
    existing = youtube.recent_upload_titles(token)
    if meta["title"] in existing:
        vid = existing[meta["title"]]
        log_event("Already on channel; recording instead of re-uploading", item=key, video_id=vid)
        ledger[key] = {"video_id": vid, "title": meta["title"], "kind": kind, "recovered": True}
        return ledger[key]
    mode = cfg["publish_mode"]
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "embeddable": True,
              "license": "youtube", "containsSyntheticMedia": bool(cfg.get("contains_synthetic_media", False))}
    publish_at = None
    if mode == "scheduled_public":
        publish_at = next_slot(cfg, kind, ledger)
        if publish_at:
            status["publishAt"] = publish_at
    snippet = {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
               "categoryId": cfg.get("category_id", "28"), "defaultLanguage": "en", "defaultAudioLanguage": "en"}
    ledger[key] = {"title": meta["title"], "kind": kind, "status": "uploading"}
    save("uploads.json", ledger)
    res = youtube.upload_video(final, snippet, status, token)
    vid = res["id"]
    entry = {"video_id": vid, "title": meta["title"], "kind": kind, "status": "uploaded", "privacy": "private",
             "publish_at": publish_at, "mode": mode, "duration": report["checks"]["duration"]["value"],
             "uploaded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "plan_hash": plan_hash(path)}
    ledger[key] = entry
    save("uploads.json", ledger)
    warnings = []
    if thumb:
        try:
            youtube.set_thumbnail(vid, thumb, token)
        except Exception as e:  # unverified channels cannot set custom thumbnails
            warnings.append(f"thumbnail: {str(e)[:160]}")
    if kind == "long":
        try:
            youtube.insert_captions(vid, srt, token)
        except Exception as e:
            warnings.append(f"captions: {str(e)[:160]}")
    if meta.get("playlist"):
        try:
            cache = load("playlists.json", {})
            pid = youtube.ensure_playlist(meta["playlist"], "Hypothetica thought experiments.", token, cache)
            save("playlists.json", cache)
            youtube.add_to_playlist(pid, vid, token)
        except Exception as e:
            warnings.append(f"playlist: {str(e)[:160]}")
    entry["warnings"] = warnings
    save("uploads.json", ledger)
    log_event("Uploaded", item=key, video_id=vid, publish_at=publish_at, mode=mode, warnings=warnings)
    failures.pop(key, None)
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    args = ap.parse_args()
    cfg = load("config.json", {})
    health = load("health.json", {})
    ledger = load("uploads.json", {})
    failures = load("qc_failures.json", {})
    upload = not args.no_upload and cfg.get("uploads_enabled", True)
    token = None
    if upload:
        try:
            token = youtube.access_token()
            health["auth"] = {"ok": True, "checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        except youtube.AuthError as e:
            health["auth"] = {"ok": False, "error": str(e)[:200], "checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
            save("health.json", health)
            log_event("PAUSED: YouTube credentials rejected; re-run setup step 5 to refresh the token")
            sys.exit(2)
    items = pending_items(cfg, ledger, failures)[: cfg.get("max_items_per_run", 4)]
    if not items:
        log_event("Nothing ready to produce")
        save("health.json", health)
        return
    long_ids = {os.path.join(ROOT, os.path.dirname(k)): v["video_id"] for k, v in ledger.items()
                if v.get("kind") == "long" and v.get("video_id")}
    for kind, path in items:
        ep_dir = os.path.dirname(os.path.dirname(path)) if kind == "short" else os.path.dirname(path)
        if kind == "short" and upload and cfg.get("long_form_enabled", False) \
                and os.path.exists(os.path.join(ep_dir, "plan.json")) and ep_dir not in long_ids:
            log_event("Short waits for its long-form upload", item=os.path.relpath(path, ROOT))
            continue
        try:
            r = produce_item(kind, path, cfg, ledger, failures, token, long_ids, upload)
            if r and kind == "long" and r.get("video_id"):
                long_ids[os.path.dirname(path)] = r["video_id"]
        except youtube.QuotaError as e:
            log_event("PAUSED: YouTube quota reached; will resume next run", error=str(e)[:200])
            break
        except youtube.AuthError as e:
            health["auth"] = {"ok": False, "error": str(e)[:200]}
            log_event("PAUSED: credentials rejected during upload")
            break
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            log_event("Error producing item; will retry next run", item=os.path.relpath(path, ROOT), error=str(e)[:300])
        finally:
            save("uploads.json", ledger)
            save("qc_failures.json", failures)
            shutil.rmtree(os.path.join(OUT, "_tmp"), ignore_errors=True)
    health["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    save("health.json", health)


if __name__ == "__main__":
    main()
