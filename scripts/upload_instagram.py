#!/usr/bin/env python3
"""
Instagram Reels Upload via Instagram Graph API.
Uses Instagram Login (IGAA tokens) + Content Publishing API.

Flow:
  1. Upload video via public URL -> create media container
  2. Wait for container to finish processing
  3. Publish the container

Requires:
  - Instagram Professional account (Creator or Business)
  - Facebook App with instagram_content_publish permission
  - Video accessible via public URL (served by nginx on this server)
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# ─── Configuration ──────────────────────────────────────────────────
INSTAGRAM_APP_ID = os.environ.get("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET = os.environ.get("INSTAGRAM_APP_SECRET", "")
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "")
INSTAGRAM_USER_ID = os.environ.get("INSTAGRAM_USER_ID", "")
INSTAGRAM_VIDEO_BASE_URL = os.environ.get("INSTAGRAM_VIDEO_BASE_URL", "https://joselito.mywire.org/shorts")

IG_GRAPH_API = "https://graph.instagram.com"
IG_GRAPH_API_V = "https://graph.instagram.com/v21.0"

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instagram_tokens.json")


# ─── Token Management ───────────────────────────────────────────────

def save_tokens(token_data):
    to_save = {
        "access_token": token_data["access_token"],
        "user_id": token_data.get("user_id", INSTAGRAM_USER_ID),
        "expires_at": token_data.get("expires_at", time.time() + 5184000),  # 60 days
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
    if time.time() > data.get("expires_at", 0):
        print("  [tokens] Token expired. Refresh needed.", file=sys.stderr)
        return None
    return data


def get_access_token():
    """Get access token from file, env, or fail."""
    tokens = load_tokens()
    if tokens:
        return tokens["access_token"], tokens.get("user_id", INSTAGRAM_USER_ID)

    if INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID:
        return INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_USER_ID

    print("  [auth] No tokens. Run: python3 upload_instagram.py --auth", file=sys.stderr)
    sys.exit(1)


def _api_get(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api_post(url, params):
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8")
        print(f"  [API] HTTP {e.code}: {err}", file=sys.stderr)
        raise RuntimeError(f"API error {e.code}: {err}")


# ─── OAuth Flow ──────────────────────────────────────────────────────

def get_long_lived_token(short_token):
    """Exchange a short-lived Instagram token for a long-lived one (60 days)."""
    result = _api_get(f"{IG_GRAPH_API}/access_token", {
        "grant_type": "ig_exchange_token",
        "client_secret": INSTAGRAM_APP_SECRET,
        "access_token": short_token,
    })
    if "access_token" not in result:
        raise RuntimeError(f"Token exchange failed: {result}")

    result["expires_at"] = time.time() + result.get("expires_in", 5184000)
    return result


def refresh_long_lived_token(current_token):
    """Refresh a long-lived Instagram token (must not be expired)."""
    result = _api_get(f"{IG_GRAPH_API}/refresh_access_token", {
        "grant_type": "ig_refresh_token",
        "access_token": current_token,
    })
    if "access_token" not in result:
        raise RuntimeError(f"Token refresh failed: {result}")

    result["expires_at"] = time.time() + result.get("expires_in", 5184000)
    return result


def get_instagram_user_id(access_token):
    """Get the Instagram user ID from the token."""
    result = _api_get(f"{IG_GRAPH_API_V}/me", {
        "fields": "user_id,username",
        "access_token": access_token,
    })
    user_id = result.get("user_id") or result.get("id")
    username = result.get("username", "unknown")

    if not user_id:
        raise RuntimeError(f"Could not get user ID: {result}")

    print(f"  [auth] Instagram: @{username} (ID: {user_id})", file=sys.stderr)
    return user_id


def run_auth_flow(token_arg=None):
    """Auth flow: exchange short-lived token for long-lived one."""
    print("\n" + "=" * 60, file=sys.stderr)
    print("  INSTAGRAM AUTHORIZATION", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    if token_arg:
        short_token = token_arg
    else:
        print(f"\n  1. Go to your app's Instagram > API setup", file=sys.stderr)
        print(f"  2. Generate a token for your IG account", file=sys.stderr)
        print(f"  3. Copy the token and paste it below\n", file=sys.stderr)
        short_token = input("  Paste access token here: ").strip()

    if not short_token:
        print("  [ERR] No token provided", file=sys.stderr)
        sys.exit(1)

    # Exchange for long-lived token
    print("  [auth] Exchanging for long-lived token...", file=sys.stderr)
    long_lived = get_long_lived_token(short_token)
    access_token = long_lived["access_token"]

    # Get IG user ID
    print("  [auth] Looking up Instagram account...", file=sys.stderr)
    user_id = get_instagram_user_id(access_token)

    token_data = {
        "access_token": access_token,
        "user_id": user_id,
        "expires_at": long_lived.get("expires_at", time.time() + 5184000),
    }
    save_tokens(token_data)
    print(f"\n  [OK] Authorized! Token valid for ~60 days.", file=sys.stderr)
    print(f"  [OK] Instagram User ID: {user_id}", file=sys.stderr)
    return token_data


# ─── Instagram Publishing API ────────────────────────────────────────

def create_reel_container(user_id, access_token, video_url, caption):
    """Step 1: Create a media container for the Reel."""
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "access_token": access_token,
    }
    result = _api_post(f"{IG_GRAPH_API_V}/{user_id}/media", params)

    container_id = result.get("id")
    if not container_id:
        raise RuntimeError(f"Failed to create container: {result}")

    print(f"  [container] Created: {container_id}", file=sys.stderr)
    return container_id


def check_container_status(container_id, access_token):
    """Check if the media container is ready for publishing."""
    result = _api_get(f"{IG_GRAPH_API_V}/{container_id}", {
        "fields": "status_code,status",
        "access_token": access_token,
    })
    return result.get("status_code", "UNKNOWN"), result.get("status", "")


def publish_container(user_id, access_token, container_id):
    """Step 2: Publish the media container."""
    result = _api_post(f"{IG_GRAPH_API_V}/{user_id}/media_publish", {
        "creation_id": container_id,
        "access_token": access_token,
    })

    media_id = result.get("id")
    if not media_id:
        raise RuntimeError(f"Publish failed: {result}")

    print(f"  [publish] Published! Media ID: {media_id}", file=sys.stderr)
    return media_id


def upload_reel(video_url, caption, access_token=None, user_id=None):
    """Upload a single Reel. Returns result dict."""
    if not access_token or not user_id:
        access_token, user_id = get_access_token()

    print(f"  [upload] Video URL: {video_url}", file=sys.stderr)
    print(f"  [upload] Caption: {caption[:80]}...", file=sys.stderr)

    # Step 1: Create container
    container_id = create_reel_container(user_id, access_token, video_url, caption)

    # Step 2: Wait for processing (Reels can take a while)
    print(f"  [status] Waiting for processing...", file=sys.stderr)
    for attempt in range(36):  # max 3 min
        time.sleep(5)
        status_code, status_msg = check_container_status(container_id, access_token)
        print(f"  [status] {status_code} {status_msg}", file=sys.stderr)

        if status_code == "FINISHED":
            break
        if status_code == "ERROR":
            return {"success": False, "status": status_code,
                    "error": status_msg, "container_id": container_id}
    else:
        return {"success": False, "status": "TIMEOUT", "container_id": container_id}

    # Step 3: Publish
    media_id = publish_container(user_id, access_token, container_id)

    return {
        "success": True,
        "media_id": media_id,
        "container_id": container_id,
        "status": "PUBLISHED",
    }


def upload_short(video_path, title, tags=None):
    """Upload a single short as a Reel. Builds public URL from file path."""
    access_token, user_id = get_access_token()

    # Build public URL from local path
    filename = os.path.basename(video_path)
    video_url = f"{INSTAGRAM_VIDEO_BASE_URL}/{filename}"

    # Build caption with hashtags
    tag_str = ""
    if tags:
        tag_str = " " + " ".join(f"#{t.lstrip('#')}" for t in tags)
    core_tags = "#fyp #viral #storytime #shorts #reddit #reels"
    caption = f"{title}{tag_str} {core_tags}"
    if len(caption) > 2200:
        caption = caption[:2200]

    return upload_reel(video_url, caption, access_token, user_id)


def upload_from_manifest(manifest_path):
    """Upload all shorts from pipeline manifest."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    if not manifest.get("success"):
        return {"success": False, "error": "Pipeline manifest shows failure"}

    shorts = manifest.get("shorts", [])
    if not shorts:
        return {"success": False, "error": "No shorts in manifest"}

    access_token, user_id = get_access_token()

    results = []
    for i, short in enumerate(shorts):
        path = short.get("path", "")
        title = short.get("title", f"Short {i+1}")
        tags = short.get("tags", [])

        # Build public URL
        filename = os.path.basename(path)
        video_url = f"{INSTAGRAM_VIDEO_BASE_URL}/{filename}"

        # Build caption
        tag_str = ""
        if tags:
            tag_str = " " + " ".join(f"#{t.lstrip('#')}" for t in tags)
        core_tags = "#fyp #viral #storytime #shorts #reddit #reels"
        caption = f"{title}{tag_str} {core_tags}"
        if len(caption) > 2200:
            caption = caption[:2200]

        print(f"\n--- Instagram Upload {i+1}/{len(shorts)}: {title} ---", file=sys.stderr)

        try:
            result = upload_reel(video_url, caption, access_token, user_id)
        except Exception as e:
            result = {"success": False, "error": str(e)}

        result["title"] = title
        results.append(result)

        if i < len(shorts) - 1:
            print("  Waiting 30s (IG rate limit)...", file=sys.stderr)
            time.sleep(30)

    uploaded = sum(1 for r in results if r.get("success"))
    return {"success": uploaded > 0, "uploaded": uploaded, "total": len(shorts),
            "results": results}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:", file=sys.stderr)
        print("  upload_instagram.py --auth                # Authorize (first time)", file=sys.stderr)
        print("  upload_instagram.py --refresh             # Refresh token", file=sys.stderr)
        print("  upload_instagram.py <video.mp4> [title]   # Upload video", file=sys.stderr)
        print("  upload_instagram.py --manifest <file>     # Upload from manifest", file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == "--auth":
        if not INSTAGRAM_APP_SECRET:
            print("Set INSTAGRAM_APP_SECRET env var", file=sys.stderr)
            sys.exit(1)
        token_arg = sys.argv[2] if len(sys.argv) > 2 else None
        run_auth_flow(token_arg)
    elif sys.argv[1] == "--refresh":
        tokens = load_tokens()
        if tokens:
            refreshed = refresh_long_lived_token(tokens["access_token"])
            save_tokens({
                "access_token": refreshed["access_token"],
                "user_id": tokens.get("user_id", INSTAGRAM_USER_ID),
                "expires_at": refreshed.get("expires_at", time.time() + 5184000),
            })
            print("Token refreshed.", file=sys.stderr)
        else:
            print("No tokens. Run --auth first.", file=sys.stderr)
    elif sys.argv[1] == "--manifest" and len(sys.argv) > 2:
        result = upload_from_manifest(sys.argv[2])
        print(json.dumps(result, indent=2))
    else:
        video = sys.argv[1]
        title = sys.argv[2] if len(sys.argv) > 2 else "Story Time"
        result = upload_short(video, title)
        print(json.dumps(result, indent=2))
