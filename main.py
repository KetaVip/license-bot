import os
import threading
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
import discord
from discord.ext import commands

# ================== CONFIG ==================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # set trong Render
COMMAND_PREFIX = "!"
OWNER_ID = 123456789012345678  # thay bằng Discord ID của bạn
DB_NAME = "license.db"

# ================== DATABASE ==================
conn = sqlite3.connect(DB_NAME, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    hwid TEXT PRIMARY KEY,
    expire_date TEXT
)
""")
conn.commit()

# ================== FLASK API ==================
app = Flask(__name__)

@app.route("/")
def home():
    return "License API is running"

@app.route("/check", methods=["GET"])
def check_license():
    hwid = request.args.get("hwid")

    if not hwid:
        return jsonify({"status": "error", "message": "missing hwid"}), 400

    cursor.execute(
        "SELECT expire_date FROM licenses WHERE hwid = ?",
        (hwid,)
    )
    row = cursor.fetchone()

    if not row:
        return jsonify({"status": "invalid"})

    expire_date = datetime.strptime(row[0], "%Y-%m-%d")
    if datetime.now() > expire_date:
        return jsonify({"status": "expired"})

    return jsonify({
        "status": "valid",
        "expire": expire_date.strftime("%Y-%m-%d")
    })

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# ================== DISCORD BOT ==================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")

@bot.command()
async def add(ctx, hwid: str, days: int):
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Bạn không có quyền")
        return

    expire_date = datetime.now() + timedelta(days=days)

    cursor.execute(
        "REPLACE INTO licenses (hwid, expire_date) VALUES (?, ?)",
        (hwid, expire_date.strftime("%Y-%m-%d"))
    )
    conn.commit()

    await ctx.send(
        f"✅ Đã thêm license\nHWID: `{hwid}`\nHết hạn: `{expire_date.strftime('%Y-%m-%d')}`"
    )

@bot.command()
async def remove(ctx, hwid: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Bạn không có quyền")
        return

    cursor.execute("DELETE FROM licenses WHERE hwid = ?", (hwid,))
    conn.commit()
    await ctx.send(f"🗑️ Đã xoá license `{hwid}`")

@bot.command()
async def check(ctx, hwid: str):
    cursor.execute(
        "SELECT expire_date FROM licenses WHERE hwid = ?",
        (hwid,)
    )
    row = cursor.fetchone()

    if not row:
        await ctx.send("❌ Không tồn tại")
        return

    expire_date = datetime.strptime(row[0], "%Y-%m-%d")
    await ctx.send(f"✅ License hợp lệ đến `{expire_date.strftime('%Y-%m-%d')}`")

# ================== START ==================
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(DISCORD_TOKEN)
