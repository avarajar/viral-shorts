#!/bin/bash
# Instagram Reels Upload Watcher - runs on HOST via cron
# Checks for instagram_manifest.json and uploads Reels via Graph API
# Cron: */5 * * * * /home/ubuntu/pipeline/scripts/instagram_watcher.sh >> /home/ubuntu/pipeline/instagram_upload.log 2>&1

MANIFEST="/home/ubuntu/pipeline/output/instagram_manifest.json"
LOCK="/home/ubuntu/pipeline/output/.instagram_uploading"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

export PATH="/home/ubuntu/.local/bin:$PATH"

# Load env vars
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
echo "$LOG_PREFIX Found Instagram manifest, starting upload..."

# Run upload via Instagram Graph API
RESULT=$(python3 /home/ubuntu/pipeline/scripts/upload_instagram.py --manifest "$MANIFEST" 2>>/home/ubuntu/pipeline/instagram_upload.log)
EXIT_CODE=$?

echo "$LOG_PREFIX Upload result (exit=$EXIT_CODE): $RESULT"

# Send Discord notification
if [ -n "$DISCORD_WEBHOOK_URL" ]; then
    if [ $EXIT_CODE -eq 0 ]; then
        UPLOADED=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f\"{d.get('uploaded',0)}/{d.get('total',0)}\")" 2>/dev/null || echo "?/?")
        MSG="📸 Instagram Reels Upload OK!\n\nReels subidos: $UPLOADED"
    else
        MSG="📸 Instagram Reels Upload FALLO\n\nRevisa logs:\ncat /home/ubuntu/pipeline/instagram_upload.log"
    fi

    curl -s -X POST "$DISCORD_WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$MSG\"}" > /dev/null 2>&1
fi

# Remove manifest (processed) and lock
rm -f "$MANIFEST" "$LOCK"
echo "$LOG_PREFIX Done"
