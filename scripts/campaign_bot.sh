#!/bin/bash
# Telegram approval-bot poller - HOST cron, every minute.
if [ -f /home/ubuntu/pipeline/.env ]; then
    set -a; . /home/ubuntu/pipeline/.env; set +a
fi
exec python3 /home/ubuntu/pipeline/scripts/campaign_bot.py poll
