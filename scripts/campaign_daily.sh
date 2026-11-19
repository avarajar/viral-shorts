#!/bin/bash
# Daily clipping-campaign run - HOST cron.
# Renders the next unused clip inside the n8n container (it has GROQ_API_KEY),
# then sends it to Telegram for approval (campaign_bot.py, on the host).
# Usage: campaign_daily.sh <campaign-config-name> [count]   e.g. campaign_daily.sh fundingpips 1

CAMPAIGN="${1:?campaign name, e.g. fundingpips}"
COUNT="${2:-1}"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')] [$CAMPAIGN]"

if [ -f /home/ubuntu/pipeline/.env ]; then
    set -a; . /home/ubuntu/pipeline/.env; set +a
fi

CONFIG="/pipeline/config/campaigns/$CAMPAIGN.json"
echo "$LOG_PREFIX generating $COUNT clip(s)"
OUT=$(docker exec n8n python3 /pipeline/scripts/clip_campaign.py "$CONFIG" --daily --count "$COUNT")
if [ $? -ne 0 ] || [ -z "$OUT" ]; then
    echo "$LOG_PREFIX generation failed"
    python3 - "$CAMPAIGN" <<'PY'
import json, os, sys, urllib.request
tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
if tok and chat:
    body = json.dumps({"chat_id": chat, "text": f"⚠️ No pude generar el clip de hoy ({sys.argv[1]}). Revisa campaigns.log en el servidor."}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=body, headers={"Content-Type": "application/json"}), timeout=30)
PY
    exit 1
fi

MANIFEST=$(echo "$OUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['out_dir'] + '/manifest.json')")
echo "$LOG_PREFIX manifest $MANIFEST"
python3 /home/ubuntu/pipeline/scripts/campaign_bot.py notify "$MANIFEST" "$CONFIG"
