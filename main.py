import os
import sqlite3
import threading
import random
import string
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", 8080))
OWNER_ID = 489311363953328138
PREFIX = "!"
DB_FILE = "licenses.db"
VIP_ROLE_NAME = "VIP"
# =========================================


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


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    auto_remove_expired.start()
    print("🤖 Bot is ready")


def is_owner(ctx):
    return ctx.author.id == OWNER_ID


def generate_hwid(length=16):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


async def get_vip_role(guild):
    return discord.utils.get(guild.roles, name=VIP_ROLE_NAME)


# ================= COMMANDS =================

@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")


@bot.command(name="setvip")
async def setvip(ctx, user_id: int, time_value: str):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    time_value = time_value.lower()

    try:
        if time_value.endswith("m"):
            minutes = int(time_value[:-1])
            delta = timedelta(minutes=minutes)
            label = f"{minutes} phút"

        elif time_value.endswith("d"):
            days = int(time_value[:-1])
            delta = timedelta(days=days)
            label = f"{days} ngày"

        else:
            await ctx.send("❌ Dùng: `30m` hoặc `3d`")
            return

    except:
        await ctx.send("❌ Thời gian không hợp lệ.")
        return

    member = ctx.guild.get_member(user_id)
    if not member:
        await ctx.send("❌ Không tìm thấy user trong server.")
        return

    hwid = generate_hwid()
    expire = datetime.utcnow() + delta
    expire_str = expire.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "INSERT OR REPLACE INTO licenses (user_id, hwid, expire_date) VALUES (?, ?, ?)",
        (user_id, hwid, expire_str)
    )
    conn.commit()

    role = await get_vip_role(ctx.guild)
    if role:
        await member.add_roles(role)

    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(
        f"👤 User ID: {user_id}\n"
        f"🔑 HWID: {hwid}\n"
        f"⏰ Hết hạn: {expire_str} (UTC)"
    )

    await ctx.send(f"✅ **Đã cấp VIP** cho <@{user_id}> trong **{label}**")


@bot.command(name="removevip")
async def removevip(ctx, user_id: int):
    if not is_owner(ctx):
        return

    cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
    conn.commit()

    member = ctx.guild.get_member(user_id)
    role = await get_vip_role(ctx.guild)
    if member and role:
        await member.remove_roles(role)

    await ctx.send(f"🗑️ Đã remove VIP của <@{user_id}>")


@bot.command(name="checkh")
async def checkh(ctx, user_id: int):
    if not is_owner(ctx):
        return

    cursor.execute(
        "SELECT hwid, expire_date FROM licenses WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()

    if not row:
        await ctx.send("❌ User chưa có VIP.")
        return

    expire = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
    remaining = expire - datetime.utcnow()

    await ctx.send(
        f"👤 User ID: {user_id}\n"
        f"🔑 HWID: `{row[0]}`\n"
        f"⏰ Còn lại: `{remaining}`"
    )


@bot.command(name="checkall")
async def checkall(ctx):
    if not is_owner(ctx):
        return

    cursor.execute("SELECT user_id, hwid, expire_date FROM licenses")
    rows = cursor.fetchall()

    now = datetime.utcnow()
    msg = "**📋 HWID CÒN HIỆU LỰC:**\n\n"

    for user_id, hwid, expire_date in rows:
        expire = datetime.strptime(expire_date, "%Y-%m-%d %H:%M:%S")
        if now <= expire:
            remaining = expire - now
            msg += f"👤 `{user_id}`\n🔑 `{hwid}`\n⏰ {remaining}\n\n"

    await ctx.send(msg[:1900])


# ================= AUTO REMOVE EXPIRED =================

@tasks.loop(seconds=30)
async def auto_remove_expired():
    now = datetime.utcnow()

    cursor.execute("SELECT user_id, expire_date FROM licenses")
    rows = cursor.fetchall()

    for user_id, expire_date in rows:
        expire = datetime.strptime(expire_date, "%Y-%m-%d %H:%M:%S")
        if now > expire:
            cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
            conn.commit()

            for guild in bot.guilds:
                member = guild.get_member(user_id)
                role = await get_vip_role(guild)
                if member and role and role in member.roles:
                    await member.remove_roles(role)
                    print(f"⛔ Auto removed VIP: {user_id}")


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

    expire = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    if datetime.utcnow() > expire:
        return jsonify({"status": "expired"})

    return jsonify({"status": "valid", "expire": row[0]})


# ================= RUN BOTH =================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)


threading.Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
