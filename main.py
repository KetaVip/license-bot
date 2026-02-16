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
    489311363953328138,  # nick chính
    412189424441491456,  # nick phụ (thay bằng ID thật)
]
PREFIX = "!"
DB_FILE = "/data/licenses.db"
VIP_ROLE_NAME = "VIP"
MAX_RESET_PER_DAY = 10
# =========================================


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
# ===========================================


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


# ================= EVENTS =================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    bot.loop.create_task(auto_remove_expired())


# ================= COMMANDS =================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")


# ===== SET VIP (TẠO MỚI + DM USER) =====
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

    cursor.execute("""
        INSERT OR REPLACE INTO licenses
        (user_id, hwid, expire_date, ip, reset_count, reset_date)
        VALUES (?, ?, ?, NULL, 0, ?)
    """, (user_id, hwid, expire_str, date.today().isoformat()))
    conn.commit()

    role = await get_vip_role(ctx.guild)
    if role:
        await member.add_roles(role)

    # ===== DM USER =====
    dm_ok = True
    try:
        await member.send(
            "🎉 **BẠN ĐÃ ĐƯỢC CẤP VIP** 🎉\n\n"
            f"🔑 **HWID:** `{hwid}`\n"
            f"⏰ **Hết hạn:** `{expire_str}`\n\n"
            "⚠️ Mỗi HWID chỉ dùng **1 IP**\n"
            "⚠️ Không share – vi phạm sẽ bị khoá VIP"
        )
    except:
        dm_ok = False

    # ===== THÔNG BÁO OWNER =====
    if not dm_ok:
        await ctx.send(
            f"⚠️ Đã cấp VIP cho <@{user_id}> nhưng **không gửi được DM**.\n"
            f"🔑 HWID: `{hwid}`\n"
            f"⏰ Hết hạn: `{expire_str}`"
        )
    else:
        await ctx.send(f"✅ Đã cấp VIP & gửi HWID qua DM cho <@{user_id}>")


# ===== ADD VIP (GIA HẠN) =====
@bot.command(name="addvip")
async def addvip(ctx, user_id: int, time_value: str):
    if not is_owner(ctx):
        return

    cursor.execute("SELECT expire_date FROM licenses WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        await ctx.send("❌ User chưa có VIP.")
        return

    try:
        current_expire = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")

        if time_value.endswith("days"):
            amount = int(time_value.replace("days", ""))
            new_expire = current_expire + timedelta(days=amount)
        elif time_value.endswith("min"):
            amount = int(time_value.replace("min", ""))
            new_expire = current_expire + timedelta(minutes=amount)
        else:
            await ctx.send("❌ Ví dụ: `!addvip ID 3days` hoặc `!addvip ID 60min`")
            return
    except:
        await ctx.send("❌ Thời gian không hợp lệ.")
        return

    new_expire_str = new_expire.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "UPDATE licenses SET expire_date = ? WHERE user_id = ?",
        (new_expire_str, user_id)
    )
    conn.commit()

    await ctx.send(
        f"✅ Gia hạn VIP thành công\n"
        f"👤 `{user_id}`\n"
        f"⏰ Hết hạn mới: `{new_expire_str}`"
    )


# ===== REMOVE VIP =====
@bot.command(name="removevip")
async def removevip(ctx, user_id: int):
    if not is_owner(ctx):
        return

    cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
    conn.commit()

    for guild in bot.guilds:
        member = guild.get_member(user_id)
        role = await get_vip_role(guild)
        if member and role:
            await member.remove_roles(role)

    await ctx.send(f"🗑️ Đã xoá VIP của `{user_id}`")


# ===== RESET IP (USER) =====
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
        await ctx.send("❌ Bạn đã dùng hết lượt reset hôm nay.")
        return

    cursor.execute("""
        UPDATE licenses
        SET ip = NULL,
            reset_count = ?,
            reset_date = ?
        WHERE user_id = ?
    """, (reset_count + 1, today, user_id))
    conn.commit()

    await ctx.send(f"🔄 Reset IP thành công ({reset_count + 1}/{MAX_RESET_PER_DAY})")


# ===== RESET IP (OWNER) =====
@bot.command(name="resetip")
async def resetip(ctx, user_id: int):
    if not is_owner(ctx):
        return

    cursor.execute("UPDATE licenses SET ip = NULL WHERE user_id = ?", (user_id,))
    conn.commit()

    await ctx.send(f"🔄 Đã reset IP cho `{user_id}`")


# ===== CHECK ALL =====
@bot.command(name="checkall")
async def checkall(ctx):
    if not is_owner(ctx):
        return

    cursor.execute("SELECT user_id, hwid, expire_date FROM licenses")
    rows = cursor.fetchall()

    if not rows:
        await ctx.send("⚠️ Không có dữ liệu.")
        return

    now = datetime.utcnow()
    msg = "**📋 DANH SÁCH VIP CÒN HIỆU LỰC**\n\n"

    for user_id, hwid, expire_date in rows:
        expire = datetime.strptime(expire_date, "%Y-%m-%d %H:%M:%S")
        if now <= expire:
            msg += (
                f"👤 `{user_id}`\n"
                f"🔑 `{hwid}`\n"
                f"⏰ `{expire - now}`\n\n"
            )

    await ctx.send(msg[:1900])


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


# ================= RUN =================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)


threading.Thread(target=run_flask, daemon=True).start()
bot.run(DISCORD_TOKEN)
