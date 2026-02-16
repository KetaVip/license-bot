import os
import sqlite3
import threading
import random
import string
import asyncio
from datetime import datetime, timedelta, date, timezone

import discord
from discord.ext import commands
from flask import Flask, request, jsonify

# ================= TIMEZONE (VIET NAM UTC+7) =================
VN_TZ = timezone(timedelta(hours=7))

def now_vn():
    return datetime.now(VN_TZ)

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
    reset_date TEXT,
    notified INTEGER DEFAULT 0
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
        now = now_vn()

        cursor.execute("SELECT user_id, expire_date FROM licenses")
        for user_id, expire_date in cursor.fetchall():
            expire = datetime.strptime(expire_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=VN_TZ)
            if now > expire:
                cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
                conn.commit()

                for guild in bot.guilds:
                    member = guild.get_member(user_id)
                    role = await get_vip_role(guild)
                    if member and role:
                        await member.remove_roles(role)

        await asyncio.sleep(60)

# ================= AUTO NOTIFY BEFORE EXPIRE (1 MIN) =================
async def auto_notify_expiring():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = now_vn()

        cursor.execute(
            "SELECT user_id, expire_date FROM licenses WHERE notified = 0"
        )
        rows = cursor.fetchall()

        for user_id, expire_date in rows:
            expire = datetime.strptime(
                expire_date, "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=VN_TZ)

            remaining = (expire - now).total_seconds()

            if 0 < remaining <= 60:
                user = bot.get_user(user_id)
                if user:
                    try:
                        await user.send(
                            "⚠️ **VIP CỦA BẠN SẮP HẾT HẠN!**\n\n"
                            f"⏰ Còn **{int(remaining)} giây** nữa sẽ hết hạn.\n"
                            "💳 Vui lòng gia hạn ngay để tránh bị mất quyền VIP."
                        )
                    except:
                        pass

                cursor.execute(
                    "UPDATE licenses SET notified = 1 WHERE user_id = ?",
                    (user_id,)
                )
                conn.commit()

        await asyncio.sleep(5)

# ================= BOT READY =================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    if not hasattr(bot, "task_started"):
        bot.loop.create_task(auto_remove_expired())
        bot.loop.create_task(auto_notify_expiring())
        bot.task_started = True

# ================= COMMANDS =================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")

# ===== SET VIP =====
@bot.command()
async def setvip(ctx, user_id: int, time_value: str):
    if not is_owner(ctx):
        return await ctx.send("❌ Bạn không có quyền.")

    member = ctx.guild.get_member(user_id)
    if not member:
        return await ctx.send("❌ Không tìm thấy user.")

    try:
        if time_value.endswith("days"):
            expire = now_vn() + timedelta(days=int(time_value[:-4]))
        elif time_value.endswith("min"):
            expire = now_vn() + timedelta(minutes=int(time_value[:-3]))
        else:
            return await ctx.send("❌ Ví dụ: !setvip ID 3days / 60min")
    except:
        return await ctx.send("❌ Thời gian không hợp lệ.")

    hwid = generate_hwid()
    expire_str = expire.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT OR REPLACE INTO licenses
        (user_id, hwid, expire_date, ip, reset_count, reset_date, notified)
        VALUES (?, ?, ?, NULL, 0, ?, 0)
    """, (user_id, hwid, expire_str, date.today().isoformat()))
    conn.commit()

    role = await get_vip_role(ctx.guild)
    if role:
        await member.add_roles(role)

    await ctx.send(f"✅ Đã cấp VIP cho <@{user_id}>")

    try:
        await member.send(
            f"🎉 **BẠN ĐÃ ĐƯỢC CẤP VIP**\n"
            f"🔑 HWID: `{hwid}`\n"
            f"⏰ Hết hạn: `{expire_str}` (GMT+7)"
        )
    except:
        pass

# ===== ADD VIP =====
@bot.command()
async def addvip(ctx, user_id: int, time_value: str):
    if not is_owner(ctx):
        return await ctx.send("❌ Bạn không có quyền.")

    cursor.execute("SELECT expire_date, hwid FROM licenses WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        return await ctx.send("❌ User chưa có VIP.")

    old_expire = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=VN_TZ)
    hwid = row[1]

    try:
        if time_value.endswith("days"):
            delta = timedelta(days=int(time_value[:-4]))
        elif time_value.endswith("min"):
            delta = timedelta(minutes=int(time_value[:-3]))
        else:
            return await ctx.send("❌ Ví dụ: !addvip ID 3days / 60min")
    except:
        return await ctx.send("❌ Thời gian không hợp lệ.")

    now = now_vn()
    new_expire = old_expire + delta if old_expire > now else now + delta
    new_expire_str = new_expire.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "UPDATE licenses SET expire_date = ?, notified = 0 WHERE user_id = ?",
        (new_expire_str, user_id)
    )
    conn.commit()

    await ctx.send(f"✅ Gia hạn VIP cho <@{user_id}> đến `{new_expire_str}`")

    member = ctx.guild.get_member(user_id)
    if member:
        try:
            await member.send(
                f"🔔 **VIP ĐÃ ĐƯỢC GIA HẠN**\n"
                f"🔑 HWID: `{hwid}`\n"
                f"⏰ Hết hạn mới: `{new_expire_str}` (GMT+7)"
            )
        except:
            pass

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

    expire = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=VN_TZ)
    if now_vn() > expire:
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
