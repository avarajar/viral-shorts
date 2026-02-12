# Viral Pipeline - Project Context

## Server
- **Host:** `viral-pipeline` (SSH alias) or `ssh ubuntu@149.130.186.177`
- **Platform:** Oracle Cloud Free Tier, ARM (aarch64), Ubuntu 22.04
- **Pipeline path:** `/home/ubuntu/pipeline/`
- **Scripts:** `/home/ubuntu/pipeline/scripts/`
- **n8n:** Docker container, ports 5678
- **Env vars:** `/home/ubuntu/pipeline/.env`

## TikTok Integration
- **Production Client Key:** `awxtj46z4b0gfvsg`
- **Production Client Secret:** `adyCTCYdnm7BeG8lIcOqia01IqeHpTxQ`
- **Sandbox Client Key:** `sbawxa5zsa7ap3bt7l`
- **Redirect URI:** `https://avarajar.github.io/viral-shorts/`
- **TikTok upload:** Runs via cron (`tiktok_watcher.sh`) every 5 min on host, NOT inside Docker
- **Tokens file:** `/home/ubuntu/pipeline/scripts/tiktok_tokens.json`

## Instagram Reels Integration
- **Upload:** Runs via cron (`instagram_watcher.sh`) every 5 min on host, NOT inside Docker
- **Tokens file:** `/home/ubuntu/pipeline/scripts/instagram_tokens.json`
- **API:** Instagram Graph API v21.0 (Content Publishing)
- **Video serving:** nginx serves `/pipeline/output/shorts/` at `http://149.130.186.177/shorts/`
- **Nginx config:** `config/nginx-shorts.conf` → deploy to `/etc/nginx/sites-enabled/`
- **Env vars needed:**
  - `INSTAGRAM_APP_ID` — Facebook App ID
  - `INSTAGRAM_APP_SECRET` — Facebook App Secret
  - `INSTAGRAM_ACCESS_TOKEN` — Long-lived token (60 days, refresh with `--refresh`)
  - `INSTAGRAM_USER_ID` — IG Business account ID (obtained during `--auth`)
  - `INSTAGRAM_VIDEO_BASE_URL` — defaults to `http://149.130.186.177/shorts`
- **First-time auth:** `python3 upload_instagram.py --auth` (needs short-lived token from Graph Explorer)
- **Cron:** `*/5 * * * * /home/ubuntu/pipeline/scripts/instagram_watcher.sh >> /home/ubuntu/pipeline/instagram_upload.log 2>&1`

## GitHub
- **Repo:** https://github.com/avarajar/viral-shorts
- **GitHub Pages:** https://avarajar.github.io/viral-shorts/

## YouTube
- **Channel:** https://www.youtube.com/channel/UCMvzfQUpxbx9SvztFdGJixg
- **Upload:** Via n8n YouTube node (OAuth2 inside n8n)

## Schedule
- n8n runs pipeline twice daily: 7:00 AM and 4:00 PM (Colombia time)
- Generates 3 shorts per run (6 per day)

## Deploy
- To deploy code changes to server: `scp scripts/*.py viral-pipeline:/home/ubuntu/pipeline/scripts/`
- Deploy shell scripts: `scp scripts/*.sh viral-pipeline:/home/ubuntu/pipeline/scripts/`
- Deploy nginx config: `scp config/nginx-shorts.conf viral-pipeline:/tmp/ && ssh viral-pipeline "sudo cp /tmp/nginx-shorts.conf /etc/nginx/sites-enabled/shorts.conf && sudo nginx -t && sudo systemctl reload nginx"`
- Or: `ssh viral-pipeline` then git pull from repo
