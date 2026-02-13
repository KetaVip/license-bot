import os
import sqlite3
import threading
import random
import string
import time
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import commands
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
    expire_date TEXT,
    ip TEXT
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
        return

    member = ctx.guild.get_member(user_id)
    if not member:
        await ctx.send("❌ Không tìm thấy user.")
        return

    try:
        if time_value.endswith("days"):
            amount = int(time_value.replace("days", ""))
            expire = datetime.utcnow() + timedelta(days=amount)
        elif time_value.endswith("min"):
            amount = int(time_value.replace("min", ""))
            expire = datetime.utcnow() + timedelta(minutes=amount)
        else:
            await ctx.send("❌ Ví dụ: `!setvip ID 3days` hoặc `!setvip ID 60min`")
            return
    except:
        await ctx.send("❌ Thời gian không hợp lệ.")
        return

    hwid = generate_hwid()
    expire_str = expire.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "INSERT OR REPLACE INTO licenses (user_id, hwid, expire_date, ip) VALUES (?, ?, ?, NULL)",
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
        f"⏰ Hết hạn: {expire_str}"
    )

    await ctx.send(f"✅ Đã cấp VIP cho <@{user_id}>")


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


@bot.command(name="resetip")
async def resetip(ctx, user_id: int):
    if not is_owner(ctx):
        return

    cursor.execute("UPDATE licenses SET ip = NULL WHERE user_id = ?", (user_id,))
    conn.commit()

    await ctx.send(f"🔄 Đã reset IP cho `{user_id}`")


# ================= FLASK API =================
app = Flask(__name__)


@app.route("/check")
def check_license():
    hwid = request.args.get("hwid")
    ip = request.remote_addr

    if not hwid:
        return jsonify({"status": "error"})

    cursor.execute(
        "SELECT expire_date, ip FROM licenses WHERE hwid = ?",
        (hwid,)
    )
    row = cursor.fetchone()

    if not row:
        return jsonify({"status": "invalid"})

    expire = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    if datetime.utcnow() > expire:
        return jsonify({"status": "expired"})

    saved_ip = row[1]

    if saved_ip is None:
        cursor.execute(
            "UPDATE licenses SET ip = ? WHERE hwid = ?",
            (ip, hwid)
        )
        conn.commit()
    elif saved_ip != ip:
        return jsonify({"status": "ip_mismatch"})

    return jsonify({"status": "valid"})


# ================= AUTO REMOVE EXPIRED (FIX) =================
async def remove_expired_task():
    await bot.wait_until_ready()

    while not bot.is_closed():
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
                    if member and role:
                        await member.remove_roles(role)

        await asyncio.sleep(60)


# ================= RUN =================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)


threading.Thread(target=run_flask).start()
bot.loop.create_task(remove_expired_task())
bot.run(DISCORD_TOKEN)
