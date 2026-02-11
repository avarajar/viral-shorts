#!/usr/bin/env python3
"""
Generate narration audio from story segments using edge-tts.
Returns per-segment audio files with durations.
"""

import json
import os
import subprocess
import sys

VOICE = "en-US-AndrewMultilingualNeural"
AUDIO_DIR = "/pipeline/audio"


def get_audio_duration(filepath: str) -> float:
    """Get audio file duration using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", filepath],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return 0


def generate_segment_audio(text: str, output_path: str, voice: str = VOICE) -> float:
    """Generate audio for a single segment. Returns duration."""
    if not text or not text.strip():
        return 0

    sub_path = output_path.replace(".mp3", ".vtt")
    cmd = [
        "edge-tts",
        "--voice", voice,
        "--text", text,
        "--write-media", output_path,
        "--write-subtitles", sub_path,
    ]

    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        duration = get_audio_duration(output_path)
        return duration
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [ERR] edge-tts failed: {e}", file=sys.stderr)
        return 0


def narrate_all_segments(segments: list, audio_dir: str = AUDIO_DIR,
                          voice: str = VOICE) -> list:
    """Generate audio for all story segments. Returns updated segments with durations."""
    os.makedirs(audio_dir, exist_ok=True)

    total_duration = 0
    for seg in segments:
        seg_num = seg.get("segment_number", 0)
        text = seg.get("narration", "")
        audio_path = os.path.join(audio_dir, f"seg_{seg_num}.mp3")
        sub_path = os.path.join(audio_dir, f"seg_{seg_num}.vtt")

        duration = generate_segment_audio(text, audio_path, voice)
        seg["audio_path"] = audio_path
        seg["subtitle_path"] = sub_path
        seg["audio_duration"] = duration
        total_duration += duration

        if duration > 0:
            print(f"    Segment {seg_num}: {duration:.1f}s", file=sys.stderr)

    print(f"  Total narration: {total_duration:.0f}s ({total_duration/60:.1f} min)", file=sys.stderr)
    return segments


def generate_full_subtitles(segments: list, output_path: str):
    """Merge all segment VTT files into one continuous subtitle file."""
    offset = 0.0
    lines = ["WEBVTT", ""]

    for seg in segments:
        vtt_path = seg.get("subtitle_path", "")
        duration = seg.get("audio_duration", 0)

        if not vtt_path or not os.path.exists(vtt_path):
            offset += duration
            continue

        with open(vtt_path) as f:
            content = f.read()

        for line in content.split("\n"):
            if "-->" in line:
                # Parse timestamps and add offset
                parts = line.split(" --> ")
                if len(parts) == 2:
                    start = _parse_vtt_time(parts[0]) + offset
                    end = _parse_vtt_time(parts[1]) + offset
                    lines.append(f"{_format_vtt_time(start)} --> {_format_vtt_time(end)}")
            elif line.strip() and line.strip() != "WEBVTT":
                lines.append(line)

        offset += duration

    with open(output_path, "w") as f:
        f.write("\n".join(lines))

    return output_path


def _parse_vtt_time(time_str: str) -> float:
    """Parse VTT timestamp to seconds."""
    time_str = time_str.strip().replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return 0


def _format_vtt_time(seconds: float) -> str:
    """Format seconds to VTT timestamp."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: narrate_story.py <story.json> [audio_dir]", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        story = json.load(f)

    audio_dir = sys.argv[2] if len(sys.argv) > 2 else AUDIO_DIR
    segments = narrate_all_segments(story["segments"], audio_dir)

    # Save updated story with audio paths
    with open(sys.argv[1], "w") as f:
        json.dump({**story, "segments": segments}, f, indent=2)
