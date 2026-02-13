import os
import sqlite3
import threading
import random
import string
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

OWNER_ID = 489311363953328138  # ✅ OWNER CHUẨN
PREFIX = "!"
VIP_ROLE_NAME = "VIP"

DB_FILE = "licenses.db"
PORT = int(os.getenv("PORT", 8080))
# ========================================


# ================= DATABASE =================
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    user_id INTEGER,
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


def is_owner(ctx):
    return ctx.author.id == OWNER_ID


def gen_hwid(length=16):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    check_expired_vips.start()


@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")


# ================= SET VIP =================
@bot.command(name="setvip")
async def setvip(ctx, user_id: str, duration: str):
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    try:
        user_id = int(user_id)
    except:
        await ctx.send("❌ User ID không hợp lệ.")
        return

    if duration not in ["3days", "30days"]:
        await ctx.send("⚠️ Dùng: `3days` hoặc `30days`")
        return

    days = 3 if duration == "3days" else 30
    expire = datetime.utcnow() + timedelta(days=days)
    expire_str = expire.strftime("%Y-%m-%d")

    hwid = gen_hwid()

    cursor.execute(
        "INSERT OR REPLACE INTO licenses (user_id, hwid, expire_date) VALUES (?, ?, ?)",
        (user_id, hwid, expire_str)
    )
    conn.commit()

    member = ctx.guild.get_member(user_id)
    if member:
        role = discord.utils.get(ctx.guild.roles, name=VIP_ROLE_NAME)
        if not role:
            role = await ctx.guild.create_role(name=VIP_ROLE_NAME)
        await member.add_roles(role)

    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(
        f"🔐 **VIP ĐÃ CẤP**\n"
        f"👤 User ID: `{user_id}`\n"
        f"🔑 HWID: `{hwid}`\n"
        f"⏰ Hết hạn: `{expire_str}`"
    )

    await ctx.send("✅ Đã cấp VIP thành công.")

# ================= REMOVE VIP =================
@bot.command(name="removevip")
async def removevip(ctx, user_id: int):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
    conn.commit()

    member = ctx.guild.get_member(user_id)
    if member:
        role = discord.utils.get(ctx.guild.roles, name=VIP_ROLE_NAME)
        if role:
            await member.remove_roles(role)

    await ctx.send("🗑️ Đã xóa VIP.")


# ================= AUTO REMOVE EXPIRED =================
@tasks.loop(minutes=5)
async def check_expired_vips():
    cursor.execute("SELECT user_id, expire_date FROM licenses")
    rows = cursor.fetchall()

    for user_id, expire_str in rows:
        expire = datetime.strptime(expire_str, "%Y-%m-%d")
        if datetime.utcnow() > expire:
            cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
            conn.commit()

            for guild in bot.guilds:
                member = guild.get_member(user_id)
                if member:
                    role = discord.utils.get(guild.roles, name=VIP_ROLE_NAME)
                    if role:
                        await member.remove_roles(role)


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


def run_flask():
    app.run(host="0.0.0.0", port=PORT)


threading.Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
