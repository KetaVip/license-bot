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
OWNER_ID = 489311363953328138
PREFIX = "!"
DB_FILE = "licenses.db"
PORT = int(os.getenv("PORT", 8080))
VIP_ROLE_NAME = "VIP"
# =========================================


# ================= DATABASE =================
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS licenses (
    user_id INTEGER PRIMARY KEY,
    hwid TEXT,
    expire_date TEXT
)
""")
conn.commit()
# ===========================================


def generate_hwid():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))


# ================= DISCORD BOT =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    check_expired_vips.start()


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)


def is_owner(ctx):
    return ctx.author.id == OWNER_ID


# ================= COMMANDS =================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")


@bot.command(name="setvip")
async def setvip(ctx, user_id: int, days: int):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    if days < 1 or days > 365:
        await ctx.send("⚠️ Số ngày không hợp lệ.")
        return

    guild = ctx.guild
    member = guild.get_member(user_id)
    if not member:
        await ctx.send("❌ Không tìm thấy user trong server.")
        return

    cursor.execute("SELECT hwid FROM licenses WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()

    hwid = row[0] if row else generate_hwid()

    expire = datetime.utcnow() + timedelta(days=days)
    expire_str = expire.strftime("%Y-%m-%d")

    cursor.execute(
        "INSERT OR REPLACE INTO licenses (user_id, hwid, expire_date) VALUES (?, ?, ?)",
        (user_id, hwid, expire_str)
    )
    conn.commit()

    role = discord.utils.get(guild.roles, name=VIP_ROLE_NAME)
    if not role:
        await ctx.send("❌ Không tìm thấy role VIP.")
        return

    try:
        await member.add_roles(role)
    except discord.Forbidden:
        await ctx.send("❌ Bot không đủ quyền gán role VIP.")
        return

    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(
        f"🆔 User ID: {user_id}\n"
        f"🔑 HWID: {hwid}\n"
        f"⏰ Hết hạn: {expire_str}"
    )

    await ctx.send(f"✅ Đã set VIP cho <@{user_id}> ({days} ngày)")


@bot.command(name="removevip")
async def removevip(ctx, user_id: int):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    guild = ctx.guild
    member = guild.get_member(user_id)

    cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
    conn.commit()

    if member:
        role = discord.utils.get(guild.roles, name=VIP_ROLE_NAME)
        if role and role in member.roles:
            try:
                await member.remove_roles(role)
            except discord.Forbidden:
                pass

    await ctx.send(f"🗑️ Đã remove VIP user `{user_id}`")


@bot.command(name="checkh")
async def checkh(ctx, user_id: int):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    cursor.execute(
        "SELECT hwid, expire_date FROM licenses WHERE user_id = ?",
        (user_id,)
    )
    row = cursor.fetchone()

    if not row:
        await ctx.send("❌ User không có VIP.")
        return

    hwid, expire_str = row
    expire = datetime.strptime(expire_str, "%Y-%m-%d")
    days_left = (expire - datetime.utcnow()).days

    await ctx.send(
        f"🆔 User ID: `{user_id}`\n"
        f"🔑 HWID: `{hwid}`\n"
        f"⏰ Còn `{days_left}` ngày"
    )


# ================= AUTO REMOVE EXPIRED =================
@tasks.loop(minutes=5)
async def check_expired_vips():
    now = datetime.utcnow()
    cursor.execute("SELECT user_id, expire_date FROM licenses")
    rows = cursor.fetchall()

    for user_id, expire_str in rows:
        expire = datetime.strptime(expire_str, "%Y-%m-%d")
        if now > expire:
            cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
            conn.commit()

            for guild in bot.guilds:
                member = guild.get_member(user_id)
                if member:
                    role = discord.utils.get(guild.roles, name=VIP_ROLE_NAME)
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role)
                        except:
                            pass


# ================= FLASK API =================
app = Flask(__name__)


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
