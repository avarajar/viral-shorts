#!/bin/bash
# TikTok Upload Watcher - runs on HOST via cron
# Checks for tiktok_manifest.json and uploads shorts to TikTok via official API
# Cron: */5 * * * * /home/ubuntu/pipeline/scripts/tiktok_watcher.sh >> /home/ubuntu/pipeline/tiktok_upload.log 2>&1

MANIFEST="/home/ubuntu/pipeline/output/tiktok_manifest.json"
LOCK="/home/ubuntu/pipeline/output/.tiktok_uploading"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

export PATH="/home/ubuntu/.local/bin:$PATH"

# Load env vars (TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, DISCORD_WEBHOOK_URL)
if [ -f /home/ubuntu/pipeline/.env ]; then
    export $(grep -v '^#' /home/ubuntu/pipeline/.env | xargs)
fi

cd /home/ubuntu/pipeline/scripts

# Exit if no manifest pending
if [ ! -f "$MANIFEST" ]; then
    exit 0
fi

# Exit if already uploading
if [ -f "$LOCK" ]; then
    echo "$LOG_PREFIX Already uploading, skipping"
    exit 0
fi

# Create lock
touch "$LOCK"
echo "$LOG_PREFIX Found TikTok manifest, starting upload..."

# Run upload via official TikTok API (no browser needed)
RESULT=$(python3 /home/ubuntu/pipeline/scripts/upload_tiktok.py --manifest "$MANIFEST" 2>>/home/ubuntu/pipeline/tiktok_upload.log)
EXIT_CODE=$?

echo "$LOG_PREFIX Upload result (exit=$EXIT_CODE): $RESULT"

# Send Discord notification
if [ -n "$DISCORD_WEBHOOK_URL" ]; then
    if [ $EXIT_CODE -eq 0 ]; then
        UPLOADED=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('uploaded',0)}/{d.get('total',0)}\")" 2>/dev/null || echo "?/?")
        MSG="TikTok Upload OK!\n\nShorts subidos: $UPLOADED"
    else
        MSG="TikTok Upload FALLO\n\nRevisa logs:\ncat /home/ubuntu/pipeline/tiktok_upload.log"
    fi

    curl -s -X POST "$DISCORD_WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$MSG\"}" > /dev/null 2>&1
fi

# Remove manifest (processed) and lock
rm -f "$MANIFEST" "$LOCK"
echo "$LOG_PREFIX Done"
