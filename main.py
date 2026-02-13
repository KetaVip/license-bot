import os
import sqlite3
import threading
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from flask import Flask, request, jsonify

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 412189424441491456  # 🔴 ID Discord của bạn
PREFIX = "!"
DB_FILE = "licenses.db"
VIP_DAYS = 30
PORT = int(os.getenv("PORT", 8080))
# =========================================


# ================= DATABASE =================
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    hwid TEXT PRIMARY KEY,
    expire_date TEXT
)
""")
conn.commit()
# ===========================================


# ================= FLASK API =================
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ License API running"

@app.route("/check")
def check_license():
    hwid = request.args.get("hwid")
    if not hwid:
        return jsonify({"status": "error", "msg": "no hwid"})

    cursor.execute(
        "SELECT expire_date FROM licenses WHERE hwid = ?",
        (hwid,)
    )
    row = cursor.fetchone()

    if not row:
        return jsonify({"status": "invalid"})

    expire = datetime.strptime(row[0], "%Y-%m-%d")
    if datetime.utcnow() > expire:
        return jsonify({"status": "expired"})

    return jsonify({
        "status": "valid",
        "expire": row[0]
    })


def run_flask():
    print("🌐 Flask API starting...")
    app.run(host="0.0.0.0", port=PORT)


# ================= DISCORD BOT =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print("🤖 Discord bot ready")


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)


def is_owner(ctx):
    return ctx.author.id == OWNER_ID


@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")


@bot.command(name="setvip")
async def setvip(ctx, hwid: str):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    expire = datetime.utcnow() + timedelta(days=VIP_DAYS)
    expire_str = expire.strftime("%Y-%m-%d")

    cursor.execute(
        "INSERT OR REPLACE INTO licenses (hwid, expire_date) VALUES (?, ?)",
        (hwid, expire_str)
    )
    conn.commit()

    await ctx.send(
        f"✅ **ĐÃ CẤP VIP**\n"
        f"🔑 HWID: `{hwid}`\n"
        f"⏰ Hết hạn: `{expire_str}`"
    )


@bot.command(name="removevip")
async def removevip(ctx, hwid: str):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    cursor.execute("DELETE FROM licenses WHERE hwid = ?", (hwid,))
    conn.commit()

    await ctx.send(f"🗑️ Đã xóa VIP cho HWID `{hwid}`")


# ================= MAIN =================
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    print("🤖 Starting Discord bot...")
    bot.run(DISCORD_TOKEN)
