#!/usr/bin/env python3
# v2 - auto-deploy via GitHub Actions
"""
Master pipeline script. Orchestrates the full flow:
  scrape -> download -> narrate -> compile -> cleanup

Can be called from n8n Execute Command or cron.
Outputs JSON manifest for n8n to use in upload nodes.
"""

import json
import os
import shutil
import sys
import time

# Add scripts dir to path
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from scrape_viral import scrape_viral
from download_clips import download_all
from generate_narration import generate_script, generate_all_audio
from compile_video import compile_long_video, generate_shorts, cleanup_temp

BASE_DIR = "/pipeline"
CLIPS_DIR = f"{BASE_DIR}/clips"
AUDIO_DIR = f"{BASE_DIR}/audio"
OUTPUT_DIR = f"{BASE_DIR}/output"


def cleanup_all():
    """Remove all temporary files."""
    for d in [CLIPS_DIR, AUDIO_DIR, os.path.join(OUTPUT_DIR, "tmp")]:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)


def run_pipeline() -> dict:
    """Run the full pipeline. Returns manifest dict."""
    start_time = time.time()
    result = {"success": False, "error": None}

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        result["error"] = "GROQ_API_KEY not set"
        return result

    try:
        # Ensure dirs exist
        for d in [CLIPS_DIR, AUDIO_DIR, OUTPUT_DIR, f"{OUTPUT_DIR}/shorts"]:
            os.makedirs(d, exist_ok=True)

        # Step 1: Scrape viral posts
        print("\n[1/5] Scraping viral posts...", file=sys.stderr)
        posts_file = os.path.join(CLIPS_DIR, "posts.json")
        posts = scrape_viral(posts_file)
        if not posts:
            result["error"] = "No viral posts found"
            return result
        print(f"  Found {len(posts)} viral posts", file=sys.stderr)

        # Step 2: Download clips
        print("\n[2/5] Downloading clips...", file=sys.stderr)
        clips = download_all(posts_file, CLIPS_DIR)
        if not clips:
            result["error"] = "No clips downloaded"
            return result
        print(f"  Downloaded {len(clips)} clips", file=sys.stderr)

        # Step 3: Generate narration
        print("\n[3/5] Generating narration...", file=sys.stderr)
        script = generate_script(clips, groq_key)
        audio_manifest = generate_all_audio(script, AUDIO_DIR)

        # Save script for reference
        script_path = os.path.join(AUDIO_DIR, "script.json")
        with open(script_path, "w") as f:
            json.dump(script, f, indent=2)

        # Step 4: Compile video
        print("\n[4/5] Compiling video...", file=sys.stderr)
        compilation_path = compile_long_video(clips, script, audio_manifest)
        shorts = generate_shorts(clips, script)

        # Step 5: Cleanup temp files (keep final outputs)
        print("\n[5/5] Cleaning up...", file=sys.stderr)
        cleanup_temp()
        # Remove raw clips (keep only final outputs)
        for clip in clips:
            path = clip.get("local_path")
            if path and os.path.exists(path):
                os.remove(path)

        elapsed = time.time() - start_time

        result = {
            "success": True,
            "compilation": compilation_path,
            "compilation_exists": os.path.exists(compilation_path) if compilation_path else False,
            "shorts_count": len(shorts),
            "shorts": shorts,
            "script": script,
            "clips_used": len(clips),
            "elapsed_seconds": round(elapsed),
            "video_title": script.get("video_title", ""),
            "video_description": script.get("video_description", ""),
            "tags": script.get("tags", []),
        }

    except Exception as e:
        result["error"] = str(e)
        import traceback
        traceback.print_exc(file=sys.stderr)

    return result


def main():
    print("=" * 50, file=sys.stderr)
    print("  VIRAL PIPELINE - Starting...", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    result = run_pipeline()

    # Output result as JSON (for n8n to parse)
    print(json.dumps(result, indent=2))

    if result.get("success"):
        print(f"\n  Pipeline completed in {result['elapsed_seconds']}s", file=sys.stderr)
        print(f"  Compilation: {result.get('compilation', 'N/A')}", file=sys.stderr)
        print(f"  Shorts: {result.get('shorts_count', 0)}", file=sys.stderr)
    else:
        print(f"\n  Pipeline FAILED: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
