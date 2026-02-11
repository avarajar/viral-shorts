#!/usr/bin/env python3
"""
Scrape viral videos from multiple sources that work from cloud IPs.
No Reddit API needed - uses yt-dlp extractors and public feeds.
"""

import json
import sys
import subprocess
import os
import time
from pathlib import Path

TOTAL_CLIPS = 10


def fetch_youtube_trending(limit: int = 20) -> list:
    """Fetch YouTube trending/popular videos using yt-dlp."""
    print("  Scanning YouTube Trending...", file=sys.stderr)
    cmd = [
        "yt-dlp", "--flat-playlist", "--no-warnings",
        "--dump-json", "--playlist-items", f"1:{limit}",
        "https://www.youtube.com/feed/trending",
    ]
    return _run_ytdlp_list(cmd, "YouTube Trending")


def fetch_youtube_popular_shorts(limit: int = 20) -> list:
    """Fetch popular YouTube Shorts using search."""
    print("  Scanning YouTube Shorts...", file=sys.stderr)
    # Search for recent viral/popular shorts
    queries = [
        "ytsearch15:viral moment today",
        "ytsearch15:funny fail compilation 2026",
        "ytsearch10:unexpected moments caught on camera",
    ]
    results = []
    for query in queries:
        cmd = [
            "yt-dlp", "--flat-playlist", "--no-warnings",
            "--dump-json", query,
        ]
        results.extend(_run_ytdlp_list(cmd, f"YT Search"))
        time.sleep(1)
    return results


def fetch_tiktok_trending(limit: int = 15) -> list:
    """Fetch trending TikTok videos via yt-dlp search."""
    print("  Scanning TikTok trends...", file=sys.stderr)
    queries = [
        "tiktoksearch10:viral today",
        "tiktoksearch10:funny fail",
    ]
    results = []
    for query in queries:
        cmd = [
            "yt-dlp", "--flat-playlist", "--no-warnings",
            "--dump-json", query,
        ]
        batch = _run_ytdlp_list(cmd, "TikTok")
        results.extend(batch)
        time.sleep(1)
    return results


def _run_ytdlp_list(cmd: list, source: str) -> list:
    """Run yt-dlp and parse JSON lines output."""
    results = []
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        for line in proc.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                entry = {
                    "id": data.get("id", ""),
                    "subreddit": source,  # reuse field as "source"
                    "title": data.get("title", ""),
                    "score": data.get("view_count") or data.get("like_count") or 0,
                    "url": data.get("url") or data.get("webpage_url", ""),
                    "permalink": data.get("webpage_url", ""),
                    "num_comments": data.get("comment_count") or 0,
                    "created_utc": 0,
                    "duration": data.get("duration") or 0,
                }
                # Only include videos (skip very long ones and very short)
                dur = entry["duration"]
                if dur and (dur < 5 or dur > 600):
                    continue
                if entry["url"]:
                    results.append(entry)
            except json.JSONDecodeError:
                continue
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        print(f"  [WARN] {source} fetch failed: {e}", file=sys.stderr)

    print(f"    Found {len(results)} from {source}", file=sys.stderr)
    return results


def scrape_viral(output_path: str = None) -> list:
    """Scrape viral videos from all available sources."""
    all_posts = []

    # YouTube Trending (most reliable)
    all_posts.extend(fetch_youtube_trending())

    # YouTube search for viral content
    all_posts.extend(fetch_youtube_popular_shorts())

    # TikTok (may not work from all IPs)
    all_posts.extend(fetch_tiktok_trending())

    # Sort by views/score descending
    all_posts.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate by ID
    seen = set()
    unique = []
    for post in all_posts:
        key = post["id"]
        if key and key not in seen:
            seen.add(key)
            unique.append(post)

    result = unique[:TOTAL_CLIPS]

    print(f"\n  Total: {len(result)} viral videos selected", file=sys.stderr)
    for i, p in enumerate(result):
        views = f"{p['score']:,}" if p['score'] else "?"
        print(f"    {i+1}. [{p['subreddit']}] {p['title'][:60]}... ({views} views)", file=sys.stderr)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(result, f, indent=2)

    return result


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else None
    posts = scrape_viral(output)
    if not output:
        print(json.dumps(posts, indent=2))
