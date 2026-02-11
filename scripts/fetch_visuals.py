#!/usr/bin/env python3
"""
Generate AI images for each story segment using HuggingFace FLUX (free).
Creates Ken Burns effect (slow zoom/pan) on each image for engaging visuals.
Falls back to Pexels stock footage if image generation fails.
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.parse
import time
import random

VISUALS_DIR = "/pipeline/visuals"
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
FPS = 30

POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY", "")

# HuggingFace FLUX - high quality AI image generation
HF_API_URL = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"

# Pexels as fallback
PEXELS_API_URL = "https://api.pexels.com/videos/search"


def generate_ai_image(prompt: str, output_path: str, hf_token: str = "") -> bool:
    """Generate an AI image. HuggingFace FLUX first (best quality), Pollinations fallback."""

    # Method 1: HuggingFace FLUX (best quality, handles faces well)
    if hf_token:
        hf_prompt = f"{prompt}, photorealistic, 8K, cinematic photography, shallow depth of field"
        if _generate_flux(hf_prompt, output_path, hf_token):
            return True
        print("    [INFO] HF failed, falling back to Pollinations", file=sys.stderr)

    # Method 2: Pollinations (free fallback - avoid faces, use environmental style)
    poll_prompt = _to_environmental(prompt)
    enhanced = f"{poll_prompt}, professional photography, cinematic color grading, bokeh background, shallow depth of field"
    return _generate_pollinations(enhanced, output_path)


def _to_environmental(prompt: str) -> str:
    """Convert a face/portrait prompt to an environmental/atmospheric one for Pollinations."""
    import re
    # Remove face-related terms
    removals = [
        r"close up portrait of [^,]+,",
        r"portrait of [^,]+,",
        r"[^,]*facial expression[^,]*,",
        r"[^,]*expression[^,]*with [^,]*eyes[^,]*,",
        r"both faces visible,",
        r"natural skin texture[^,]*,",
    ]
    result = prompt
    for pattern in removals:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    # Add environmental direction
    result = f"cinematic scene, no people, no faces, {result.strip().strip(',').strip()}, dark moody atmosphere, dramatic lighting"
    return result


NEGATIVE_PROMPT = "face,portrait,person close up,cartoon,anime,painting,illustration,drawing,sketch,blurry,deformed,ugly,bad anatomy,extra fingers,mutated hands,disfigured,bad proportions,watermark,text,logo"


def _generate_pollinations(prompt: str, output_path: str) -> bool:
    """Generate image via Pollinations.ai new API (gen.pollinations.ai)."""
    encoded = urllib.parse.quote(prompt)
    # New endpoint: gen.pollinations.ai/image/ (old image.pollinations.ai is deprecated)
    url = f"https://gen.pollinations.ai/image/{encoded}?width=1080&height=1920&model=flux&nologo=true&enhance=true"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/120.0.0.0",
        }
        if POLLINATIONS_API_KEY:
            headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=90) as resp:
            with open(output_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        if not (os.path.exists(output_path) and os.path.getsize(output_path) > 5000):
            return False
        # Check if Pollinations returned a placeholder/error image instead of real content
        try:
            with open(output_path, "rb") as check_f:
                raw = check_f.read()
            # Pollinations error images are PNGs containing telltale text
            # (rate limit, moved, sign up, etc.) - check raw bytes for these strings
            raw_lower = raw.lower()
            spam_markers = [b"pollinations.ai", b"rate limit", b"we have moved",
                            b"sign up here", b"enter.pollinations", b"anonymous tier"]
            for marker in spam_markers:
                if marker in raw_lower:
                    print(f"    [WARN] Pollinations placeholder image detected ({marker.decode()}), discarding",
                          file=sys.stderr)
                    os.remove(output_path)
                    return False
            # Also reject PNGs under 200KB (real 1080x1920 images are larger)
            if b"PNG" in raw[:16] and len(raw) < 200000:
                print(f"    [WARN] Pollinations small PNG detected ({len(raw)//1024}KB), discarding",
                      file=sys.stderr)
                os.remove(output_path)
                return False
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"    [WARN] Pollinations failed: {e}", file=sys.stderr)
        return False


def _generate_flux(prompt: str, output_path: str, hf_token: str) -> bool:
    """Generate image via HuggingFace FLUX (fallback)."""
    body = json.dumps({"inputs": prompt}).encode()
    try:
        req = urllib.request.Request(HF_API_URL, data=body, headers={
            "Authorization": f"Bearer {hf_token}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/120.0.0.0",
        })
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(output_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 5000
    except Exception as e:
        print(f"    [WARN] FLUX failed: {e}", file=sys.stderr)
        return False


def create_ken_burns(image_path: str, output_path: str, duration: float,
                     effect: str = "zoom_in"):
    """Create Ken Burns effect (slow zoom/pan) on a still image."""
    # Different effects for variety
    if effect == "zoom_in":
        # Slow zoom in from 1.0x to 1.15x
        zoompan = f"zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration*FPS)}:s={TARGET_WIDTH}x{TARGET_HEIGHT}:fps={FPS}"
    elif effect == "zoom_out":
        # Slow zoom out from 1.15x to 1.0x
        zoompan = f"zoompan=z='if(eq(on,1),1.15,max(zoom-0.0008,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration*FPS)}:s={TARGET_WIDTH}x{TARGET_HEIGHT}:fps={FPS}"
    elif effect == "pan_right":
        # Slow pan from left to right
        zoompan = f"zoompan=z='1.15':x='if(eq(on,1),0,min(x+1,iw-iw/zoom))':y='ih/2-(ih/zoom/2)':d={int(duration*FPS)}:s={TARGET_WIDTH}x{TARGET_HEIGHT}:fps={FPS}"
    else:
        # Pan left
        zoompan = f"zoompan=z='1.15':x='if(eq(on,1),iw-iw/zoom,max(x-1,0))':y='ih/2-(ih/zoom/2)':d={int(duration*FPS)}:s={TARGET_WIDTH}x{TARGET_HEIGHT}:fps={FPS}"

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-vf", zoompan,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        output_path,
    ]

    subprocess.run(cmd, capture_output=True, timeout=180, check=True)


def search_pexels(query: str, api_key: str, per_page: int = 3) -> list:
    """Search Pexels for stock video clips (fallback)."""
    url = f"{PEXELS_API_URL}?query={urllib.parse.quote(query)}&per_page={per_page}&orientation=landscape&size=medium"
    req = urllib.request.Request(url, headers={
        "Authorization": api_key,
        "User-Agent": "viral-pipeline/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            results = []
            for video in data.get("videos", []):
                for vf in video.get("video_files", []):
                    if vf.get("quality") == "hd" and vf.get("width", 0) >= 1280:
                        results.append({"url": vf["link"], "duration": video.get("duration", 10)})
                        break
            return results
    except Exception:
        return []


def download_file(url: str, output_path: str) -> bool:
    """Download a file from URL."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "viral-pipeline/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(output_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
    except Exception:
        return False


def normalize_video(input_path: str, output_path: str, target_duration: float):
    """Scale and loop a video clip to target duration."""
    cmd = [
        "ffmpeg", "-y", "-stream_loop", "-1", "-i", input_path,
        "-t", str(target_duration),
        "-vf", (
            f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "26",
        "-an", "-r", str(FPS),
        "-threads", "1",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=120, check=True)


# Ken Burns effects to alternate between
EFFECTS = ["zoom_in", "zoom_out", "pan_right", "pan_left"]


def fetch_visuals_for_segments(segments: list, output_dir: str,
                                hf_token: str = None,
                                pexels_key: str = None) -> list:
    """Generate AI visuals for each story segment."""
    os.makedirs(output_dir, exist_ok=True)
    results = []

    for i, seg in enumerate(segments):
        seg_num = seg.get("segment_number", i + 1)
        keywords = seg.get("visual_keywords", [])
        narration = seg.get("narration", "")
        duration = seg.get("audio_duration", 15)
        visual_path = os.path.join(output_dir, f"visual_{seg_num}.mp4")

        if os.path.exists(visual_path):
            results.append(visual_path)
            continue

        got_visual = False

        # Method 1: AI-generated image with Ken Burns effect (HuggingFace FLUX)
        if keywords and hf_token:
            image_prompt = " ".join(keywords[:3])
            if narration:
                # Use first sentence of narration for context
                first_sentence = narration.split(".")[0][:100]
                image_prompt = f"{first_sentence}, {image_prompt}"

            image_path = os.path.join(output_dir, f"img_{seg_num}.jpg")
            print(f"    Generating AI image {seg_num}: '{' '.join(keywords[:2])}'...",
                  file=sys.stderr)

            if generate_ai_image(image_prompt, image_path, hf_token):
                try:
                    effect = EFFECTS[i % len(EFFECTS)]
                    create_ken_burns(image_path, visual_path, duration, effect)
                    got_visual = True
                    print(f"    [OK] Visual {seg_num}: FLUX AI image + {effect}",
                          file=sys.stderr)
                except Exception as e:
                    print(f"    [WARN] Ken Burns failed: {e}", file=sys.stderr)
                finally:
                    try:
                        os.remove(image_path)
                    except OSError:
                        pass

            time.sleep(2)  # Respect HuggingFace rate limits

        # Method 2: Pexels stock video (fallback)
        if not got_visual and pexels_key and keywords:
            query = " ".join(keywords[:2])
            print(f"    Fallback Pexels: '{query}'...", file=sys.stderr)
            clips = search_pexels(query, pexels_key)
            if clips:
                raw_path = os.path.join(output_dir, f"raw_{seg_num}.mp4")
                if download_file(clips[0]["url"], raw_path):
                    try:
                        normalize_video(raw_path, visual_path, duration)
                        got_visual = True
                        print(f"    [OK] Visual {seg_num}: Pexels clip", file=sys.stderr)
                    except Exception:
                        pass
                    finally:
                        try:
                            os.remove(raw_path)
                        except OSError:
                            pass
            time.sleep(0.5)

        # Method 3: Dark gradient background (last resort)
        if not got_visual:
            _create_gradient_bg(duration, visual_path, i)
            print(f"    [OK] Visual {seg_num}: gradient background", file=sys.stderr)

        results.append(visual_path)

    return results


def _create_gradient_bg(duration: float, output_path: str, index: int):
    """Create an animated gradient background as last resort."""
    # Rotating dark gradients
    colors = [
        ("0x1a1a2e", "0x16213e"),
        ("0x0f3460", "0x1a1a2e"),
        ("0x2d132c", "0x1b1b2f"),
        ("0x162447", "0x1f4068"),
    ]
    c1, c2 = colors[index % len(colors)]
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c={c1}:s={TARGET_WIDTH}x{TARGET_HEIGHT}:d={duration}:r={FPS}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-shortest",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=60, check=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fetch_visuals.py <story.json> [output_dir]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        story = json.load(f)

    out_dir = sys.argv[2] if len(sys.argv) > 2 else VISUALS_DIR
    hf_token = os.environ.get("HF_TOKEN", "")
    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    visuals = fetch_visuals_for_segments(story["segments"], out_dir, hf_token, pexels_key)
    print(json.dumps(visuals, indent=2))
