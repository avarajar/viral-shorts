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
- Or: `ssh viral-pipeline` then git pull from repo
