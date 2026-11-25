"""Daily analytics pull (GitHub Actions). Stores per-video metrics history in
state/analytics.json and derives cautious lessons in state/insights.json for
the writer. Insights only appear once there is enough data to mean something."""
import datetime as dt
import json
import os
import statistics
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from studio import youtube  # noqa: E402

STATE = os.path.join(ROOT, "state")
YTA = "https://youtubeanalytics.googleapis.com/v2/reports"
MIN_SAMPLE = 8


def load(n, d):
    p = os.path.join(STATE, n)
    return json.load(open(p)) if os.path.exists(p) else d


def report(token, **params):
    q = {"ids": "channel==MINE", **params}
    return youtube._request("GET", f"{YTA}?{urllib.parse.urlencode(q)}", token)


def main():
    ledger = load("uploads.json", {})
    an = load("analytics.json", {"videos": {}, "channel": []})
    today = dt.date.today()
    try:
        token = youtube.access_token()
    except youtube.AuthError as e:
        print("auth failed:", e)
        sys.exit(2)
    ids = {v["video_id"]: k for k, v in ledger.items() if v.get("video_id")}
    if ids:
        for chunk in [list(ids)[i:i + 50] for i in range(0, len(ids), 50)]:
            res = youtube.get("videos", {"part": "statistics,status,snippet", "id": ",".join(chunk)}, token)
            for it in res.get("items", []):
                v = an["videos"].setdefault(it["id"], {"item": ids[it["id"]], "history": []})
                st = it.get("statistics", {})
                v.update(title=it["snippet"]["title"], privacy=it["status"]["privacyStatus"],
                         published=it["snippet"].get("publishedAt"),
                         views=int(st.get("viewCount", 0)), likes=int(st.get("likeCount", 0)),
                         comments=int(st.get("commentCount", 0)))
        start = (today - dt.timedelta(days=90)).isoformat()
        try:
            r = report(token, startDate=start, endDate=today.isoformat(), dimensions="video",
                       metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,likes,shares",
                       filters="video==" + ",".join(list(ids)[:200]), sort="-views", maxResults=200)
            cols = [c["name"] for c in r.get("columnHeaders", [])]
            for row in r.get("rows", []):
                d = dict(zip(cols, row))
                v = an["videos"].setdefault(d["video"], {"item": ids.get(d["video"]), "history": []})
                v["analytics"] = d
                v["history"] = (v["history"] + [{"date": today.isoformat(), **{k: d[k] for k in cols if k != "video"}}])[-120:]
        except Exception as e:  # analytics can lag 2-3 days for new channels
            print("analytics report skipped:", str(e)[:200])
    try:
        r = report(token, startDate=(today - dt.timedelta(days=28)).isoformat(), endDate=today.isoformat(),
                   dimensions="insightTrafficSourceType", metrics="views,estimatedMinutesWatched")
        an["traffic_sources_28d"] = {row[0]: {"views": row[1], "minutes": row[2]} for row in r.get("rows", [])}
        r = report(token, startDate=(today - dt.timedelta(days=28)).isoformat(), endDate=today.isoformat(),
                   dimensions="day", metrics="views,subscribersGained,subscribersLost,estimatedMinutesWatched")
        an["channel_daily_28d"] = r.get("rows", [])
    except Exception as e:
        print("channel report skipped:", str(e)[:200])
    an["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    json.dump(an, open(os.path.join(STATE, "analytics.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(insights(an, ledger), open(os.path.join(STATE, "insights.json"), "w"), indent=1, ensure_ascii=False)


def insights(an, ledger):
    """Cautious, sample-size-aware lessons. Retention (avg % viewed) is weighted
    above raw views so the channel optimises for satisfied viewers, not clicks."""
    vids = [v for v in an["videos"].values() if v.get("analytics") and v.get("privacy") == "public"]
    out = {"sample_size": len(vids), "updated": an.get("updated"), "lessons": []}
    if len(vids) < MIN_SAMPLE:
        out["lessons"].append(f"Only {len(vids)} public videos with analytics; need {MIN_SAMPLE}+ before drawing conclusions. Keep variety.")
        return out
    pct = [v["analytics"]["averageViewPercentage"] for v in vids]
    med = statistics.median(pct)
    ranked = sorted(vids, key=lambda v: (v["analytics"]["averageViewPercentage"] / med) * 0.6
                    + (v["analytics"]["views"] / max(1, statistics.median([x["analytics"]["views"] for x in vids]))) * 0.4,
                    reverse=True)
    out["median_avg_view_pct"] = round(med, 1)
    out["top"] = [{"title": v["title"], "avg_view_pct": v["analytics"]["averageViewPercentage"], "views": v["analytics"]["views"]} for v in ranked[:5]]
    out["bottom"] = [{"title": v["title"], "avg_view_pct": v["analytics"]["averageViewPercentage"], "views": v["analytics"]["views"]} for v in ranked[-3:]]
    themes = {}
    for v in vids:
        pl = ledger.get(v.get("item") or "", {}).get("playlist") or "unknown"
        themes.setdefault(pl, []).append(v["analytics"]["averageViewPercentage"])
    out["theme_avg_view_pct"] = {k: round(statistics.mean(x), 1) for k, x in themes.items() if len(x) >= 3}
    out["lessons"].append("Study what the top videos' hooks and first 3 seconds do differently from the bottom ones; apply it to hooks, not topics alone.")
    return out


if __name__ == "__main__":
    main()
