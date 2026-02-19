#!/usr/bin/env python3
"""
TikTok Content Posting API - Direct Post Video Upload.
Uses official API (no browser automation needed).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
import secrets
import threading

# ─── Configuration ──────────────────────────────────────────────────
CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY", "")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("TIKTOK_REDIRECT_URI", "https://avarajar.github.io/viral-shorts/")

BASE_URL = "https://open.tiktokapis.com"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = f"{BASE_URL}/v2/oauth/token/"

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiktok_tokens.json")


# ─── Token Management ───────────────────────────────────────────────

def save_tokens(token_data):
    to_save = {
        "access_token": token_data["access_token"],
        "refresh_token": token_data["refresh_token"],
        "open_id": token_data.get("open_id", ""),
        "expires_at": time.time() + token_data.get("expires_in", 86400),
        "refresh_expires_at": time.time() + token_data.get("refresh_expires_in", 31536000),
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(to_save, f, indent=2)
    print(f"  [tokens] Saved to {TOKEN_FILE}", file=sys.stderr)
    return to_save


def load_tokens():
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, "r") as f:
        data = json.load(f)
    if time.time() > data.get("refresh_expires_at", 0):
        print("  [tokens] Refresh token expired. Re-auth needed.", file=sys.stderr)
        return None
    return data


def _post_form(url, params):
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def exchange_code(auth_code):
    params = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "code": auth_code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    data = _post_form(TOKEN_URL, params)
    if "access_token" not in data:
        raise RuntimeError(f"Token exchange failed: {data}")
    return save_tokens(data)


def refresh_token(refresh_tok):
    params = {
        "client_key": CLIENT_KEY,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
    }
    data = _post_form(TOKEN_URL, params)
    if "access_token" not in data:
        raise RuntimeError(f"Token refresh failed: {data}")
    return save_tokens(data)


def get_access_token():
    tokens = load_tokens()
    if tokens is None:
        print("  [auth] No tokens. Run: python3 upload_tiktok.py --auth", file=sys.stderr)
        sys.exit(1)
    if time.time() > tokens.get("expires_at", 0):
        print("  [auth] Access token expired, refreshing...", file=sys.stderr)
        tokens = refresh_token(tokens["refresh_token"])
    return tokens["access_token"]


# ─── OAuth Flow ──────────────────────────────────────────────────────

class CallbackHandler(BaseHTTPRequestHandler):
    auth_code = None

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        CallbackHandler.auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if CallbackHandler.auth_code:
            self.wfile.write(b"<h1>Autorizado! Puedes cerrar esta ventana.</h1>")
        else:
            err = params.get("error_description", ["Error desconocido"])[0]
            self.wfile.write(f"<h1>Error: {err}</h1>".encode())

    def log_message(self, *args):
        pass


def run_auth_flow():
    state = secrets.token_urlsafe(16)
    auth_params = urllib.parse.urlencode({
        "client_key": CLIENT_KEY,
        "response_type": "code",
        "scope": "video.publish",
        "redirect_uri": REDIRECT_URI,
        "state": state,
    })
    auth_url = f"{AUTH_URL}?{auth_params}"

    print("\n" + "=" * 60, file=sys.stderr)
    print("  TIKTOK AUTHORIZATION", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"\n  Open this link in your browser:\n", file=sys.stderr)
    print(f"  {auth_url}\n", file=sys.stderr)
    print("  After authorizing, you will be redirected.", file=sys.stderr)
    print("  Copy the FULL URL from your browser's address bar", file=sys.stderr)
    print("  and paste it below.\n", file=sys.stderr)

    redirected_url = input("  Paste redirected URL here: ").strip()

    params = urllib.parse.parse_qs(urllib.parse.urlparse(redirected_url).query)
    code = params.get("code", [None])[0]

    if not code:
        print("  [ERR] No authorization code found in URL", file=sys.stderr)
        sys.exit(1)

    print("  [OK] Code received, exchanging for tokens...", file=sys.stderr)
    tokens = exchange_code(code)
    print("  [OK] Tokens saved!", file=sys.stderr)
    return tokens


# ─── TikTok API ──────────────────────────────────────────────────────

def _api(method, path, access_token, body=None):
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8")
        print(f"  [API] HTTP {e.code}: {err}", file=sys.stderr)
        raise RuntimeError(f"API error {e.code}: {err}")


def query_creator(access_token):
    result = _api("POST", "/v2/post/publish/creator_info/query/", access_token)
    if result.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"Creator info failed: {result}")
    data = result["data"]
    print(f"  [creator] @{data['creator_username']} ({data['creator_nickname']})", file=sys.stderr)
    print(f"  [creator] Privacy: {data['privacy_level_options']}", file=sys.stderr)
    return data


def upload_video(video_path, title, access_token, privacy="SELF_ONLY"):
    """Complete upload flow: init -> upload file -> check status."""
    file_size = os.path.getsize(video_path)

    # Single chunk for shorts (< 64MB)
    chunk_size = file_size
    total_chunks = 1

    print(f"  [upload] File: {video_path} ({file_size / 1024 / 1024:.1f} MB)", file=sys.stderr)

    # Init
    body = {
        "post_info": {
            "title": title,
            "privacy_level": privacy,
            "disable_duet": False,
            "disable_stitch": False,
            "disable_comment": False,
            "is_aigc": True,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        },
    }

    result = _api("POST", "/v2/post/publish/video/init/", access_token, body)
    if result.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"Init failed: {result}")

    publish_id = result["data"]["publish_id"]
    upload_url = result["data"]["upload_url"]
    print(f"  [upload] publish_id: {publish_id}", file=sys.stderr)

    # Upload file
    with open(video_path, "rb") as f:
        video_data = f.read()

    req = urllib.request.Request(upload_url, data=video_data, headers={
        "Content-Type": "video/mp4",
        "Content-Length": str(file_size),
        "Content-Range": f"bytes 0-{file_size - 1}/{file_size}",
    }, method="PUT")

    with urllib.request.urlopen(req, timeout=120) as resp:
        print(f"  [upload] Uploaded -> HTTP {resp.status}", file=sys.stderr)

    # Poll status
    print(f"  [status] Checking publish status...", file=sys.stderr)
    for _ in range(24):  # max 2 min
        time.sleep(5)
        status_result = _api("POST", "/v2/post/publish/status/fetch/", access_token,
                             {"publish_id": publish_id})
        if status_result.get("error", {}).get("code") != "ok":
            continue
        data = status_result["data"]
        status = data.get("status", "UNKNOWN")
        print(f"  [status] {status}", file=sys.stderr)

        if status == "PUBLISH_COMPLETE":
            post_ids = data.get("publicaly_available_post_id", [])
            return {"success": True, "status": status, "post_ids": post_ids,
                    "publish_id": publish_id}
        if status == "FAILED":
            return {"success": False, "status": status,
                    "reason": data.get("fail_reason", "Unknown")}

    return {"success": False, "status": "TIMEOUT", "publish_id": publish_id}


def upload_short(video_path, title, tags=None):
    """Upload a single short with title and tags."""
    access_token = get_access_token()

    # Query creator to get available privacy levels
    creator = query_creator(access_token)
    available = creator.get("privacy_level_options", ["SELF_ONLY"])

    # Default to SELF_ONLY while app is under review; change manually once approved
    privacy = "SELF_ONLY"

    # Build description with hashtags
    tag_str = ""
    if tags:
        tag_str = " " + " ".join(f"#{t.lstrip('#')}" for t in tags)
    core_tags = "#fyp #viral #storytime #shorts #reddit"
    description = f"{title}{tag_str} {core_tags}"
    if len(description) > 2200:
        description = description[:2200]

    print(f"  [post] Privacy: {privacy}", file=sys.stderr)
    print(f"  [post] Title: {description[:80]}...", file=sys.stderr)

    return upload_video(video_path, description, access_token, privacy)


def upload_from_manifest(manifest_path, max_uploads=None):
    """Upload shorts from pipeline manifest. Optionally limit to max_uploads."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    if not manifest.get("success"):
        return {"success": False, "error": "Pipeline manifest shows failure"}

    shorts = manifest.get("shorts", [])
    if not shorts:
        return {"success": False, "error": "No shorts in manifest"}

    if max_uploads and max_uploads < len(shorts):
        print(f"  [limit] Uploading {max_uploads} of {len(shorts)} shorts", file=sys.stderr)
        shorts = shorts[:max_uploads]

    results = []
    for i, short in enumerate(shorts):
        path = short.get("path", "")
        title = short.get("title", f"Short {i+1}")
        tags = short.get("tags", [])

        print(f"\n--- TikTok Upload {i+1}/{len(shorts)}: {title} ---", file=sys.stderr)
        result = upload_short(path, title, tags)
        result["title"] = title
        results.append(result)

        if i < len(shorts) - 1:
            print("  Waiting 10s...", file=sys.stderr)
            time.sleep(10)

    uploaded = sum(1 for r in results if r.get("success"))
    return {"success": uploaded > 0, "uploaded": uploaded, "total": len(shorts),
            "results": results}


if __name__ == "__main__":
    if not CLIENT_KEY or not CLIENT_SECRET:
        print("Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET env vars", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  upload_tiktok.py --auth              # Authorize (first time)", file=sys.stderr)
        print("  upload_tiktok.py --refresh            # Refresh token", file=sys.stderr)
        print("  upload_tiktok.py <video.mp4> [title]  # Upload video", file=sys.stderr)
        print("  upload_tiktok.py --manifest <file>    # Upload from manifest", file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--auth":
        run_auth_flow()
    elif sys.argv[1] == "--refresh":
        tokens = load_tokens()
        if tokens:
            refresh_token(tokens["refresh_token"])
            print("Token refreshed.", file=sys.stderr)
        else:
            print("No tokens. Run --auth first.", file=sys.stderr)
    elif sys.argv[1] == "--manifest" and len(sys.argv) > 2:
        manifest_file = sys.argv[2]
        max_up = None
        if "--max" in sys.argv:
            idx = sys.argv.index("--max")
            if idx + 1 < len(sys.argv):
                max_up = int(sys.argv[idx + 1])
        result = upload_from_manifest(manifest_file, max_uploads=max_up)
        print(json.dumps(result, indent=2))
    else:
        video = sys.argv[1]
        title = sys.argv[2] if len(sys.argv) > 2 else "Story Time"
        result = upload_short(video, title)
        print(json.dumps(result, indent=2))
