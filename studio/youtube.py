"""Minimal YouTube Data/Analytics API client (stdlib only). Credentials come
from environment variables populated from GitHub encrypted secrets."""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"


class AuthError(RuntimeError):
    pass


def access_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"].strip(),
        "client_secret": os.environ["YT_CLIENT_SECRET"].strip(),
        "refresh_token": os.environ["YT_REFRESH_TOKEN"].strip(),
        "grant_type": "refresh_token",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=30) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        # never print secrets; Google's error body contains only an error code/description
        raise AuthError(f"token refresh failed ({e.code}): {body[:300]}")


def get(path, params, token):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)
