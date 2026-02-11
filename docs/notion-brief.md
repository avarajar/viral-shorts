# Viral Shorts Pipeline

Automated system that generates and publishes viral YouTube Shorts from trending Reddit stories. Runs 24/7 on a cloud server with zero manual intervention and zero cost.

**YouTube Channel:** https://www.youtube.com/channel/UCMvzfQUpxbx9SvztFdGJixg

---

## How It Works

Trending Reddit posts are scraped, rewritten into dramatic scripts by AI, narrated with natural voice, illustrated with AI-generated cinematic images, and assembled into professional vertical shorts — all automatically.

### Pipeline Flow

> Reddit Scraping → AI Script Adaptation → Voice Narration → AI Image Generation → Video Assembly → YouTube Upload → Discord Notification

| Stage | Tool | Description |
|---|---|---|
| Story Scraping | Reddit JSON API | Scrapes top trending posts from 8 subreddits (AITA, ProRevenge, TIFU, etc.), sorted by engagement score |
| Script Adaptation | Groq AI (Llama 3.3 70B) | Rewrites posts into 120-150 word dramatic scripts with hooks, tension, and twist endings. Generates 4 cinematic scene descriptions per story |
| Voice Narration | Microsoft Edge TTS | Generates natural voice narration + word-level subtitle timing (VTT format) |
| Image Generation | HuggingFace FLUX + Pollinations AI | Creates 4 photorealistic cinematic scene images per short (1080x1920). Ken Burns animation effects (zoom, pan) for visual motion |
| Video Assembly | FFmpeg | Composes final vertical video: multi-image animated background + audio + karaoke-style word-by-word subtitles + hook text overlay |
| Upload | YouTube Data API v3 | Auto-uploads with optimized title, description, hashtags, and tags |
| Notification | Discord Webhook | Sends success/failure alerts with video link |

---

## Content Strategy

- **Niche:** Reddit storytime — AITA, revenge, plot twists, family drama
- **Format:** Vertical 1080x1920, 30-55 seconds per short
- **Narrative Style:** First person, dramatic hook opening, casual tone, shocking twist ending
- **Visuals:** Cinematic photography scenes with slow Ken Burns motion (zoom in/out, pan left/right)
- **Subtitles:** Word-by-word karaoke highlight with shadow effect, max 3 words per group, dynamic font sizing
- **Hashtags:** #shorts #storytime #reddit #aita #revenge #plottwist #drama #viral #redditstories

---

## Distribution

| Platform | Status | Method |
|---|---|---|
| YouTube | Active | Auto-upload via OAuth2 — public, with description, hashtags, and tags |
| TikTok | Pending | Official Content Posting API — awaiting app review approval |
| Instagram Reels | Planned | Graph API (requires Business account) |
| Discord | Active | Webhook notifications on every run (success + failure) |

---

## Infrastructure

| Component | Details |
|---|---|
| Server | Oracle Cloud Free Tier — ARM (aarch64), 1 OCPU, 6GB RAM, 45GB disk |
| OS | Ubuntu 22.04 |
| Orchestration | n8n (self-hosted in Docker) |
| Schedule | Twice daily: 7:00 AM and 4:00 PM (Colombia time) |
| Cost | $0/month |

---

## AI Services

| Service | Purpose | Tier |
|---|---|---|
| Groq API | Story generation and adaptation (Llama 3.3 70B) | Free |
| HuggingFace Inference | Primary image generation (FLUX.1 Schnell) — handles faces well | Free (resets monthly) |
| Pollinations AI | Fallback image generation (Flux model) — environmental/atmospheric scenes | Free + API key |
| Microsoft Edge TTS | Text-to-speech narration (Andrew Multilingual voice) | Free |

---

## Error Handling

- **Groq API:** 3 retry attempts with 10-second delay between each
- **Image Generation:** HuggingFace first, automatic Pollinations fallback if payment required (402)
- **Pollinations:** Placeholder/spam image detection (rate limit, moved notices) — auto-discards and retries
- **Face Quality:** HuggingFace handles portraits/faces, Pollinations uses environmental scenes (no faces) to avoid deformation
- **Pipeline Failure:** Discord error notification with node name and error message
- **Cleanup:** Automatic temp file cleanup after every run (success or failure)

---

## Architecture

```
                    +------------------+
                    |   n8n Scheduler  |
                    |  (7AM + 4PM)     |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Reddit Scraping |
                    |  (8 subreddits)  |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Groq AI Adapt   |
                    |  (Llama 3.3 70B) |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
    +---------v----------+       +----------v---------+
    |  Edge TTS Narrate  |       |  AI Image Gen x4   |
    |  (audio + subs)    |       |  (HF FLUX/Pollin.) |
    +----------+---------+       +----------+----------+
               |                            |
               +-------------+--------------+
                             |
                    +--------v---------+
                    |  FFmpeg Assembly  |
                    |  (video + subs)  |
                    +--------+---------+
                             |
              +--------------+--------------+
              |              |              |
    +---------v--+   +------v------+  +----v-------+
    |  YouTube   |   |   TikTok   |  |  Discord   |
    |  Upload    |   |  (pending) |  |  Notify    |
    +------------+   +------------+  +------------+
```

---

## Key Metrics

| Metric | Value |
|---|---|
| Pipeline run time | ~10 minutes |
| Shorts per run | 3 |
| Runs per day | 2 |
| Shorts per day | 6 |
| Images per short | 4 (AI-generated) |
| Short duration | 30-55 seconds |
| Video resolution | 1080x1920 (vertical) |
| Monthly cost | $0 |

---

## Tech Stack

`Python` `FFmpeg` `n8n` `Docker` `Groq API` `HuggingFace` `Pollinations AI` `Edge TTS` `YouTube Data API` `TikTok Content Posting API` `Oracle Cloud` `Ubuntu ARM64`
