#!/usr/bin/env python3
"""
Download viral clips using yt-dlp.
Trims clips to max duration and converts to standard format.
"""

import json
import subprocess
import sys
import os
from pathlib import Path

MAX_DURATION = 45  # seconds - max clip length
OUTPUT_DIR = "/pipeline/clips"
MAX_HEIGHT = 1080
COOKIES_FILE = "/pipeline/config/cookies.txt"


def download_clip(post: dict, output_dir: str) -> dict | None:
    """Download a single clip with yt-dlp and trim it."""
    clip_id = post["id"]
    url = post["url"]
    raw_path = os.path.join(output_dir, f"{clip_id}_raw.mp4")
    final_path = os.path.join(output_dir, f"{clip_id}.mp4")

    if os.path.exists(final_path):
        print(f"  [SKIP] {clip_id} already exists", file=sys.stderr)
        return {**post, "local_path": final_path}

    # Download with yt-dlp
    print(f"  [DL] {clip_id}: {post['title'][:60]}...", file=sys.stderr)
    dl_cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", f"best[height<={MAX_HEIGHT}]/best",
        "--merge-output-format", "mp4",
        "-o", raw_path,
        "--socket-timeout", "30",
        "--retries", "3",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
    ]
    if os.path.exists(COOKIES_FILE):
        dl_cmd.extend(["--cookies", COOKIES_FILE])
    dl_cmd.append(url)

    try:
        subprocess.run(dl_cmd, capture_output=True, timeout=120, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [ERR] Failed to download {clip_id}: {e}", file=sys.stderr)
        _cleanup(raw_path)
        return None

    if not os.path.exists(raw_path):
        print(f"  [ERR] No file downloaded for {clip_id}", file=sys.stderr)
        return None

    # Get duration
    duration = _get_duration(raw_path)
    if duration is None or duration < 3:
        print(f"  [SKIP] {clip_id}: too short ({duration}s)", file=sys.stderr)
        _cleanup(raw_path)
        return None

    # Trim if needed + normalize format
    trim_args = []
    if duration > MAX_DURATION:
        trim_args = ["-t", str(MAX_DURATION)]
        print(f"  [TRIM] {clip_id}: {duration:.0f}s -> {MAX_DURATION}s", file=sys.stderr)

    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", raw_path,
        *trim_args,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-threads", "1",
        final_path,
    ]

    try:
        subprocess.run(ffmpeg_cmd, capture_output=True, timeout=300, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [ERR] FFmpeg failed for {clip_id}: {e}", file=sys.stderr)
        _cleanup(raw_path, final_path)
        return None

    # Cleanup raw file
    _cleanup(raw_path)

    actual_duration = _get_duration(final_path) or MAX_DURATION
    print(f"  [OK] {clip_id}: {actual_duration:.0f}s", file=sys.stderr)

    return {**post, "local_path": final_path, "duration": actual_duration}


def _get_duration(filepath: str) -> float | None:
    """Get video duration using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", filepath],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return None


def _cleanup(*paths):
    """Remove files if they exist."""
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def download_all(posts_file: str, output_dir: str = OUTPUT_DIR) -> list:
    """Download all clips from a posts JSON file."""
    os.makedirs(output_dir, exist_ok=True)

    with open(posts_file) as f:
        posts = json.load(f)

    results = []
    for post in posts:
        result = download_clip(post, output_dir)
        if result:
            results.append(result)

    print(f"\n  Downloaded {len(results)}/{len(posts)} clips", file=sys.stderr)

    # Save results
    results_path = os.path.join(output_dir, "downloaded.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: download_clips.py <posts.json> [output_dir]", file=sys.stderr)
        sys.exit(1)

    posts_file = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_DIR
    download_all(posts_file, out_dir)
