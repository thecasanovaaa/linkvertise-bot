import threading
import re
import secrets
import requests
import os

from flask import Flask
from telebot import TeleBot

# ==================================================
# CONFIG (ENV VARS – SAFE FOR GITHUB)
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID"))
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))

RENTRY_CSRF_TOKEN = os.getenv("RENTRY_CSRF_TOKEN")
LINKVERTISE_TAG_ID = os.getenv("LINKVERTISE_TAG_ID")

DISCORD_WEBHOOK_1 = os.getenv("DISCORD_WEBHOOK_1")
DISCORD_WEBHOOK_2 = os.getenv("DISCORD_WEBHOOK_2")

# ==================================================
# TELEGRAM BOT (NO GLOBAL HTML PARSE MODE)
# ==================================================

bot = TeleBot(BOT_TOKEN)
print("✅ Telegram bot started")

# ==================================================
# FLASK KEEP-ALIVE (RENDER / UPTIMEROBOT)
# ==================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "alive"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# ==================================================
# ADMIN CHECK
# ==================================================

def is_admin(message):
    return message.from_user and message.from_user.id == ADMIN_USER_ID

# ==================================================
# RENTRY (SAFE + TIMEOUT)
# ==================================================

def create_rentry_paste(content: str):
    try:
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://rentry.co/",
            "X-CSRFToken": RENTRY_CSRF_TOKEN
        })

        payload = {
            "text": content,
            "edit_code": secrets.token_hex(8)
        }

        r = session.post(
            "https://rentry.co/api/new",
            data=payload,
            timeout=15
        )

        r.raise_for_status()
        data = r.json()

        if "url" not in data:
            raise Exception(f"Invalid response: {data}")

        return data["url"]

    except requests.exceptions.RequestException as e:
        raise Exception(f"Rentry failed: {e}")

# ==================================================
# LINKVERTISE
# ==================================================

def linkvertise_lock(url: str) -> str:
    return f"https://linkvertise.com/{LINKVERTISE_TAG_ID}?r={requests.utils.quote(url)}"

# ==================================================
# DISCORD
# ==================================================

def post_to_discord(webhook_url, image_url, name, link):
    payload = {
        "content": f"{name}\n{link}",
        "embeds": [{"image": {"url": image_url}}]
    }
    requests.post(webhook_url, json=payload, timeout=10)

# ==================================================
# TELEGRAM CHANNEL
# ==================================================

def post_to_telegram_channel(file_id, name, link):
    bot.send_photo(
        TELEGRAM_CHANNEL_ID,
        file_id,
        caption=f"{name}\n\n{link}"
    )

# ==================================================
# PIPELINE
# ==================================================

def process_pipeline(photo_file_id, name, mega_link):
    print("🚀 Pipeline started")

    rentry1 = create_rentry_paste(
        f"📦 {name}\n\n⬇️ Download:\n{mega_link}"
    )

    lv1 = linkvertise_lock(rentry1)

    rentry2 = create_rentry_paste(
        f"📦 {name}\n\n⬇️ Continue:\n{lv1}"
    )

    lv2 = linkvertise_lock(rentry2)

    file_info = bot.get_file(photo_file_id)
    image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

    post_to_discord(DISCORD_WEBHOOK_1, image_url, name, lv2)
    post_to_discord(DISCORD_WEBHOOK_2, image_url, name, lv2)
    post_to_telegram_channel(photo_file_id, name, lv2)

# ==================================================
# SINGLE MESSAGE HANDLER (ADMIN ONLY)
# ==================================================

@bot.message_handler(content_types=["photo"])
def handle_message(message):
    if not is_admin(message):
        return  # silently ignore non-admin users

    print("📩 Admin message received")

    photo_file_id = message.photo[-1].file_id
    text = message.caption or message.text

    if not text:
        bot.reply_to(message, "Send image with name and link")
        return

    link_match = re.search(r"https?://\S+", text)
    if not link_match:
        bot.reply_to(message, "No link found")
        return

    mega_link = link_match.group(0)
    name = text.replace(mega_link, "").strip()

    if not name:
        bot.reply_to(message, "Name missing")
        return

    bot.reply_to(message, "Processing...")

    try:
        process_pipeline(photo_file_id, name, mega_link)
        bot.reply_to(message, "Done and posted")
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"Error:\n{e}",
            parse_mode=None
        )

# ==================================================
# START
# ==================================================

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
