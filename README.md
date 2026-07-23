# Viral Pipeline

Fully automated content engine that turns Reddit-style stories into narrated shorts with AI-generated visuals and publishes them to **TikTok**, **Instagram Reels**, and **YouTube** — twice a day, zero human input.

```
Story ➜ Narrate ➜ Generate Images ➜ Assemble ➜ Publish
```

## How It Works

| Stage | What happens | Tools |
|-------|-------------|-------|
| **Story** | Scrapes trending Reddit posts (or generates original stories when Reddit blocks) | Reddit JSON + Groq (Llama 3.3 70B) |
| **Narrate** | Voice-over narration with word timestamps for karaoke subtitles | Edge TTS |
| **Generate Images** | AI image per scene, vertical 1080x1920 | Cloudflare Workers AI (FLUX.2 klein / FLUX.1 schnell) → HuggingFace SD3 → Pollinations |
| **Assemble** | Ken Burns motion + karaoke subs into vertical shorts | `ffmpeg` |
| **Publish** | Uploads shorts to TikTok, Instagram Reels, and YouTube | TikTok API, Instagram Graph API, n8n |

The pipeline runs inside **n8n** on an Oracle Cloud ARM server, triggered on a schedule. Upload watchers run as cron jobs on the host, polling for new manifests every 5 minutes.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Oracle Cloud (ARM · Ubuntu 22.04)              │
│                                                 │
│  ┌───────────────────────────────────┐          │
│  │  Docker: n8n                      │          │
│  │  ┌─────────┐  ┌─────────────────┐ │          │
│  │  │ Schedule│──▶│story_pipeline.py│ │          │
│  │  │ 7am/4pm │  │ story→img→short │ │          │
│  │  └─────────┘  └────────┬────────┘ │          │
│  │                        │ manifest │          │
│  └────────────────────────┼──────────┘          │
│                           ▼                     │
│  ┌────────────────────────────────────────────┐  │
│  │  Cron Watchers (every 5 min)              │  │
│  │  ├── tiktok_watcher.sh ──▶ TikTok API     │  │
│  │  ├── instagram_watcher.sh ──▶ IG Graph API│  │
│  │  └── (YouTube via n8n node)               │  │
│  └────────────────────────────────────────────┘  │
│                                                 │
│  nginx ──▶ serves /shorts/ for IG video URLs    │
└─────────────────────────────────────────────────┘
```

## Quick Start

### 1. Server Setup

```bash
ssh your-server
git clone https://github.com/avarajar/viral-shorts.git /home/ubuntu/pipeline
cd /home/ubuntu/pipeline
bash setup.sh
```

### 2. Environment Variables

Create `/home/ubuntu/pipeline/.env`:

```env
# Required
GROQ_API_KEY=your_groq_key

# TikTok
TIKTOK_CLIENT_KEY=your_key
TIKTOK_CLIENT_SECRET=your_secret

# Instagram
INSTAGRAM_APP_ID=your_app_id
INSTAGRAM_APP_SECRET=your_app_secret
INSTAGRAM_ACCESS_TOKEN=your_token
INSTAGRAM_USER_ID=your_ig_user_id

# Notifications
DISCORD_WEBHOOK_URL=your_webhook
```

Image-generation credentials live in the n8n container's environment
(`/home/ubuntu/n8n-docker/docker-compose.yml` on the server), since the
pipeline runs inside n8n:

```env
CLOUDFLARE_ACCOUNT_ID=...   # Workers AI, primary provider (free 10k neurons/day)
CLOUDFLARE_API_TOKEN=...    # token template "Workers AI"
HF_TOKEN=...                # HuggingFace fallback (SD3 medium)
POLLINATIONS_API_KEY=...    # last-resort fallback (paid "pollen" balance)
```

### 3. Authenticate Platforms

```bash
# TikTok (opens auth flow, paste redirect URL)
python3 scripts/upload_tiktok.py --auth

# Instagram (needs short-lived token from Graph Explorer)
python3 scripts/upload_instagram.py --auth
```

### 4. Set Up Cron Jobs

```cron
*/5 * * * * /home/ubuntu/pipeline/scripts/tiktok_watcher.sh >> /home/ubuntu/pipeline/tiktok_upload.log 2>&1
*/5 * * * * /home/ubuntu/pipeline/scripts/instagram_watcher.sh >> /home/ubuntu/pipeline/instagram_upload.log 2>&1
```

### 5. Run the Pipeline

```bash
# Manual test run (inside the n8n container, where the env vars live)
docker exec n8n python3 /pipeline/scripts/story_pipeline.py

# Or let n8n handle it on schedule
```

## Project Structure

```
scripts/
├── story_pipeline.py        # Orchestrator — story → narration → AI images → shorts
├── generate_story.py        # Reddit scraping + Groq story adaptation
├── narrate_story.py         # Edge TTS narration with word timestamps
├── fetch_visuals.py         # AI images (Cloudflare → HF → Pollinations) + Ken Burns
├── assemble_video.py        # FFmpeg assembly with karaoke subtitles
├── pipeline.py              # Legacy orchestrator (clip-based pipeline)
├── scrape_viral.py          # Scrapes trending content sources
├── download_clips.py        # Downloads raw video clips
├── generate_narration.py    # AI script generation + TTS voice-over
├── compile_video.py         # FFmpeg compilation + shorts generation
├── upload_tiktok.py         # TikTok Content Posting API
├── upload_instagram.py      # Instagram Graph API (Reels)
├── tiktok_watcher.sh        # Cron: polls for TikTok manifests
├── instagram_watcher.sh     # Cron: polls for Instagram manifests
└── cleanup.sh               # Cleanup temp files

n8n/
├── Dockerfile               # Custom n8n image with ffmpeg + python
├── docker-compose.override.yml
└── workflow.json            # n8n workflow definition

config/
└── nginx-shorts.conf        # Serves video files for Instagram API

docs/
└── index.html               # GitHub Pages (TikTok OAuth redirect)
```

## Deployment

Pushes to `main` auto-deploy via GitHub Actions — only changed components get deployed:

| Changed path | Action |
|-------------|--------|
| `scripts/*` | SCP scripts to server |
| `config/*` | Deploy nginx config + reload |
| `n8n/Dockerfile` | Rebuild Docker container |
| `n8n/workflow.json` | Import workflow + restart n8n |

Manual deploy:
```bash
scp scripts/*.py scripts/*.sh your-server:/home/ubuntu/pipeline/scripts/
```

## Schedule

| Time (Colombia) | Action |
|-----------------|--------|
| 7:00 AM | n8n generates 3 shorts |
| 4:00 PM | n8n generates 3 shorts |
| Every 5 min | Watchers check for new uploads |

**Output:** 6 shorts/day across TikTok, Instagram, and YouTube.

## Token Management

- **TikTok:** Access tokens auto-refresh 5 minutes before expiry. Refresh tokens last ~1 year. If both expire, run `--auth` again.
- **Instagram:** Long-lived tokens last 60 days. Refresh with `python3 upload_instagram.py --refresh`.
- **YouTube:** Managed by n8n's built-in OAuth2 node.

## License

Private project.
