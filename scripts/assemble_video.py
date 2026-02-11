#!/usr/bin/env python3
"""
Assemble vertical YouTube Shorts with karaoke-style subtitles.
Multiple AI images + Ken Burns effects + big bold word-by-word captions.
"""

import os
import subprocess
import sys
import re

WIDTH = 1080
HEIGHT = 1920
FPS = 30
FONT_PATH = "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf"
OUTPUT_DIR = "/pipeline/output"
SHORTS_DIR = "/pipeline/output/shorts"

EFFECTS = ["zoom_in", "zoom_out", "pan_down", "pan_up"]


def parse_vtt_words(vtt_path: str) -> list:
    """Parse VTT file and split sentences into individual words with distributed timing."""
    words = []
    if not vtt_path or not os.path.exists(vtt_path):
        return words

    with open(vtt_path) as f:
        content = f.read()

    cues = []
    current_start = None
    current_end = None

    for line in content.split("\n"):
        line = line.strip()
        if "-->" in line:
            parts = line.split(" --> ")
            if len(parts) == 2:
                current_start = _parse_time(parts[0])
                current_end = _parse_time(parts[1])
        elif line and line != "WEBVTT" and not line.startswith("NOTE") and not line.isdigit():
            if current_start is not None:
                text = re.sub(r'<[^>]+>', '', line)
                if text.strip():
                    cues.append({
                        "text": text.strip(),
                        "start": current_start,
                        "end": current_end,
                    })
                current_start = None
                current_end = None

    for cue in cues:
        cue_words = cue["text"].split()
        if not cue_words:
            continue
        cue_duration = cue["end"] - cue["start"]
        word_duration = cue_duration / len(cue_words)

        for j, word in enumerate(cue_words):
            words.append({
                "text": word,
                "start": cue["start"] + j * word_duration,
                "end": cue["start"] + (j + 1) * word_duration,
            })

    return words


def _parse_time(time_str: str) -> float:
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


def group_words(words: list, max_words: int = 3) -> list:
    """Group words into chunks for display."""
    groups = []
    for i in range(0, len(words), max_words):
        chunk = words[i:i + max_words]
        if chunk:
            groups.append({
                "text": " ".join(w["text"] for w in chunk),
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
            })
    return groups


def escape_drawtext(text: str) -> str:
    """Escape text for FFmpeg drawtext filter."""
    text = text.replace("\\", "\\\\\\\\")
    text = text.replace("'", "\u2019")
    text = text.replace('"', '\\"')
    text = text.replace(":", "\\\\:")
    text = text.replace("%", "%%%%")
    text = text.replace("[", "\\\\[")
    text = text.replace("]", "\\\\]")
    text = text.replace(";", "\\\\;")
    return text


def build_subtitle_filter(vtt_path: str) -> str:
    """Build FFmpeg drawtext filter chain for cinematic subtitles."""
    words = parse_vtt_words(vtt_path)
    if not words:
        return ""

    groups = group_words(words, max_words=3)
    if not groups:
        return ""

    # Lower third positioning (like pro reels)
    y_pos = int(HEIGHT * 0.68)

    filters = []
    for g in groups:
        text = escape_drawtext(g["text"].upper())
        start = g["start"]
        end = g["end"]
        if not text.strip():
            continue

        # Scale font down for longer text to prevent overflow
        raw_len = len(g["text"])
        if raw_len > 18:
            fsize = 58
        elif raw_len > 14:
            fsize = 64
        else:
            fsize = 72

        f = (
            f"drawtext=text='{text}'"
            f":fontfile={FONT_PATH}"
            f":fontsize={fsize}"
            f":fontcolor=white"
            f":borderw=4"
            f":bordercolor=black@0.8"
            f":shadowcolor=black@0.5"
            f":shadowx=2:shadowy=2"
            f":x=(w-text_w)/2"
            f":y={y_pos}"
            f":enable='between(t\\,{start:.3f}\\,{end:.3f})'"
        )
        filters.append(f)

    return ",".join(filters)


def build_hook_filter(hook_text: str, duration: float = 2.5) -> str:
    """Build drawtext filter for hook text overlay (clean white, upper area)."""
    if not hook_text:
        return ""

    text = escape_drawtext(hook_text.upper())
    return (
        f"drawtext=text='{text}'"
        f":fontfile={FONT_PATH}"
        f":fontsize=90"
        f":fontcolor=white"
        f":borderw=5"
        f":bordercolor=black@0.8"
        f":shadowcolor=black@0.5"
        f":shadowx=2:shadowy=2"
        f":x=(w-text_w)/2"
        f":y={int(HEIGHT * 0.28)}"
        f":enable='between(t\\,0.2\\,{duration})'"
    )


def get_duration(filepath: str) -> float:
    """Get media file duration."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", filepath],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return 0


def _zoompan_expr(effect: str, frames: int) -> str:
    """Get zoompan filter expression for a specific Ken Burns effect."""
    base = f":d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    if effect == "zoom_in":
        return f"zoompan=z='min(zoom+0.0008\\,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'{base}"
    elif effect == "zoom_out":
        return f"zoompan=z='if(eq(on\\,1)\\,1.15\\,max(zoom-0.0008\\,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'{base}"
    elif effect == "pan_down":
        return f"zoompan=z='1.12':x='iw/2-(iw/zoom/2)':y='if(eq(on\\,1)\\,0\\,min(y+1\\,ih-ih/zoom))'{base}"
    else:  # pan_up
        return f"zoompan=z='1.12':x='iw/2-(iw/zoom/2)':y='if(eq(on\\,1)\\,ih-ih/zoom\\,max(y-1\\,0))'{base}"


def _create_bg_video(image_paths: list, duration: float, output_path: str) -> bool:
    """Create background video from multiple images (static + concat, fast on ARM)."""
    n = len(image_paths)
    seg_dur = duration / n

    cmd = ["ffmpeg", "-y"]

    # Add each image as a looped input
    for img in image_paths:
        cmd.extend(["-loop", "1", "-t", f"{seg_dur:.2f}", "-framerate", str(FPS), "-i", img])

    # Scale + pad each to vertical, then concat (no zoompan = fast on ARM)
    filter_parts = []
    concat_inputs = ""

    for i in range(n):
        filter_parts.append(
            f"[{i}:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={FPS}[v{i}]"
        )
        concat_inputs += f"[v{i}]"

    filter_parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[vout]")
    filter_complex = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-pix_fmt", "yuv420p",
        "-threads", "1",
        output_path,
    ])

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300, text=True)
        if result.returncode != 0:
            print(f"    [ERR] BG video: {result.stderr[-300:]}", file=sys.stderr)
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 10000
    except Exception as e:
        print(f"    [ERR] BG video failed: {e}", file=sys.stderr)
        return False


def assemble_short(image_paths, audio_path: str, vtt_path: str,
                   output_path: str, hook_text: str = "",
                   duration: float = None) -> bool:
    """Assemble a YouTube Short from images + audio + karaoke subtitles.

    image_paths: single path (str) or list of paths for multi-image.
    """
    if isinstance(image_paths, str):
        image_paths = [image_paths]

    # Filter to only existing images
    image_paths = [p for p in image_paths if os.path.exists(p) and os.path.getsize(p) > 5000]
    if not image_paths:
        print("    [ERR] No valid images", file=sys.stderr)
        return False

    if not duration:
        duration = get_duration(audio_path)
    if duration <= 0:
        duration = 45

    duration = min(duration + 0.5, 59)

    if len(image_paths) == 1:
        return _assemble_single(image_paths[0], audio_path, vtt_path,
                                output_path, hook_text, duration)

    return _assemble_multi(image_paths, audio_path, vtt_path,
                           output_path, hook_text, duration)


def _assemble_single(image_path, audio_path, vtt_path, output_path, hook_text, duration):
    """Single image assembly."""
    zoompan = (
        f"zoompan=z='min(zoom+0.0005\\,1.12)'"
        f":x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)'"
        f":d={int(duration * FPS)}"
        f":s={WIDTH}x{HEIGHT}"
        f":fps={FPS}"
    )

    subtitle_filter = build_subtitle_filter(vtt_path)
    hook_filter = build_hook_filter(hook_text)

    vf_parts = [zoompan]
    if subtitle_filter:
        vf_parts.append(subtitle_filter)
    if hook_filter:
        vf_parts.append(hook_filter)

    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-vf", vf,
        "-t", str(duration),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-threads", "1",
        output_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300, text=True)
        if result.returncode != 0:
            print(f"    [ERR] FFmpeg: {result.stderr[-200:]}", file=sys.stderr)
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 10000
    except Exception as e:
        print(f"    [ERR] Assembly failed: {e}", file=sys.stderr)
        return False


def _assemble_multi(image_paths, audio_path, vtt_path, output_path, hook_text, duration):
    """Multi-image assembly: Ken Burns per image, concat, then overlay subtitles + audio."""

    work_dir = os.path.dirname(output_path)
    bg_path = os.path.join(work_dir, f"_bg_{os.path.basename(output_path)}")

    print(f"    Creating background from {len(image_paths)} images...", file=sys.stderr)

    if not _create_bg_video(image_paths, duration, bg_path):
        print("    [WARN] Multi-image failed, falling back to first image", file=sys.stderr)
        return _assemble_single(image_paths[0], audio_path, vtt_path,
                                output_path, hook_text, duration)

    # Step 2: Overlay audio + subtitles on background video
    subtitle_filter = build_subtitle_filter(vtt_path)
    hook_filter = build_hook_filter(hook_text)

    vf_parts = []
    if subtitle_filter:
        vf_parts.append(subtitle_filter)
    if hook_filter:
        vf_parts.append(hook_filter)

    cmd = [
        "ffmpeg", "-y",
        "-i", bg_path,
        "-i", audio_path,
    ]

    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])

    cmd.extend([
        "-t", str(duration),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-threads", "1",
        output_path,
    ])

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=300, text=True)
        if result.returncode != 0:
            print(f"    [ERR] FFmpeg overlay: {result.stderr[-200:]}", file=sys.stderr)
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 10000
    except Exception as e:
        print(f"    [ERR] Overlay failed: {e}", file=sys.stderr)
        return False
    finally:
        try:
            os.remove(bg_path)
        except OSError:
            pass


if __name__ == "__main__":
    print("Use via story_pipeline.py", file=sys.stderr)
