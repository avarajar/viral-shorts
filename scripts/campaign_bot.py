#!/usr/bin/env python3
"""
Telegram approval bot for clipping-campaign clips (runs on the HOST via cron).

    notify MANIFEST CAMPAIGN.json   send each clip as a video with Approve/Discard buttons
    poll                            handle button presses (cron, every minute)
    chat-id                         print the chat ids that messaged the bot (setup)

On Approve the clip is posted to TikTok with the campaign's exact caption, and
a follow-up message gives the post link plus the Content Rewards deadline:
the link must be submitted within 30 minutes of posting, and the marketplace
has no submission API, so that last step stays manual.

Env (from /home/ubuntu/pipeline/.env): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET.
"""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.dirname(SCRIPTS)
# Not under output/campaigns: that dir is created by the n8n container and the
# host user can't write there.
STATE_FILE = os.path.join(PIPELINE, "campaign_bot_state.json")
LOCK_FILE = os.path.join(PIPELINE, ".campaign_bot.lock")
SUBMIT_WINDOW_MIN = 30
COLOMBIA = timezone(timedelta(hours=-5))

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


def host_path(path: str) -> str:
    """Container paths (/pipeline/...) -> host paths (/home/ubuntu/pipeline/...)."""
    return os.path.join(PIPELINE, path[len("/pipeline/"):]) if path.startswith("/pipeline/") else path


# ── Telegram API ────────────────────────────────────────────────────────────

def tg(method: str, params: dict | None = None, files: dict | None = None, timeout: int = 60) -> dict:
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in (params or {}).items():
            v = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, path in files.items():
            with open(path, "rb") as f:
                data = f.read()
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; '
                     f'filename="{os.path.basename(path)}"\r\nContent-Type: video/mp4\r\n\r\n').encode()
            body += data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    else:
        body = json.dumps(params or {}).encode()
        headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        log(f"Telegram {method} HTTP {e.code}: {detail}")
        return {"ok": False, "description": detail}


# ── State ───────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"offset": 0, "clips": {}}


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)


# ── Commands ────────────────────────────────────────────────────────────────

def notify(manifest_path: str, campaign_path: str):
    with open(host_path(manifest_path)) as f:
        manifest = json.load(f)
    state = load_state()
    for i, clip in enumerate(manifest["clips"]):
        cid = hashlib.sha1(f"{clip['file']}|{clip['start']}".encode()).hexdigest()[:10]
        if cid in state["clips"]:
            log(f"clip {cid} already sent, skipping")
            continue
        dur = clip["end"] - clip["start"]
        text = (f"🎬 *{manifest.get('campaign', 'Clip')}* · {dur:.0f}s\n"
                f"Hook: {clip.get('hook', '')}\n\n"
                f"Caption:\n`{clip['caption']}`\n\n"
                f"Si lo apruebas se publica YA en TikTok, y tienes {SUBMIT_WINDOW_MIN} min "
                f"para enviar el link en Content Rewards.")
        buttons = {"inline_keyboard": [[{"text": "✅ Aprobar y publicar", "callback_data": f"ok|{cid}"},
                                        {"text": "❌ Descartar", "callback_data": f"no|{cid}"}]]}
        res = tg("sendVideo", {"chat_id": CHAT_ID, "caption": text, "parse_mode": "Markdown",
                               "supports_streaming": "true", "reply_markup": buttons},
                 files={"video": host_path(clip["file"])}, timeout=300)
        if not res.get("ok"):
            sys.exit(f"sendVideo failed: {res.get('description')}")
        state["clips"][cid] = {"manifest": manifest_path, "index": i, "campaign": campaign_path,
                               "status": "pending", "message_id": res["result"]["message_id"],
                               "sent_at": time.time()}
        save_state(state)
        log(f"sent clip {cid}: {clip.get('hook', '')}")


def _post_tiktok(entry: dict) -> dict:
    with open(host_path(entry["manifest"])) as f:
        clip = json.load(f)["clips"][entry["index"]]
    with open(host_path(entry["campaign"])) as f:
        campaign = json.load(f)
    tt = campaign.get("tiktok", {})
    env = dict(os.environ)
    if tt.get("tokens_file"):
        env["TIKTOK_TOKENS_FILE"] = os.path.join(SCRIPTS, tt["tokens_file"])
    cmd = [sys.executable, os.path.join(SCRIPTS, "upload_tiktok.py"), "--post",
           host_path(clip["file"]), clip["caption"]]
    if tt.get("is_aigc"):
        cmd.append("--aigc")
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {"success": False, "status": "ERROR", "reason": (proc.stderr or proc.stdout)[-500:]}
    result["submit_url"] = campaign.get("campaign_url", "https://contentrewards.com/c/campaigns")
    return result


def handle_callback(cb: dict, state: dict):
    action, _, cid = cb.get("data", "").partition("|")
    entry = state["clips"].get(cid)
    chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
    if chat != str(CHAT_ID) or not entry:
        tg("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "Clip desconocido"})
        return
    if entry["status"] != "pending":
        tg("answerCallbackQuery", {"callback_query_id": cb["id"], "text": f"Ya está: {entry['status']}"})
        return
    no_buttons = {"chat_id": CHAT_ID, "message_id": entry["message_id"],
                  "reply_markup": {"inline_keyboard": []}}

    if action == "no":
        entry["status"] = "discarded"
        save_state(state)
        tg("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "Descartado"})
        tg("editMessageReplyMarkup", no_buttons)
        tg("sendMessage", {"chat_id": CHAT_ID, "reply_to_message_id": entry["message_id"],
                           "text": "❌ Descartado. No se publicará."})
        return

    entry["status"] = "posting"
    save_state(state)
    tg("answerCallbackQuery", {"callback_query_id": cb["id"], "text": "Publicando en TikTok…"})
    tg("editMessageReplyMarkup", no_buttons)
    log(f"posting clip {cid}")
    result = _post_tiktok(entry)

    if result.get("success"):
        posted = datetime.now(COLOMBIA)
        deadline = posted + timedelta(minutes=SUBMIT_WINDOW_MIN)
        user = result.get("username", "")
        ids = result.get("post_ids") or []
        if ids and user:
            link = f"https://www.tiktok.com/@{user}/video/{ids[0]}"
        else:
            link = f"(abre https://www.tiktok.com/@{user} y copia el link del video más reciente)"
        entry.update(status="posted", posted_at=time.time(), tiktok_link=link,
                     privacy=result.get("privacy"))
        warn = ""
        if result.get("privacy") != "PUBLIC_TO_EVERYONE":
            warn = "\n⚠️ Se publicó como PRIVADO (la cuenta aún no permite publicar público por API). Así no suma vistas."
        tg("sendMessage", {"chat_id": CHAT_ID, "reply_to_message_id": entry["message_id"],
                           "disable_web_page_preview": True,
                           "text": (f"✅ Publicado en TikTok a las {posted:%H:%M}.\n"
                                    f"⏰ Envíalo antes de las {deadline:%H:%M} (hora Colombia):\n\n"
                                    f"1. Copia: {link}\n"
                                    f"2. Abre {result['submit_url']} → Submit clip → pega.{warn}")})
    else:
        entry.update(status="failed", error=str(result.get("reason") or result.get("status")))
        tg("sendMessage", {"chat_id": CHAT_ID, "reply_to_message_id": entry["message_id"],
                           "text": f"⚠️ Falló la publicación en TikTok: {entry['error'][:300]}\n"
                                   f"No se publicó nada."})
    save_state(state)


def poll():
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # a previous poll is still posting
        state = load_state()
        res = tg("getUpdates", {"offset": state.get("offset", 0), "timeout": 0,
                                "allowed_updates": ["callback_query", "message"]})
        for upd in res.get("result", []):
            state["offset"] = upd["update_id"] + 1
            save_state(state)
            if "callback_query" in upd:
                handle_callback(upd["callback_query"], state)
            elif "message" in upd and str(upd["message"]["chat"]["id"]) == str(CHAT_ID):
                tg("sendMessage", {"chat_id": CHAT_ID,
                                   "text": "👋 Aquí estoy. Los clips nuevos llegan cada día a las 8:00 AM."})


def chat_ids():
    res = tg("getUpdates", {"timeout": 0})
    seen = {}
    for upd in res.get("result", []):
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        if chat:
            seen[chat["id"]] = chat.get("username") or chat.get("first_name", "")
    if not seen:
        print("No messages yet: send any message to the bot, then run this again.")
    for cid, name in seen.items():
        print(f"{cid}\t{name}")


if __name__ == "__main__":
    if not TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN not set")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "chat-id":
        chat_ids()
    elif not CHAT_ID:
        sys.exit("TELEGRAM_CHAT_ID not set (run: campaign_bot.py chat-id)")
    elif cmd == "notify" and len(sys.argv) == 4:
        notify(sys.argv[2], sys.argv[3])
    elif cmd == "poll":
        poll()
    else:
        sys.exit(__doc__)
