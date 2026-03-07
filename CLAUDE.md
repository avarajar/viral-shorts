# Viral Pipeline

> Automated short-form content engine: scrape, narrate, compile, publish.

## Server

| | |
|---|---|
| **SSH** | `viral-pipeline` (alias) or `ssh ubuntu@149.130.186.177` |
| **Platform** | Oracle Cloud Free Tier, ARM (aarch64), Ubuntu 22.04 |
| **Pipeline** | `/home/ubuntu/pipeline/` |
| **Scripts** | `/home/ubuntu/pipeline/scripts/` |
| **Env file** | `/home/ubuntu/pipeline/.env` |
| **n8n** | Docker container, port 5678 |

## Pipeline Flow

```
n8n (Docker, schedule) ──▶ pipeline.py ──▶ manifest.json
                                              │
Cron watchers (host, */5) ────────────────────┘
  ├── tiktok_watcher.sh ──▶ TikTok Content Posting API
  ├── instagram_watcher.sh ──▶ Instagram Graph API v21.0
  └── YouTube ──▶ via n8n OAuth2 node (no watcher)
```

**Schedule:** 7:00 AM + 4:00 PM Colombia time, 3 shorts per run (6/day).

## Key Scripts

| Script | Purpose |
|--------|---------|
| `pipeline.py` | Master orchestrator — scrape, download, narrate, compile, output manifest |
| `scrape_viral.py` | Finds trending clips (YouTube, Reddit via yt-dlp) |
| `download_clips.py` | Downloads raw video clips |
| `generate_narration.py` | Groq API (Llama 3.3 70B) for script + Edge TTS for voice |
| `compile_video.py` | FFmpeg assembly — long video + vertical shorts |
| `upload_tiktok.py` | TikTok upload + token management (`--auth`, `--refresh`) |
| `upload_instagram.py` | Instagram Reels upload (`--auth`, `--refresh`) |
| `tiktok_watcher.sh` | Cron watcher — polls for `tiktok_manifest.json` |
| `instagram_watcher.sh` | Cron watcher — polls for `instagram_manifest.json` |

## TikTok Integration

- **Production Client Key:** `awxtj46z4b0gfvsg`
- **Production Client Secret:** `adyCTCYdnm7BeG8lIcOqia01IqeHpTxQ`
- **Sandbox Client Key:** `sbawxa5zsa7ap3bt7l`
- **Redirect URI:** `https://avarajar.github.io/viral-shorts/`
- **Tokens file:** `/home/ubuntu/pipeline/scripts/tiktok_tokens.json`
- **Runs via cron on the host, NOT inside Docker**
- Access tokens auto-refresh 5 min before expiry; 401s trigger automatic retry with refresh
- First-time auth: `python3 upload_tiktok.py --auth`

## Instagram Reels Integration

- **API:** Instagram Graph API v21.0 (Content Publishing)
- **Tokens file:** `/home/ubuntu/pipeline/scripts/instagram_tokens.json`
- **Video serving:** nginx serves `/pipeline/output/shorts/` at `http://149.130.186.177/shorts/`
- **Nginx config:** `config/nginx-shorts.conf` → `/etc/nginx/sites-enabled/`
- **Runs via cron on the host, NOT inside Docker**
- Long-lived tokens last 60 days; refresh with `--refresh`
- First-time auth: `python3 upload_instagram.py --auth` (needs short-lived token from Graph Explorer)
- Env vars: `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`, `INSTAGRAM_VIDEO_BASE_URL`

## YouTube

- **Channel:** `UCMvzfQUpxbx9SvztFdGJixg`
- **Upload:** Handled by n8n YouTube node (OAuth2 managed inside n8n)

## GitHub & Deploy

- **Repo:** https://github.com/avarajar/viral-shorts
- **GitHub Pages:** https://avarajar.github.io/viral-shorts/ (TikTok OAuth redirect page)
- **CI/CD:** GitHub Actions auto-deploys on push to `main` (only changed components)

### Manual Deploy

```bash
# Scripts
scp scripts/*.py scripts/*.sh viral-pipeline:/home/ubuntu/pipeline/scripts/

# Nginx
scp config/nginx-shorts.conf viral-pipeline:/tmp/ && \
  ssh viral-pipeline "sudo cp /tmp/nginx-shorts.conf /etc/nginx/sites-enabled/shorts.conf && sudo nginx -t && sudo systemctl reload nginx"
```

## Conventions

- All Python scripts use only stdlib (`urllib`, `json`, `subprocess`) — no `requests` or heavy deps
- FFmpeg and yt-dlp are the external workhorses
- AI: Groq free tier with Llama 3.3 70B for script generation
- TTS: Microsoft Edge TTS (free, no API key needed)
- Docker paths start with `/pipeline/` — map to `/home/ubuntu/pipeline/` on host
- Token files (`.json`) are gitignored — never commit secrets
- Logs: `tiktok_upload.log`, `instagram_upload.log` in pipeline root
