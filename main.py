import os
import sqlite3
import threading
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from flask import Flask, request, jsonify

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # SET TRONG RENDER
OWNER_ID = 412189424441491456  # 🔴 THAY ID DISCORD CỦA BẠN
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
# ===========================================


# ================= DISCORD BOT =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print("🤖 Bot is ready")
    print("📌 Guilds:", bot.guilds)


# 🔴 BẮT BUỘC – KHÔNG CÓ → BOT KHÔNG NGHE LỆNH
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    print("MESSAGE:", message.content)
    await bot.process_commands(message)


def is_owner(ctx):
    return ctx.author.id == OWNER_ID


# ================= COMMANDS =================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")


@bot.command()
async def myid(ctx):
    await ctx.send(f"🆔 Your ID: `{ctx.author.id}`")


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


# ================= FLASK API =================
app = Flask(__name__)


@app.route("/")
def home():
    return "License API running"


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


# ================= RUN BOTH =================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)


threading.Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
