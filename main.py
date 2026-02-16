import os
import sqlite3
import threading
import random
import string
import asyncio
from datetime import datetime, timedelta, date

import discord
from discord.ext import commands
from flask import Flask, request, jsonify

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.getenv("PORT", 8080))

OWNER_IDS = [
    489311363953328138,
    412189424441491456,
]

PREFIX = "!"
VIP_ROLE_NAME = "VIP"
MAX_RESET_PER_DAY = 10

# ================= DATABASE =================
DATA_DIR = "/data"
DB_FILE = os.path.join(DATA_DIR, "licenses.db")
os.makedirs(DATA_DIR, exist_ok=True)

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    user_id INTEGER PRIMARY KEY,
    hwid TEXT,
    expire_date TEXT,
    ip TEXT,
    reset_count INTEGER DEFAULT 0,
    reset_date TEXT
)
""")
conn.commit()

# ================= DISCORD BOT =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ================= UTILS =================
def is_owner(ctx):
    return ctx.author.id in OWNER_IDS

def generate_hwid(length=16):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

async def get_vip_role(guild):
    return discord.utils.get(guild.roles, name=VIP_ROLE_NAME)

# ================= AUTO REMOVE EXPIRED =================
async def auto_remove_expired():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.utcnow()

        cursor.execute("SELECT user_id, expire_date FROM licenses")
        for user_id, expire_date in cursor.fetchall():
            if now > datetime.strptime(expire_date, "%Y-%m-%d %H:%M:%S"):
                cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
                conn.commit()

                for guild in bot.guilds:
                    member = guild.get_member(user_id)
                    role = await get_vip_role(guild)
                    if member and role:
                        await member.remove_roles(role)

        await asyncio.sleep(60)

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    if not hasattr(bot, "task_started"):
        bot.loop.create_task(auto_remove_expired())
        bot.task_started = True

# ================= COMMANDS =================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")

# ===== SET VIP (OWNER) =====
@bot.command()
async def setvip(ctx, user_id: int, time_value: str):
    if not is_owner(ctx):
        return await ctx.send("❌ Bạn không có quyền.")

    member = ctx.guild.get_member(user_id)
    if not member:
        return await ctx.send("❌ Không tìm thấy user.")

    try:
        if time_value.endswith("days"):
            expire = datetime.utcnow() + timedelta(days=int(time_value[:-4]))
        elif time_value.endswith("min"):
            expire = datetime.utcnow() + timedelta(minutes=int(time_value[:-3]))
        else:
            return await ctx.send("❌ Ví dụ: !setvip ID 3days / 60min")
    except:
        return await ctx.send("❌ Thời gian không hợp lệ.")

    hwid = generate_hwid()
    expire_str = expire.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT OR REPLACE INTO licenses
        (user_id, hwid, expire_date, ip, reset_count, reset_date)
        VALUES (?, ?, ?, NULL, 0, ?)
    """, (user_id, hwid, expire_str, date.today().isoformat()))
    conn.commit()

    role = await get_vip_role(ctx.guild)
    if role:
        await member.add_roles(role)

    await ctx.send(f"✅ Đã cấp VIP cho <@{user_id}>")

    try:
        await member.send(
            f"🎉 **Bạn đã được cấp VIP**\n"
            f"🔑 HWID: `{hwid}`\n"
            f"⏰ Hết hạn: `{expire_str}`"
        )
    except:
        pass

# ===== REMOVE VIP (OWNER) =====
@bot.command()
async def removevip(ctx, user_id: int):
    if not is_owner(ctx):
        return await ctx.send("❌ Bạn không có quyền.")

    cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
    conn.commit()

    member = ctx.guild.get_member(user_id)
    role = await get_vip_role(ctx.guild)
    if member and role:
        await member.remove_roles(role)

    await ctx.send(f"🗑️ Đã xóa VIP của <@{user_id}>")

# ===== CHECK ALL (OWNER) =====
@bot.command()
async def checkall(ctx):
    if not is_owner(ctx):
        return await ctx.send("❌ Bạn không có quyền.")

    cursor.execute("SELECT user_id, expire_date FROM licenses")
    rows = cursor.fetchall()

    if not rows:
        return await ctx.send("📭 Không có VIP nào.")

    msg = "**📋 DANH SÁCH VIP:**\n"
    for uid, exp in rows:
        msg += f"👤 <@{uid}> | ⏰ `{exp}`\n"

    await ctx.send(msg)

# ===== RESET IP (OWNER – UNLIMITED) =====
@bot.command()
async def resetip(ctx, user_id: int):
    if not is_owner(ctx):
        return await ctx.send("❌ Bạn không có quyền.")

    cursor.execute("UPDATE licenses SET ip = NULL WHERE user_id = ?", (user_id,))
    conn.commit()

    await ctx.send(f"🔄 Đã reset IP cho <@{user_id}>")

# ===== CHECK VIP (USER) =====
@bot.command()
async def check(ctx):
    cursor.execute("SELECT expire_date FROM licenses WHERE user_id = ?", (ctx.author.id,))
    row = cursor.fetchone()

    if not row:
        return await ctx.send("❌ Bạn không có VIP.")

    await ctx.send(f"⏰ VIP của bạn hết hạn: `{row[0]}`")

# ================= FLASK API =================
app = Flask(__name__)

@app.route("/check")
def check_license():
    hwid = request.args.get("hwid")
    ip = request.remote_addr

    cursor.execute("SELECT expire_date, ip FROM licenses WHERE hwid = ?", (hwid,))
    row = cursor.fetchone()

    if not row:
        return jsonify({"status": "invalid"})

    if datetime.utcnow() > datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"):
        return jsonify({"status": "expired"})

    if row[1] is None:
        cursor.execute("UPDATE licenses SET ip = ? WHERE hwid = ?", (ip, hwid))
        conn.commit()
    elif row[1] != ip:
        return jsonify({"status": "ip_mismatch"})

    return jsonify({"status": "valid"})

threading.Thread(
    target=lambda: app.run(host="0.0.0.0", port=PORT, use_reloader=False),
    daemon=True
).start()

# ================= START =================
bot.run(DISCORD_TOKEN)
