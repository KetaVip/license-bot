import os
import sqlite3
import threading
import random
import string
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from flask import Flask, request, jsonify

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 412189424441491456
PREFIX = "!"
DB_FILE = "licenses.db"
PORT = int(os.getenv("PORT", 8080))
# ==========================================


# ================= DATABASE =================
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    user_id TEXT,
    hwid TEXT PRIMARY KEY,
    expire_date TEXT
)
""")
conn.commit()
# ===========================================


# ================= BOT =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")


def is_owner(ctx):
    return ctx.author.id == OWNER_ID


def gen_hwid():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))


# ================= COMMAND =================
@bot.command(name="setvip")
async def setvip(ctx, user_id: int, duration: str):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    if duration == "3days":
        days = 3
    elif duration == "30days":
        days = 30
    else:
        await ctx.send("❌ Thời hạn chỉ được: `3days` hoặc `30days`")
        return

    member = ctx.guild.get_member(user_id)
    if not member:
        await ctx.send("❌ Không tìm thấy user trong server.")
        return

    expire = datetime.utcnow() + timedelta(days=days)
    expire_str = expire.strftime("%Y-%m-%d")

    hwid = gen_hwid()

    cursor.execute(
        "INSERT OR REPLACE INTO licenses (user_id, hwid, expire_date) VALUES (?, ?, ?)",
        (str(user_id), hwid, expire_str)
    )
    conn.commit()

    # ROLE VIP
    role = discord.utils.get(ctx.guild.roles, name="VIP")
    if role:
        await member.add_roles(role)

    # DM OWNER
    owner = ctx.guild.get_member(OWNER_ID)
    if owner:
        await owner.send(
            f"🔑 **CẤP VIP MỚI**\n"
            f"👤 User ID: `{user_id}`\n"
            f"HWID: `{hwid}`\n"
            f"Hết hạn: `{expire_str}`"
        )

    await ctx.send(
        f"✅ Đã cấp VIP cho <@{user_id}>\n"
        f"⏰ Thời hạn: `{duration}`"
    )


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


# ================= RUN =================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)


threading.Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
