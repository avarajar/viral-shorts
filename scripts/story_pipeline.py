#!/usr/bin/env python3
"""
Shorts Pipeline - generates viral YouTube Shorts from trending Reddit posts.
Flow: scrape Reddit -> adapt with Groq -> narrate -> generate AI images per scene -> assemble with karaoke subs
"""

import json
import os
import subprocess
import sys
import time

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from generate_story import generate_story
from fetch_visuals import generate_ai_image
from assemble_video import assemble_short

BASE_DIR = "/pipeline"
AUDIO_DIR = f"{BASE_DIR}/audio"
VISUALS_DIR = f"{BASE_DIR}/visuals"
OUTPUT_DIR = f"{BASE_DIR}/output"
SHORTS_DIR = f"{BASE_DIR}/output/shorts"


def narrate_short(text: str, audio_path: str, sub_path: str,
                  voice: str = "en-US-AndrewMultilingualNeural") -> float:
    """Generate audio + subtitles for a short story. Returns duration."""
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--text", text,
        "--write-media", audio_path,
        "--write-subtitles", sub_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", audio_path],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception as e:
        print(f"    [ERR] TTS failed: {e}", file=sys.stderr)
        return 0


def run_pipeline() -> dict:
    """Run the shorts pipeline. Returns manifest dict."""
    start_time = time.time()
    result = {"success": False, "error": None}

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        result["error"] = "GROQ_API_KEY not set"
        return result

    hf_token = os.environ.get("HF_TOKEN", "")

    try:
        for d in [AUDIO_DIR, VISUALS_DIR, OUTPUT_DIR, SHORTS_DIR]:
            os.makedirs(d, exist_ok=True)

        # Step 1: Scrape Reddit + adapt with Groq
        print("\n[1/4] Scraping Reddit trending + adapting stories...", file=sys.stderr)
        stories = generate_story(groq_key, count=3)
        if not stories or not stories.get("shorts"):
            result["error"] = "Failed to generate stories"
            return result

        shorts_data = stories["shorts"]
        generated_shorts = []

        for i, short in enumerate(shorts_data):
            idx = i + 1
            title = short.get("title", f"Short {idx}")
            narration = short.get("narration", "")
            scenes = short.get("scenes", [])
            hook_text = short.get("hook_text", "")

            if not narration:
                print(f"  [SKIP] Short {idx}: no narration", file=sys.stderr)
                continue

            print(f"\n--- Short {idx}: {title[:50]} ---", file=sys.stderr)

            # Step 2: Narrate
            print(f"  [2/4] Narrating...", file=sys.stderr)
            audio_path = os.path.join(AUDIO_DIR, f"short_{idx}.mp3")
            sub_path = os.path.join(AUDIO_DIR, f"short_{idx}.vtt")
            duration = narrate_short(narration, audio_path, sub_path)

            if duration <= 0:
                print(f"  [SKIP] Short {idx}: narration failed", file=sys.stderr)
                continue

            if duration > 58:
                print(f"  [WARN] Short {idx}: {duration:.1f}s > 58s, will be trimmed",
                      file=sys.stderr)

            print(f"  Duration: {duration:.1f}s", file=sys.stderr)

            # Step 3: Generate AI images for each scene
            print(f"  [3/4] Generating AI images ({len(scenes)} scenes)...", file=sys.stderr)
            scene_images = []

            if hf_token and scenes:
                for j, scene in enumerate(scenes):
                    # Handle both {"visual_prompt": "..."} and plain string formats
                    if isinstance(scene, dict):
                        prompt = scene.get("visual_prompt", "")
                    elif isinstance(scene, str):
                        prompt = scene
                    else:
                        continue
                    if not prompt:
                        continue
                    img_path = os.path.join(VISUALS_DIR, f"short_{idx}_scene_{j+1}.jpg")

                    print(f"    Scene {j+1}: generating...", file=sys.stderr)
                    if generate_ai_image(prompt, img_path, hf_token):
                        if os.path.exists(img_path) and os.path.getsize(img_path) > 5000:
                            scene_images.append(img_path)
                            print(f"    Scene {j+1}: OK ({os.path.getsize(img_path)/1024:.0f} KB)",
                                  file=sys.stderr)
                    else:
                        print(f"    Scene {j+1}: failed", file=sys.stderr)

                    time.sleep(2)  # HuggingFace rate limit

            # Fallback: if no scene images, try single image from narration
            if not scene_images and hf_token:
                fallback_prompt = f"dark cinematic scene, {narration.split('.')[0][:80]}, moody atmosphere, dramatic lighting"
                fallback_path = os.path.join(VISUALS_DIR, f"short_{idx}_fallback.jpg")
                print(f"    Fallback: generating from narration...", file=sys.stderr)
                if generate_ai_image(fallback_prompt, fallback_path, hf_token):
                    if os.path.exists(fallback_path) and os.path.getsize(fallback_path) > 5000:
                        scene_images.append(fallback_path)
                time.sleep(2)

            if not scene_images:
                print(f"  [SKIP] Short {idx}: no images generated", file=sys.stderr)
                continue

            print(f"  Images: {len(scene_images)} generated", file=sys.stderr)

            # Step 4: Assemble short with multi-image + karaoke subs
            print(f"  [4/4] Assembling short ({len(scene_images)} images)...", file=sys.stderr)
            output_path = os.path.join(SHORTS_DIR, f"short_{idx}.mp4")

            success = assemble_short(
                image_paths=scene_images,
                audio_path=audio_path,
                vtt_path=sub_path,
                output_path=output_path,
                hook_text=hook_text,
                duration=duration,
            )

            if success:
                size_mb = os.path.getsize(output_path) / (1024 * 1024)
                print(f"  [OK] Short {idx}: {duration:.1f}s, {size_mb:.1f}MB, {len(scene_images)} images",
                      file=sys.stderr)
                generated_shorts.append({
                    "path": output_path,
                    "title": title,
                    "description": short.get("description", ""),
                    "tags": short.get("tags", []),
                    "duration": round(duration, 1),
                    "hook_text": hook_text,
                    "images_used": len(scene_images),
                    "source_subreddit": short.get("source_subreddit", ""),
                })
            else:
                print(f"  [FAIL] Short {idx}: assembly failed", file=sys.stderr)

            # Cleanup scene images
            for img in scene_images:
                try:
                    os.remove(img)
                except OSError:
                    pass

        elapsed = time.time() - start_time

        if not generated_shorts:
            result["error"] = "No shorts generated successfully"
            return result

        # Use first short as the main for YouTube upload
        main_short = generated_shorts[0]

        result = {
            "success": True,
            "compilation": main_short["path"],
            "compilation_exists": os.path.exists(main_short["path"]),
            "shorts_count": len(generated_shorts),
            "shorts": generated_shorts,
            "clips_used": len(generated_shorts),
            "elapsed_seconds": round(elapsed),
            "video_title": main_short["title"],
            "video_description": main_short["description"],
            "tags": main_short["tags"],
        }

        # Save manifest for TikTok upload (runs on host via cron)
        manifest_path = os.path.join(OUTPUT_DIR, "tiktok_manifest.json")
        try:
            with open(manifest_path, "w") as mf:
                json.dump(result, mf, indent=2)
            print(f"  TikTok manifest saved: {manifest_path}", file=sys.stderr)
        except Exception as e:
            print(f"  [WARN] Could not save TikTok manifest: {e}", file=sys.stderr)

    except Exception as e:
        result["error"] = str(e)
        import traceback
        traceback.print_exc(file=sys.stderr)

    return result


def main():
    print("=" * 50, file=sys.stderr)
    print("  SHORTS PIPELINE - Reddit Stories Edition", file=sys.stderr)
    print("=" * 50, file=sys.stderr)

    result = run_pipeline()

    # Output result as JSON (for n8n to parse)
    print(json.dumps(result, indent=2))

    if result.get("success"):
        print(f"\n  Pipeline completed in {result['elapsed_seconds']}s", file=sys.stderr)
        print(f"  Shorts generated: {result['shorts_count']}", file=sys.stderr)
        for s in result.get("shorts", []):
            print(f"    - {s['title'][:50]} ({s['duration']}s, {s['images_used']} imgs)",
                  file=sys.stderr)
    else:
        print(f"\n  Pipeline FAILED: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
