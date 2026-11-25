"""YouTube Data API client (stdlib only): token refresh, resumable upload,
thumbnails, captions, playlists. Credentials come from environment variables
populated from GitHub encrypted secrets; nothing secret is ever logged."""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"


class AuthError(RuntimeError):
    """Credentials revoked/expired: the pipeline must pause, not retry."""


class QuotaError(RuntimeError):
    """Daily quota exhausted: pause until tomorrow."""


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
        if e.code in (400, 401) and ("invalid_grant" in body or "unauthorized_client" in body or "invalid_client" in body):
            raise AuthError(f"credentials rejected ({e.code}): {body[:200]}")
        raise RuntimeError(f"token refresh failed ({e.code}): {body[:200]}")


def _request(method, url, token, body=None, headers=None, retries=5, raw=False):
    hdrs = {"Authorization": f"Bearer {token}"}
    if headers:
        hdrs.update(headers)
    if body is not None and not isinstance(body, (bytes, bytearray)):
        body = json.dumps(body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
            with urllib.request.urlopen(req, timeout=300) as r:
                return r if raw else (json.load(r) if r.length != 0 else {})
        except urllib.error.HTTPError as e:
            txt = e.read().decode(errors="replace")
            if e.code == 401:
                raise AuthError(txt[:200])
            if e.code == 403 and ("quotaExceeded" in txt or "dailyLimitExceeded" in txt or "uploadLimitExceeded" in txt):
                raise QuotaError(txt[:300])
            if e.code in (500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code}: {txt[:400]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise


def get(path, params, token):
    return _request("GET", f"{API}/{path}?{urllib.parse.urlencode(params)}", token)


def upload_video(path, snippet, status, token, chunk=16 * 1024 * 1024, log=print):
    """Resumable upload with chunk-level retry. Returns the video resource."""
    size = os.path.getsize(path)
    init = _request("POST", f"{UPLOAD}/videos?uploadType=resumable&part=snippet,status", token,
                    body={"snippet": snippet, "status": status},
                    headers={"X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"}, raw=True)
    session = init.headers["Location"]
    sent = 0
    with open(path, "rb") as f:
        while sent < size:
            f.seek(sent)
            data = f.read(chunk)
            end = sent + len(data) - 1
            for attempt in range(6):
                try:
                    req = urllib.request.Request(session, data=data, method="PUT", headers={
                        "Authorization": f"Bearer {token}", "Content-Length": str(len(data)),
                        "Content-Range": f"bytes {sent}-{end}/{size}"})
                    with urllib.request.urlopen(req, timeout=600) as r:
                        return json.load(r)  # 200/201: complete
                except urllib.error.HTTPError as e:
                    if e.code == 308:  # resume incomplete
                        rng = e.headers.get("Range")
                        sent = int(rng.split("-")[1]) + 1 if rng else 0
                        log(f"  uploaded {sent / size:.0%}")
                        break
                    if e.code in (500, 502, 503, 504) and attempt < 5:
                        time.sleep(2 ** attempt * 3)
                        continue
                    raise RuntimeError(f"upload failed {e.code}: {e.read().decode(errors='replace')[:300]}")
                except (urllib.error.URLError, TimeoutError, ConnectionError):
                    if attempt < 5:
                        time.sleep(2 ** attempt * 3)
                        continue
                    raise
    raise RuntimeError("upload ended without a final response")


def set_thumbnail(video_id, image_path, token):
    with open(image_path, "rb") as f:
        data = f.read()
    ctype = "image/jpeg" if image_path.endswith(".jpg") else "image/png"
    return _request("POST", f"{UPLOAD}/thumbnails/set?videoId={video_id}&uploadType=media", token,
                    body=data, headers={"Content-Type": ctype})


def insert_captions(video_id, srt_path, token, language="en", name="English"):
    boundary = uuid.uuid4().hex
    meta = json.dumps({"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": False}})
    with open(srt_path, "rb") as f:
        srt = f.read()
    body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
            f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode() + srt + f"\r\n--{boundary}--".encode()
    return _request("POST", f"{UPLOAD}/captions?part=snippet&uploadType=multipart", token, body=body,
                    headers={"Content-Type": f"multipart/related; boundary={boundary}"})


def ensure_playlist(title, description, token, cache):
    if title in cache:
        return cache[title]
    res = _request("POST", f"{API}/playlists?part=snippet,status", token,
                   body={"snippet": {"title": title, "description": description}, "status": {"privacyStatus": "public"}})
    cache[title] = res["id"]
    return res["id"]


def add_to_playlist(playlist_id, video_id, token):
    return _request("POST", f"{API}/playlistItems?part=snippet", token,
                    body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})


def recent_upload_titles(token, n=50):
    ch = get("channels", {"part": "contentDetails", "mine": "true"}, token)
    pl = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    items = get("playlistItems", {"part": "snippet", "playlistId": pl, "maxResults": n}, token).get("items", [])
    return {it["snippet"]["title"]: it["snippet"]["resourceId"]["videoId"] for it in items}
