#!/usr/bin/env python3
"""
Clipping-campaign mode (Content Rewards and similar marketplaces).

Takes a long source video supplied by a campaign (stream VOD, podcast,
interview), finds the strongest moments from its transcript and renders
vertical 1080x1920 clips with burned-in word captions, ready to post.

    download (yt-dlp) -> audio chunks -> Groq Whisper (word timestamps)
      -> Groq LLM picks highlights -> ffmpeg: blur-fit layout + ASS captions
      -> manifest.json (clip paths + ready-to-paste captions)

Posting is NOT automatic on purpose: Content Rewards requires the post link to
be submitted within 30 minutes of publishing and has no submission API, so a
human posts and submits each clip.

Usage:
    python3 clip_campaign.py CAMPAIGN.json [--source URL] [--window 0:30:00-1:30:00]
                             [--count N] [--out DIR]

Env: GROQ_API_KEY
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime

GROQ_MODEL = "openai/gpt-oss-120b"
WHISPER_MODEL = "whisper-large-v3-turbo"
GROQ_BASE = "https://api.groq.com/openai/v1"
UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

OUTPUT_ROOT = "/pipeline/output/campaigns"
COOKIES_FILE = "/pipeline/config/cookies.txt"
MAX_HEIGHT = 1080
W, H = 1080, 1920

AUDIO_CHUNK_SEC = 600        # 10 min of 16kHz mono @32kbps ~ 2.4MB (Groq limit 25MB)
TRANSCRIPT_WINDOW_SEC = 600  # transcript slice sent per highlight-picking call
# Groq free tier caps at 8000 TPM; each highlight call is ~3-4k tokens.
LLM_CALL_GAP_SEC = 35
MAX_RETRIES = 3


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True)


# ── Download ────────────────────────────────────────────────────────────────

def parse_hms(s: str) -> float:
    parts = [float(p) for p in s.split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def download_source(url: str, work: str, window: str | None) -> str:
    path = os.path.join(work, "source.mp4")
    if os.path.exists(path):
        log(f"  [SKIP] source already downloaded")
        return path
    cmd = [
        "yt-dlp", "--no-warnings", "--no-playlist",
        "-f", f"bv*[height<={MAX_HEIGHT}]+ba/b[height<={MAX_HEIGHT}]/b",
        "--merge-output-format", "mp4",
        "-o", path, "--socket-timeout", "30", "--retries", "3",
        "--js-runtimes", "node", "--remote-components", "ejs:github",
    ]
    if window:
        # Stream copy (no re-encode): cuts land on keyframes, a few seconds off is fine
        cmd += ["--download-sections", f"*{window}"]
    if os.path.exists(COOKIES_FILE):
        cmd += ["--cookies", COOKIES_FILE]
    cmd.append(url)
    log(f"  [DL] {url} {('(' + window + ')') if window else ''}")
    run(cmd, timeout=3600)
    return path


def duration_of(path: str) -> float:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path]).stdout.strip()
    return float(out)


# ── Transcription (Groq Whisper) ────────────────────────────────────────────

def _multipart(fields: list, file_field: str, file_path: str):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    with open(file_path, "rb") as f:
        data = f.read()
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
        f'filename="{os.path.basename(file_path)}"\r\nContent-Type: audio/mpeg\r\n\r\n'.encode()
        + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _whisper(api_key: str, audio_path: str, language: str | None) -> dict:
    fields = [("model", WHISPER_MODEL), ("response_format", "verbose_json"),
              ("timestamp_granularities[]", "word"), ("timestamp_granularities[]", "segment"),
              ("temperature", "0")]
    if language:
        fields.append(("language", language))
    body, ctype = _multipart(fields, "file", audio_path)
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(f"{GROQ_BASE}/audio/transcriptions", data=body, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": ctype, "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            log(f"  [WARN] Whisper attempt {attempt}: HTTP {e.code} {detail}")
            if e.code == 400:
                break  # bad request won't fix itself on retry
            wait = float(e.headers.get("retry-after") or 30) if e.code == 429 else 10
            if attempt < MAX_RETRIES:
                time.sleep(min(wait, 120))
        except Exception as e:
            log(f"  [WARN] Whisper attempt {attempt}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(10)
    raise RuntimeError(f"Whisper failed for {audio_path}")


def transcribe(api_key: str, video: str, work: str, language: str | None) -> dict:
    """Returns {"segments": [{start,end,text}], "words": [{start,end,word}]} in source time."""
    cache = os.path.join(work, "transcript.json")
    if os.path.exists(cache):
        log("  [SKIP] transcript cached")
        with open(cache) as f:
            return json.load(f)

    total = duration_of(video)
    segments, words = [], []
    offset = 0.0
    idx = 0
    # Skip a trailing sliver (keyframe-aligned downloads run a hair long): Whisper
    # rejects near-empty audio with HTTP 400.
    while total - offset > 2:
        chunk = os.path.join(work, f"audio_{idx:03d}.mp3")
        chunk_cache = os.path.join(work, f"asr_{idx:03d}.json")
        if os.path.exists(chunk_cache):
            with open(chunk_cache) as f:
                res = json.load(f)
        else:
            run(["ffmpeg", "-y", "-v", "error", "-ss", str(offset), "-t", str(AUDIO_CHUNK_SEC),
                 "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", chunk])
            log(f"  [ASR] chunk {idx} @ {offset:.0f}s / {total:.0f}s")
            res = _whisper(api_key, chunk, language)
            os.remove(chunk)
            with open(chunk_cache, "w") as f:
                json.dump(res, f)
        for s in res.get("segments", []):
            segments.append({"start": s["start"] + offset, "end": s["end"] + offset,
                             "text": s["text"].strip()})
        for w in res.get("words", []):
            words.append({"start": w["start"] + offset, "end": w["end"] + offset,
                          "word": w["word"].strip()})
        offset += AUDIO_CHUNK_SEC
        idx += 1

    data = {"segments": segments, "words": words}
    with open(cache, "w") as f:
        json.dump(data, f)
    return data


# ── Highlight picking (Groq LLM) ────────────────────────────────────────────

def _call_llm(api_key: str, prompt: str) -> dict | None:
    body = json.dumps({
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }).encode()
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(f"{GROQ_BASE}/chat/completions", data=body, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
            "User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(json.loads(resp.read().decode())["choices"][0]["message"]["content"])
        except Exception as e:
            log(f"  [WARN] LLM attempt {attempt}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(LLM_CALL_GAP_SEC)
    return None


def pick_highlights(api_key: str, transcript: dict, campaign: dict) -> list:
    segs = transcript["segments"]
    if not segs:
        return []
    min_len, max_len = campaign.get("clip_seconds", [20, 60])
    brief = campaign.get("brief", "")
    lang = campaign.get("caption_language", "English")
    candidates = []
    t0, t_end = segs[0]["start"], segs[-1]["end"]
    win_start = t0
    first = True
    while win_start < t_end:
        win = [s for s in segs if win_start <= s["start"] < win_start + TRANSCRIPT_WINDOW_SEC]
        win_start += TRANSCRIPT_WINDOW_SEC
        if len(" ".join(s["text"] for s in win).split()) < 80:
            continue
        lines = "\n".join(f"[{s['start']:.1f}] {s['text']}" for s in win)
        prompt = f"""You are an expert short-form video editor clipping a long video for TikTok/Reels/Shorts.

Campaign: {campaign.get('name', '')}
Brief / what the campaign wants: {brief}

Below is a transcript slice; each line starts with its start time in seconds.
Pick up to 2 moments that would work as standalone viral clips: a strong hook in
the first 2 seconds, a payoff (funny, shocking, emotional, a hot take, a big
play/reaction), and no context needed. Each clip must be {min_len}-{max_len} seconds.
Skip the slice (return an empty list) if nothing is genuinely strong.

The "hook" is the on-screen title. It must make someone STOP scrolling: create
curiosity or tension about what happens, never just describe the clip.
  Bad (descriptive): "Warzone Nostalgia to Mom Joke"
  Good (curiosity):  "He did NOT expect this answer 💀"
No false claims or misleading clickbait: the clip must deliver what the hook promises.

Return JSON: {{"clips": [{{"start": <sec>, "end": <sec>, "score": <1-10 virality>,
"hook": "<on-screen title, max 8 words, {lang}>", "why": "<one line>"}}]}}

TRANSCRIPT:
{lines}"""
        if not first:
            time.sleep(LLM_CALL_GAP_SEC)
        first = False
        res = _call_llm(api_key, prompt) or {}
        for c in res.get("clips", []):
            try:
                c["start"], c["end"], c["score"] = float(c["start"]), float(c["end"]), float(c.get("score", 0))
                candidates.append(c)
            except (KeyError, TypeError, ValueError):
                continue
        log(f"  [LLM] window done, {len(candidates)} candidates so far")
    return candidates


def snap_and_select(candidates: list, transcript: dict, campaign: dict, count: int) -> list:
    """Snap to sentence boundaries, enforce length, drop overlaps, keep top `count`."""
    segs = transcript["segments"]
    min_len, max_len = campaign.get("clip_seconds", [20, 60])
    chosen = []
    for c in sorted(candidates, key=lambda c: -c["score"]):
        starts = [s["start"] for s in segs if s["start"] <= c["start"] + 0.5]
        ends = [s["end"] for s in segs if s["end"] >= c["end"] - 0.5]
        start = max(starts) if starts else c["start"]
        end = min(ends) if ends else c["end"]
        if end - start > max_len:
            end = start + max_len
        if end - start < min_len:
            continue
        if any(start < o["end"] and end > o["start"] for o in chosen):
            continue
        chosen.append({**c, "start": round(start, 2), "end": round(end, 2)})
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda c: c["start"])


# ── Rendering ───────────────────────────────────────────────────────────────

def _ass_time(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_text(s: str) -> str:
    # The server font has no emoji glyphs (they render as boxes), so drop them
    # from burned-in text; the post caption keeps them.
    s = re.sub(r"[\U0001F000-\U0001FFFF☀-➿️‍]", "", s)
    return re.sub(r"[{}\\]", "", s).replace("\n", " ").strip()


def apply_fixes(words: list, fixes: dict) -> list:
    """Replace mis-transcribed phrases (1-3 words, case-insensitive) in a word list.

    fixes: {"funding tips": "FundingPips", "emi": "EMI"}. Matching ignores
    punctuation; the replacement keeps the first word's start and last word's end.
    """
    if not fixes:
        return words
    norm = lambda x: re.sub(r"[^a-z0-9$£%']", "", x.lower())
    table = {tuple(k.lower().split()): v for k, v in fixes.items()}
    out, i = [], 0
    while i < len(words):
        for n in (3, 2, 1):
            key = tuple(norm(w["word"]) for w in words[i:i + n])
            if len(key) == n and key in table:
                trail = re.sub(r"^.*?([.,!?]*)$", r"\1", words[i + n - 1]["word"])
                out.append({"start": words[i]["start"], "end": words[i + n - 1]["end"],
                            "word": table[key] + trail})
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return out


def build_ass(clip: dict, words: list, campaign: dict, path: str):
    start, end = clip["start"], clip["end"]
    dur = end - start
    group = campaign.get("caption_words_per_line", 3)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,520,1
Style: Hook,DejaVu Sans,72,&H0000E5FF,&H0000E5FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,8,60,60,330,1
Style: Disc,DejaVu Sans,44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,8,60,60,120,1
Style: Pin,DejaVu Sans,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&HB4000000,-1,0,0,0,100,100,0,0,3,14,0,2,60,60,250,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    hook = clip.get("hook", "")
    if hook:
        events.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(dur)},Hook,,0,0,0,,{_ass_text(hook.upper())}")
    pinned = campaign.get("on_screen_persistent")  # e.g. a required discount code
    if pinned:
        events.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(dur)},Pin,,0,0,0,,{_ass_text(pinned)}")
    disclosure = campaign.get("on_screen_disclosure")
    if disclosure:
        events.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(min(3, dur))},Disc,,0,0,0,,{_ass_text(disclosure)}")

    clip_words = [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05 and w["word"]]
    clip_words = apply_fixes(clip_words, campaign.get("transcript_fixes"))
    for i in range(0, len(clip_words), group):
        g = clip_words[i:i + group]
        g_start = g[0]["start"] - start
        nxt = clip_words[i + group]["start"] - start if i + group < len(clip_words) else g[-1]["end"] - start
        g_end = max(nxt, g[-1]["end"] - start)
        text = " ".join(_ass_text(w["word"]).upper() for w in g)
        events.append(f"Dialogue: 0,{_ass_time(g_start)},{_ass_time(min(g_end, dur))},Cap,,0,0,0,,{text}")

    with open(path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events) + "\n")


def video_size(path: str) -> tuple:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
               "stream=width,height", "-of", "csv=p=0:s=x", path]).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


# Punch-in presets cycled on every cut: (zoom, horizontal focus 0=left..1=right)
CUT_PRESETS = [(1.0, 0.5), (1.22, 0.5), (1.12, 0.35), (1.3, 0.55), (1.08, 0.65)]


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def _foreground(src_w: int, src_h: int, dur: float, campaign: dict) -> tuple:
    """Filter chain [fgsrc] -> [fg] plus the box the foreground fills.

    layout "blur": full-width source centered over a blurred copy (16:9 sources).
    layout "fill": source cropped to fill the whole 9:16 frame (vertical sources).
    dynamic_cuts: re-frame (zoom/pan) every cut_seconds, the "active editing"
    many campaigns require instead of a static re-upload.
    """
    if campaign.get("layout", "blur") == "fill":
        box_w, box_h = W, H
        if src_w / src_h > W / H:   # wider than 9:16: crop the sides
            bh, bw = src_h, src_h * W / H
        else:                       # taller: crop top/bottom
            bw, bh = src_w, src_w * H / W
    else:
        box_w, box_h = W, _even(W * src_h / src_w)
        bw, bh = src_w, src_h
    bx, by = (src_w - bw) / 2, (src_h - bh) / 2

    def crop(z: float, xf: float) -> str:
        cw, ch = _even(bw / z), _even(bh / z)
        x = int(bx + (bw - cw) * xf)
        y = int(by + (bh - ch) / 2)
        return f"crop={cw}:{ch}:{x}:{y},scale={box_w}:{box_h},setsar=1"

    if not campaign.get("dynamic_cuts"):
        return f"[fgsrc]{crop(1.0, 0.5)}[fg]", box_w, box_h

    step = float(campaign.get("cut_seconds", 2.2))
    bounds = []
    t = 0.0
    while t < dur - 0.05:
        bounds.append((t, min(t + step, dur)))
        t += step
    n = len(bounds)
    parts = [f"[fgsrc]split={n}" + "".join(f"[c{i}]" for i in range(n))]
    for i, (a, b) in enumerate(bounds):
        z, xf = CUT_PRESETS[i % len(CUT_PRESETS)]
        parts.append(f"[c{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,{crop(z, xf)}[s{i}]")
    parts.append("".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[fg]")
    return ";".join(parts), box_w, box_h


def render_clip(source: str, clip: dict, ass_path: str, out_path: str, campaign: dict | None = None):
    """Vertical 1080x1920 render with burned-in captions (see _foreground for layouts)."""
    campaign = campaign or {}
    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    src_w, src_h = video_size(source)
    fg_chain, box_w, box_h = _foreground(src_w, src_h, clip["end"] - clip["start"], campaign)
    if box_h >= H:
        vf = f"[0:v]fps=30,setpts=PTS-STARTPTS[fgsrc];{fg_chain};[fg]ass='{ass_escaped}'[v]"
    else:
        vf = (
            f"[0:v]fps=30,setpts=PTS-STARTPTS,split=2[bg][fgsrc];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=25:2,eq=brightness=-0.08[bgb];"
            f"{fg_chain};"
            f"[bgb][fg]overlay=(W-w)/2:(H-h)/2,ass='{ass_escaped}'[v]"
        )
    run([
        "ffmpeg", "-y", "-v", "error",
        "-ss", str(clip["start"]), "-to", str(clip["end"]), "-i", source,
        "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_path,
    ], timeout=900)


def compose_caption(clip: dict, campaign: dict) -> str:
    parts = [clip.get("hook", "")]
    if campaign.get("caption_suffix"):
        parts.append(campaign["caption_suffix"])
    tags = " ".join(campaign.get("mentions", []) + campaign.get("hashtags", []))
    if tags:
        parts.append(tags)
    if campaign.get("caption_disclosure"):
        parts.append(campaign["caption_disclosure"])
    return " ".join(p for p in parts if p).strip()


# ── Main ────────────────────────────────────────────────────────────────────

def rerender(manifest_path: str, campaign: dict):
    """Re-render a manifest's clips in place, using its (possibly hand-edited) hooks."""
    with open(manifest_path) as f:
        manifest = json.load(f)
    work = manifest.get("work_dir")
    if not work:
        sys.exit("manifest has no work_dir (made by an older version); re-run the campaign instead")
    with open(os.path.join(work, "transcript.json")) as f:
        transcript = json.load(f)
    source = os.path.join(work, "source.mp4")
    for i, clip in enumerate(manifest["clips"], 1):
        ass = os.path.join(work, f"clip_{i}.ass")
        build_ass(clip, transcript["words"], campaign, ass)
        render_clip(source, clip, ass, clip["file"], campaign)
        clip["caption"] = compose_caption(clip, campaign)
        log(f"  [OK] {clip['file']} {clip.get('hook', '')}")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign", help="campaign config JSON")
    ap.add_argument("--source", help="override source URL (default: first in config)")
    ap.add_argument("--window", help="only this part of the source, e.g. 0:30:00-1:30:00")
    ap.add_argument("--count", type=int, help="clips to render (default from config)")
    ap.add_argument("--out", default=OUTPUT_ROOT)
    ap.add_argument("--rerender", metavar="MANIFEST",
                    help="re-render the clips of an existing manifest (after editing hooks "
                         "or transcript_fixes); skips download, transcription and picking")
    args = ap.parse_args()

    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        log("GROQ_API_KEY not set")
        sys.exit(1)
    with open(args.campaign) as f:
        campaign = json.load(f)
    if args.rerender:
        rerender(args.rerender, campaign)
        return

    # sources[] entries are either a URL string or {"url", "window"}; the
    # campaign's allowed-footage window is the default when --window isn't given.
    first = (campaign.get("sources") or [None])[0]
    if isinstance(first, dict):
        source_url = args.source or first.get("url")
        if not args.source and not args.window:
            args.window = first.get("window")
    else:
        source_url = args.source or first
    if not source_url:
        log("No source URL: pass --source or set sources[] in the campaign config")
        sys.exit(1)
    count = args.count or campaign.get("clips_per_run", 3)

    slug = re.sub(r"[^a-z0-9]+", "-", campaign.get("name", "campaign").lower()).strip("-")
    src_id = re.sub(r"[^A-Za-z0-9]+", "_", source_url)[-40:] + (("_" + args.window.replace(":", "")) if args.window else "")
    work = os.path.join(args.out, slug, "work", src_id)
    out_dir = os.path.join(args.out, slug, datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(work, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    log(f"[1/4] Download")
    source = download_source(source_url, work, args.window)
    log(f"[2/4] Transcribe")
    transcript = transcribe(api_key, source, work, campaign.get("source_language"))
    log(f"[3/4] Pick highlights ({len(transcript['segments'])} segments)")
    clips = snap_and_select(pick_highlights(api_key, transcript, campaign), transcript, campaign, count)
    if not clips:
        log("No usable highlights found")
        sys.exit(2)

    log(f"[4/4] Render {len(clips)} clips")
    results = []
    for i, clip in enumerate(clips, 1):
        ass = os.path.join(work, f"clip_{i}.ass")
        mp4 = os.path.join(out_dir, f"clip_{i}.mp4")
        build_ass(clip, transcript["words"], campaign, ass)
        try:
            render_clip(source, clip, ass, mp4, campaign)
        except subprocess.CalledProcessError as e:
            log(f"  [ERR] clip {i}: {e.stderr[-400:]}")
            continue
        results.append({"file": mp4, "start": clip["start"], "end": clip["end"],
                        "score": clip["score"], "hook": clip.get("hook", ""), "why": clip.get("why", ""),
                        "caption": compose_caption(clip, campaign)})
        log(f"  [OK] {mp4} ({clip['end'] - clip['start']:.0f}s, score {clip['score']:.0f}) {clip.get('hook', '')}")

    manifest = {"campaign": campaign.get("name"), "source": source_url, "window": args.window,
                "work_dir": work,
                "created": datetime.now().isoformat(timespec="seconds"), "clips": results}
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(json.dumps(manifest, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
