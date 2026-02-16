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

# ===== DATABASE PATH (RAILWAY VOLUME) =====
DATA_DIR = "/data"
DB_FILE = os.path.join(DATA_DIR, "licenses.db")

# ================= ENSURE DATA DIR =================
os.makedirs(DATA_DIR, exist_ok=True)

# ================= DATABASE =================
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    user_id INTEGER,
    hwid TEXT PRIMARY KEY,
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

def is_owner(ctx):
    return ctx.author.id in OWNER_IDS

def generate_hwid(length=16):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

async def get_vip_role(guild):
    return discord.utils.get(guild.roles, name=VIP_ROLE_NAME)

# ================= AUTO REMOVE EXPIRED =================
async def auto_remove_expired():
    await bot.wait_until_ready()
    print("🕒 Auto remove expired started")

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

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    bot.loop.create_task(auto_remove_expired())

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
            await ctx.send("❌ Ví dụ: !setvip ID 3days hoặc 60min")
            return
    except:
        await ctx.send("❌ Thời gian không hợp lệ.")
        return

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

    try:
        await member.send(
            f"🎉 VIP activated\nHWID: {hwid}\nExpire: {expire_str}"
        )
    except:
        pass

    await ctx.send(f"✅ Đã cấp VIP cho <@{user_id}>")

@bot.command(name="reset")
async def reset(ctx):
    user_id = ctx.author.id

    cursor.execute(
        "SELECT reset_count, reset_date FROM licenses WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()

    if not row:
        await ctx.send("❌ Bạn không có VIP.")
        return

    reset_count, reset_date = row
    today = date.today().isoformat()

    if reset_date != today:
        reset_count = 0

    if reset_count >= MAX_RESET_PER_DAY:
        await ctx.send("❌ Hết lượt reset hôm nay.")
        return

    cursor.execute("""
        UPDATE licenses
        SET ip = NULL,
            reset_count = ?,
            reset_date = ?
        WHERE user_id = ?
    """, (reset_count + 1, today, user_id))
    conn.commit()

    await ctx.send(f"🔄 Reset IP ({reset_count + 1}/{MAX_RESET_PER_DAY})")

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

    expire = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    if datetime.utcnow() > expire:
        return jsonify({"status": "expired"})

    if row[1] is None:
        cursor.execute("UPDATE licenses SET ip = ? WHERE hwid = ?", (ip, hwid))
        conn.commit()
    elif row[1] != ip:
        return jsonify({"status": "ip_mismatch"})

    return jsonify({"status": "valid"})

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

threading.Thread(target=run_flask, daemon=True).start()
bot.run(DISCORD_TOKEN)
