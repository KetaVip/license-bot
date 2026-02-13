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
PORT = int(os.getenv("PORT", 8080))  # Railway dùng PORT động
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
    print("🤖 Bot is ready")


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)


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
async def setvip(ctx, user_id: int, days: str):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    if not days.lower().endswith("days"):
        await ctx.send("❌ Ví dụ đúng: `!setvip 123456789 3days`")
        return

    try:
        day_count = int(days.lower().replace("days", ""))
    except:
        await ctx.send("❌ Số ngày không hợp lệ.")
        return

    member = ctx.guild.get_member(user_id)
    if not member:
        await ctx.send("❌ Không tìm thấy user trong server.")
        return

    hwid = generate_hwid()
    expire = datetime.utcnow() + timedelta(days=day_count)
    expire_str = expire.strftime("%Y-%m-%d")

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
        f"⏰ Hết hạn: {expire_str}"
    )

    await ctx.send(
        f"✅ **Đã cấp VIP** cho <@{user_id}>\n"
        f"⏰ {day_count} ngày"
    )


@bot.command(name="removevip")
async def removevip(ctx, user_id: int):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    cursor.execute("SELECT hwid FROM licenses WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    if not row:
        await ctx.send("❌ User này không có VIP.")
        return

    cursor.execute("DELETE FROM licenses WHERE hwid = ?", (row[0],))
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

    await ctx.send(
        f"👤 User ID: {user_id}\n"
        f"🔑 HWID: `{row[0]}`\n"
        f"⏰ Hết hạn: `{row[1]}`"
    )


# ====== ✅ CHECKALL (OWNER ONLY) ======

@bot.command(name="checkall")
async def checkall(ctx):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    cursor.execute("SELECT user_id, hwid, expire_date FROM licenses")
    rows = cursor.fetchall()

    if not rows:
        await ctx.send("⚠️ Không có HWID nào trong hệ thống.")
        return

    now = datetime.utcnow()
    valid_list = []

    for user_id, hwid, expire_date in rows:
        expire = datetime.strptime(expire_date, "%Y-%m-%d")
        if now <= expire:
            days_left = (expire - now).days
            valid_list.append(
                f"👤 `{user_id}`\n"
                f"🔑 `{hwid}`\n"
                f"⏰ còn **{days_left} ngày**"
            )

    if not valid_list:
        await ctx.send("⚠️ Không có HWID nào còn hiệu lực.")
        return

    header = "**📋 DANH SÁCH HWID CÒN HIỆU LỰC:**\n\n"

    # gửi nhiều tin nếu quá dài
    chunk = []
    length = 0

    for item in valid_list:
        if length + len(item) > 1800:
            await ctx.send(header + "\n\n".join(chunk))
            chunk = []
            length = 0
        chunk.append(item)
        length += len(item)

    if chunk:
        await ctx.send(header + "\n\n".join(chunk))


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
