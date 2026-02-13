import os
import sqlite3
import threading
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from flask import Flask, request, jsonify

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 412189424441491456  # 🔴 THAY ID CỦA BẠN
PREFIX = "!"
DB_FILE = "licenses.db"
VIP_DAYS = 30
PORT = int(os.getenv("PORT", 10000))
# ==========================================

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
# ============================================

# ================= DISCORD BOT =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print("🤖 Bot is ready")


def owner_only(ctx):
    return ctx.author.id == OWNER_ID


@bot.command(name="setvip")
async def setvip(ctx, member: discord.Member, hwid: str):
    if not owner_only(ctx):
        await ctx.send("❌ Chỉ OWNER mới được dùng lệnh này.")
        return

    expire = datetime.utcnow() + timedelta(days=VIP_DAYS)
    expire_str = expire.strftime("%Y-%m-%d")

    cursor.execute(
        "INSERT OR REPLACE INTO licenses (hwid, expire_date) VALUES (?, ?)",
        (hwid, expire_str)
    )
    conn.commit()

    await ctx.send(
        f"✅ **VIP đã được cấp**\n"
        f"👤 User: {member.mention}\n"
        f"🔑 HWID: `{hwid}`\n"
        f"⏰ Hết hạn: `{expire_str}`"
    )


@bot.command(name="removevip")
async def removevip(ctx, hwid: str):
    if not owner_only(ctx):
        await ctx.send("❌ Chỉ OWNER mới được dùng lệnh này.")
        return

    cursor.execute("DELETE FROM licenses WHERE hwid = ?", (hwid,))
    conn.commit()

    await ctx.send(f"🗑️ Đã **xóa VIP** cho HWID `{hwid}`")


@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")
# =============================================

# ================= FLASK API =================
app = Flask(__name__)


@app.route("/")
def home():
    return "License API running"


@app.route("/check")
def check_license():
    hwid = request.args.get("hwid")
    if not hwid:
        return jsonify({"status": "error"})

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

    return jsonify({"status": "valid", "expire": row[0]})
# =============================================

# ================= RUN =================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
# ======================================
