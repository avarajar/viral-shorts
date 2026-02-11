#!/usr/bin/env python3
"""
Compile viral clips into a final video with narration, subtitles,
transitions, and background music. Also generates individual shorts.

Uses FFmpeg directly via subprocess for performance on ARM.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = "/pipeline"
CLIPS_DIR = f"{BASE_DIR}/clips"
AUDIO_DIR = f"{BASE_DIR}/audio"
OUTPUT_DIR = f"{BASE_DIR}/output"
SHORTS_DIR = f"{BASE_DIR}/output/shorts"
MUSIC_DIR = f"{BASE_DIR}/templates/music"

# Video settings
WIDTH = 1920
HEIGHT = 1080
FPS = 30
CRF = 23  # Quality (lower = better, 18-28 typical)
PRESET = "fast"  # Speed vs compression tradeoff

# Shorts settings
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920


def get_duration(filepath: str) -> float:
    """Get media file duration."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", filepath],
        capture_output=True, text=True, timeout=30
    )
    return float(result.stdout.strip())


def get_video_dimensions(filepath: str) -> tuple:
    """Get video width and height."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", filepath],
        capture_output=True, text=True, timeout=30
    )
    parts = result.stdout.strip().split(",")
    return int(parts[0]), int(parts[1])


def scale_and_pad(input_path: str, output_path: str, target_w: int, target_h: int):
    """Scale video to fit target dimensions with padding (letterbox/pillarbox)."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1"
        ),
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-c:a", "aac", "-b:a", "128k",
        "-r", str(FPS),
        "-threads", "1",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=300, check=True)


def create_text_video(text: str, duration: float, output_path: str,
                      w: int = WIDTH, h: int = HEIGHT, fontsize: int = 48):
    """Create a video with text on black background."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={duration}:r={FPS}",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
    ]
    # Only add drawtext if there's actual text
    if text.strip():
        safe_text = text.replace("'", "\\'").replace(":", "\\:")
        cmd.extend(["-vf", (
            f"drawtext=text='{safe_text}'"
            f":fontsize={fontsize}:fontcolor=white"
            f":x=(w-text_w)/2:y=(h-text_h)/2"
            f":font=Sans"
        )])
    cmd.extend([
        "-t", str(duration),
        "-c:v", "libx264", "-preset", PRESET,
        "-c:a", "aac",
        "-shortest",
        output_path,
    ])
    subprocess.run(cmd, capture_output=True, timeout=120, check=True)


def concat_videos(file_list: list, output_path: str):
    """Concatenate videos using FFmpeg concat demuxer."""
    list_file = output_path + ".txt"
    with open(list_file, "w") as f:
        for filepath in file_list:
            f.write(f"file '{filepath}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=300, check=True)
    os.remove(list_file)


def add_background_music(video_path: str, music_path: str, output_path: str,
                         music_volume: float = 0.08):
    """Mix background music into video at low volume."""
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", music_path,
        "-filter_complex", (
            f"[1:a]aloop=loop=-1:size=2e+09,volume={music_volume}[music];"
            f"[0:a][music]amix=inputs=2:duration=first:dropout_transition=3[out]"
        ),
        "-map", "0:v", "-map", "[out]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=300, check=True)


def add_watermark(video_path: str, output_path: str, text: str = "Subscribe!"):
    """Add a subtle text watermark to the video."""
    safe_text = text.replace("'", "\\'").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", (
            f"drawtext=text='{safe_text}'"
            f":fontsize=24:fontcolor=white@0.5"
            f":x=w-tw-20:y=h-th-20"
            f":font=Sans"
        ),
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-c:a", "copy",
        "-threads", "1",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=600, check=True)


def compile_long_video(clips: list, script: dict, audio_manifest: dict) -> str:
    """Compile the full-length compilation video."""
    print("  Compiling long-form video...", file=sys.stderr)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    segments = []
    tmp_dir = os.path.join(OUTPUT_DIR, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # Intro narration over black screen
    intro_audio = audio_manifest.get("intro")
    if intro_audio and os.path.exists(intro_audio):
        intro_dur = get_duration(intro_audio)
        intro_video = os.path.join(tmp_dir, "intro.mp4")
        create_text_video("", intro_dur, intro_video)
        # Merge intro audio
        intro_merged = os.path.join(tmp_dir, "intro_merged.mp4")
        cmd = [
            "ffmpeg", "-y", "-i", intro_video, "-i", intro_audio,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            intro_merged,
        ]
        subprocess.run(cmd, capture_output=True, timeout=60, check=True)
        segments.append(intro_merged)

    # Each clip with its narration
    clip_audios = audio_manifest.get("clips", [])
    for i, clip in enumerate(clips):
        clip_path = clip.get("local_path")
        if not clip_path or not os.path.exists(clip_path):
            continue

        clip_audio = clip_audios[i] if i < len(clip_audios) else {}

        # Before narration
        before_audio = clip_audio.get("before")
        if before_audio and os.path.exists(before_audio):
            before_dur = get_duration(before_audio)
            before_video = os.path.join(tmp_dir, f"before_{i}.mp4")
            create_text_video("", before_dur, before_video)
            before_merged = os.path.join(tmp_dir, f"before_{i}_merged.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", before_video, "-i", before_audio,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                before_merged,
            ]
            subprocess.run(cmd, capture_output=True, timeout=60, check=True)
            segments.append(before_merged)

        # The clip itself (normalized to target dimensions)
        normalized = os.path.join(tmp_dir, f"clip_{i}_norm.mp4")
        scale_and_pad(clip_path, normalized, WIDTH, HEIGHT)
        segments.append(normalized)

        # After narration
        after_audio = clip_audio.get("after")
        if after_audio and os.path.exists(after_audio):
            after_dur = get_duration(after_audio)
            after_video = os.path.join(tmp_dir, f"after_{i}.mp4")
            create_text_video("", after_dur, after_video)
            after_merged = os.path.join(tmp_dir, f"after_{i}_merged.mp4")
            cmd = [
                "ffmpeg", "-y", "-i", after_video, "-i", after_audio,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                after_merged,
            ]
            subprocess.run(cmd, capture_output=True, timeout=60, check=True)
            segments.append(after_merged)

    # Outro
    outro_audio = audio_manifest.get("outro")
    if outro_audio and os.path.exists(outro_audio):
        outro_dur = get_duration(outro_audio)
        outro_video = os.path.join(tmp_dir, "outro.mp4")
        create_text_video("SUBSCRIBE FOR MORE!", outro_dur, outro_video, fontsize=64)
        outro_merged = os.path.join(tmp_dir, "outro_merged.mp4")
        cmd = [
            "ffmpeg", "-y", "-i", outro_video, "-i", outro_audio,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            outro_merged,
        ]
        subprocess.run(cmd, capture_output=True, timeout=60, check=True)
        segments.append(outro_merged)

    if not segments:
        print("  [ERR] No segments to compile!", file=sys.stderr)
        return ""

    # Concatenate all segments
    raw_compilation = os.path.join(OUTPUT_DIR, "compilation_raw.mp4")
    concat_videos(segments, raw_compilation)

    # Add background music if available
    final_path = os.path.join(OUTPUT_DIR, "compilation.mp4")
    music_files = list(Path(MUSIC_DIR).glob("*.mp3")) if os.path.isdir(MUSIC_DIR) else []
    if music_files:
        add_background_music(raw_compilation, str(music_files[0]), final_path)
        os.remove(raw_compilation)
    else:
        os.rename(raw_compilation, final_path)

    duration = get_duration(final_path)
    size_mb = os.path.getsize(final_path) / (1024 * 1024)
    print(f"  Compilation: {duration:.0f}s, {size_mb:.1f}MB", file=sys.stderr)

    return final_path


def generate_shorts(clips: list, script: dict) -> list:
    """Generate individual vertical shorts from the best clips."""
    print("  Generating shorts...", file=sys.stderr)
    os.makedirs(SHORTS_DIR, exist_ok=True)

    shorts_data = script.get("shorts_hooks", [])
    generated = []

    for short_info in shorts_data:
        clip_num = short_info["clip_number"]
        if clip_num > len(clips):
            continue

        clip = clips[clip_num - 1]
        clip_path = clip.get("local_path")
        if not clip_path or not os.path.exists(clip_path):
            continue

        hook_text = short_info.get("hook_text", "WAIT FOR IT")
        safe_hook = hook_text.replace("'", "\\'").replace(":", "\\:")
        output_path = os.path.join(SHORTS_DIR, f"short_{clip_num}.mp4")

        # Convert to vertical (crop center) + add hook text overlay
        cmd = [
            "ffmpeg", "-y", "-i", clip_path,
            "-vf", (
                f"scale=-2:{SHORTS_HEIGHT},"
                f"crop={SHORTS_WIDTH}:{SHORTS_HEIGHT},"
                f"drawtext=text='{safe_hook}'"
                f":fontsize=56:fontcolor=white:borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=100"
                f":font=Sans"
                f":enable='lt(t,3)'"  # Show for first 3 seconds
            ),
            "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
            "-c:a", "aac", "-b:a", "128k",
            "-t", "60",  # Max 60s for shorts
            "-threads", "1",
            output_path,
        ]

        try:
            subprocess.run(cmd, capture_output=True, timeout=180, check=True)
            generated.append({
                "path": output_path,
                "clip_number": clip_num,
                "hook_text": hook_text,
                "caption": short_info.get("caption", ""),
            })
            print(f"  [OK] Short {clip_num}", file=sys.stderr)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"  [ERR] Short {clip_num} failed: {e}", file=sys.stderr)

    return generated


def cleanup_temp():
    """Remove temporary files."""
    tmp_dir = os.path.join(OUTPUT_DIR, "tmp")
    if os.path.isdir(tmp_dir):
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: compile_video.py <downloaded.json> <script.json>", file=sys.stderr)
        sys.exit(1)

    clips_file = sys.argv[1]
    script_file = sys.argv[2]

    with open(clips_file) as f:
        clips = json.load(f)
    with open(script_file) as f:
        script = json.load(f)

    # Load audio manifest
    audio_manifest_path = os.path.join(AUDIO_DIR, "audio_manifest.json")
    if os.path.exists(audio_manifest_path):
        with open(audio_manifest_path) as f:
            audio_manifest = json.load(f)
    else:
        audio_manifest = {}

    # Compile long video
    compilation_path = compile_long_video(clips, script, audio_manifest)

    # Generate shorts
    shorts = generate_shorts(clips, script)

    # Save manifest
    manifest = {
        "compilation": compilation_path,
        "shorts": shorts,
        "script": script,
    }
    manifest_path = os.path.join(OUTPUT_DIR, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n  Output manifest: {manifest_path}", file=sys.stderr)

    # Cleanup temp files (keep final outputs)
    cleanup_temp()
