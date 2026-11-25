"""Read-only connection test: refresh the token and read the channel's name."""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from studio import youtube  # noqa: E402

result = {"checked_at": datetime.datetime.utcnow().isoformat() + "Z"}
missing = [k for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN") if not os.environ.get(k)]
if missing:
    result.update(ok=False, error=f"missing secrets: {missing}")
else:
    try:
        tok = youtube.access_token()
        ch = youtube.get("channels", {"part": "snippet,status", "mine": "true"}, tok)
        items = ch.get("items", [])
        if not items:
            result.update(ok=False, error="token works but no channel found (wrong account chosen?)")
        else:
            c = items[0]
            result.update(ok=True, channel_title=c["snippet"]["title"], channel_id=c["id"],
                          custom_url=c["snippet"].get("customUrl"),
                          long_uploads_status=c.get("status", {}).get("longUploadsStatus"),
                          privacy_status=c.get("status", {}).get("privacyStatus"))
    except Exception as e:  # noqa: BLE001
        result.update(ok=False, error=str(e)[:400])
os.makedirs("state", exist_ok=True)
json.dump(result, open("state/auth_check.json", "w"), indent=1)
print(json.dumps(result, indent=1))
sys.exit(0 if result.get("ok") else 1)
