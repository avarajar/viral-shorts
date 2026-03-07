# Viral Pipeline

Fully automated content engine that scrapes trending videos, generates AI narration, compiles short-form content, and publishes to **TikTok**, **Instagram Reels**, and **YouTube** — twice a day, zero human input.

```
Scrape ➜ Download ➜ Narrate ➜ Compile ➜ Publish
```

## How It Works

| Stage | What happens | Tools |
|-------|-------------|-------|
| **Scrape** | Finds trending clips from YouTube, Reddit, and other sources | `yt-dlp` |
| **Download** | Pulls the raw video clips | `yt-dlp` |
| **Narrate** | Generates a script and voice-over narration | Groq (Llama 3.3 70B) + Edge TTS |
| **Compile** | Assembles clips with narration, subtitles, transitions, and music into a long-form video + vertical shorts | `ffmpeg` |
| **Publish** | Uploads shorts to TikTok, Instagram Reels, and YouTube | TikTok API, Instagram Graph API, n8n |

The pipeline runs inside **n8n** on an Oracle Cloud ARM server, triggered on a schedule. Upload watchers run as cron jobs on the host, polling for new manifests every 5 minutes.

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Oracle Cloud (ARM · Ubuntu 22.04)              │
│                                                 │
│  ┌───────────────────────────────────┐          │
│  │  Docker: n8n                      │          │
│  │  ┌─────────┐    ┌──────────────┐  │          │
│  │  │ Schedule │───▶│  pipeline.py │  │          │
│  │  │ 7am/4pm │    │  (5 stages)  │  │          │
│  │  └─────────┘    └──────┬───────┘  │          │
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
# Manual test run
cd /home/ubuntu/pipeline/scripts
source ../venv/bin/activate
python3 pipeline.py

# Or let n8n handle it on schedule
```

## Project Structure

```
scripts/
├── pipeline.py              # Master orchestrator (5-stage pipeline)
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
