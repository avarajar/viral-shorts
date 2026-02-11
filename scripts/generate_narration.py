#!/usr/bin/env python3
"""
Generate narration script using Groq API (free tier)
and convert to audio using edge-tts.
"""

import json
import os
import subprocess
import sys
import urllib.request

GROQ_MODEL = "llama-3.3-70b-versatile"
VOICE = "en-US-AndrewMultilingualNeural"  # Natural male English voice
AUDIO_DIR = "/pipeline/audio"


def generate_script(clips: list, groq_api_key: str) -> dict:
    """Generate narration script and metadata using Groq."""

    titles_list = "\n".join(
        f"CLIP {i+1} (r/{c['subreddit']}): {c['title']}"
        for i, c in enumerate(clips)
    )

    prompt = f"""You are a narrator for a viral video compilation channel (like Daily Dose of Internet).

I have these {len(clips)} viral clips for today's compilation:

{titles_list}

Generate the following in JSON format:
{{
  "video_title": "catchy YouTube title under 70 chars, use curiosity/surprise",
  "video_description": "YouTube description with keywords, 2-3 sentences",
  "tags": ["tag1", "tag2", ...],
  "intro_narration": "brief 1-sentence hook to start the video (under 15 words)",
  "clips": [
    {{
      "clip_number": 1,
      "narration_before": "1-2 sentence setup BEFORE the clip plays (create anticipation)",
      "narration_after": "optional 1 sentence reaction AFTER clip (only if funny/surprising)"
    }},
    ...
  ],
  "outro_narration": "brief closing, ask to subscribe (under 20 words)",
  "shorts_hooks": [
    {{
      "clip_number": 1,
      "hook_text": "short text overlay for the first 2 seconds (max 6 words, ALL CAPS)",
      "caption": "TikTok/Shorts caption with hashtags"
    }},
    ...pick the 5 best clips for shorts
  ]
}}

Rules:
- Keep narrations SHORT. 1-2 sentences max per clip.
- Sound natural and conversational, not robotic or overhyped.
- Match the tone: funny clips get humor, impressive clips get awe.
- The hook_text should make people STOP scrolling.
- Return ONLY valid JSON, no markdown."""

    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }).encode()

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "viral-pipeline/1.0",
        },
    )

    print("  Generating narration script via Groq...", file=sys.stderr)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        print(f"  [ERR] Groq API failed: {e}", file=sys.stderr)
        return _fallback_script(clips)


def _fallback_script(clips: list) -> dict:
    """Generate a basic script if Groq fails."""
    return {
        "video_title": "You Won't Believe What Happened Today",
        "video_description": "The most viral videos from today's internet.",
        "tags": ["viral", "compilation", "funny", "unexpected"],
        "intro_narration": "Here are today's most incredible moments from the internet.",
        "clips": [
            {
                "clip_number": i + 1,
                "narration_before": f"Check this out from r/{c['subreddit']}.",
                "narration_after": "",
            }
            for i, c in enumerate(clips)
        ],
        "outro_narration": "Subscribe for more daily viral videos.",
        "shorts_hooks": [
            {
                "clip_number": i + 1,
                "hook_text": "WAIT FOR IT",
                "caption": f"#{c['subreddit']} #viral #fyp",
            }
            for i, c in enumerate(clips[:5])
        ],
    }


def generate_audio(text: str, output_path: str, voice: str = VOICE) -> bool:
    """Generate audio from text using edge-tts."""
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--text", text,
        "--write-media", output_path,
        "--write-subtitles", output_path.replace(".mp3", ".vtt"),
    ]

    try:
        subprocess.run(cmd, capture_output=True, timeout=60, check=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [ERR] edge-tts failed: {e}", file=sys.stderr)
        return False


def generate_all_audio(script: dict, audio_dir: str = AUDIO_DIR) -> dict:
    """Generate all audio files for the narration."""
    os.makedirs(audio_dir, exist_ok=True)
    audio_files = {}

    # Intro
    intro_path = os.path.join(audio_dir, "intro.mp3")
    if generate_audio(script["intro_narration"], intro_path):
        audio_files["intro"] = intro_path

    # Per-clip narrations
    audio_files["clips"] = []
    for clip_data in script.get("clips", []):
        clip_num = clip_data["clip_number"]
        clip_audio = {}

        before_text = clip_data.get("narration_before", "")
        if before_text:
            before_path = os.path.join(audio_dir, f"clip_{clip_num}_before.mp3")
            if generate_audio(before_text, before_path):
                clip_audio["before"] = before_path

        after_text = clip_data.get("narration_after", "")
        if after_text:
            after_path = os.path.join(audio_dir, f"clip_{clip_num}_after.mp3")
            if generate_audio(after_text, after_path):
                clip_audio["after"] = after_path

        audio_files["clips"].append(clip_audio)

    # Outro
    outro_path = os.path.join(audio_dir, "outro.mp3")
    if generate_audio(script["outro_narration"], outro_path):
        audio_files["outro"] = outro_path

    print(f"  Generated audio files in {audio_dir}", file=sys.stderr)
    return audio_files


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: generate_narration.py <downloaded.json> [audio_dir]", file=sys.stderr)
        sys.exit(1)

    clips_file = sys.argv[1]
    audio_dir = sys.argv[2] if len(sys.argv) > 2 else AUDIO_DIR

    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        print("  [ERR] GROQ_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    with open(clips_file) as f:
        clips = json.load(f)

    # Generate script
    script = generate_script(clips, groq_key)
    script_path = os.path.join(audio_dir, "script.json")
    os.makedirs(audio_dir, exist_ok=True)
    with open(script_path, "w") as f:
        json.dump(script, f, indent=2)
    print(f"  Script saved to {script_path}", file=sys.stderr)

    # Generate audio
    audio_files = generate_all_audio(script, audio_dir)
    audio_manifest = os.path.join(audio_dir, "audio_manifest.json")
    with open(audio_manifest, "w") as f:
        json.dump(audio_files, f, indent=2)
