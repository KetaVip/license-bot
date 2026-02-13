import os
import sqlite3
import threading
from datetime import datetime, timedelta

import discord
from discord.ext import commands, tasks
from flask import Flask, request, jsonify

# ================= CONFIG =================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

OWNER_ID = 412189424441491456        # 🔴 ID DISCORD CỦA BẠN
GUILD_ID = 1469614191353790652        # 🔴 ID SERVER
VIP_ROLE_NAME = "VIP"               # 🔴 TÊN ROLE VIP

PREFIX = "!"
VIP_DAYS = 30
DB_FILE = "licenses.db"
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


def is_owner(ctx):
    return ctx.author.id == OWNER_ID


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    print("🤖 Bot is ready")
    check_expired_vips.start()


# ================= COMMANDS =================
@bot.command()
async def ping(ctx):
    await ctx.send("🏓 pong")


@bot.command(name="setvip")
async def setvip(ctx, member: discord.Member, hwid: str):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    expire = datetime.utcnow() + timedelta(days=VIP_DAYS)
    expire_str = expire.strftime("%Y-%m-%d")

    cursor.execute(
        "INSERT OR REPLACE INTO licenses (user_id, hwid, expire_date) VALUES (?, ?, ?)",
        (member.id, hwid, expire_str)
    )
    conn.commit()

    role = discord.utils.get(ctx.guild.roles, name=VIP_ROLE_NAME)
    if role:
        await member.add_roles(role)

    # Gửi HWID riêng cho OWNER
    owner = await bot.fetch_user(OWNER_ID)
    await owner.send(
        f"🔑 **HWID ĐÃ CẤP**\n"
        f"👤 User: {member}\n"
        f"🔑 HWID: `{hwid}`\n"
        f"⏰ Hết hạn: `{expire_str}`"
    )

    await ctx.send(
        f"✅ Đã cấp VIP cho {member.mention}\n"
        f"⏰ Hết hạn: `{expire_str}`"
    )


@bot.command(name="removevip")
async def removevip(ctx, member: discord.Member):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    cursor.execute("DELETE FROM licenses WHERE user_id = ?", (member.id,))
    conn.commit()

    role = discord.utils.get(ctx.guild.roles, name=VIP_ROLE_NAME)
    if role:
        await member.remove_roles(role)

    await ctx.send(f"🗑️ Đã xóa VIP của {member.mention}")


@bot.command(name="checkhwid")
async def checkhwid(ctx, hwid: str):
    if not is_owner(ctx):
        await ctx.send("❌ Chỉ OWNER mới dùng được lệnh này.")
        return

    cursor.execute(
        "SELECT user_id, expire_date FROM licenses WHERE hwid = ?",
        (hwid,)
    )
    row = cursor.fetchone()

    if not row:
        await ctx.send("❌ HWID không tồn tại.")
        return

    await ctx.send(
        f"🔍 **HWID INFO**\n"
        f"👤 User ID: `{row[0]}`\n"
        f"⏰ Hết hạn: `{row[1]}`"
    )


# ================= AUTO EXPIRE TASK =================
@tasks.loop(minutes=5)
async def check_expired_vips():
    now = datetime.utcnow()
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    role = discord.utils.get(guild.roles, name=VIP_ROLE_NAME)
    if not role:
        return

    cursor.execute("SELECT user_id, expire_date FROM licenses")
    rows = cursor.fetchall()

    for user_id, expire_date in rows:
        expire = datetime.strptime(expire_date, "%Y-%m-%d")
        if now > expire:
            member = guild.get_member(user_id)
            if member and role in member.roles:
                await member.remove_roles(role)

            cursor.execute("DELETE FROM licenses WHERE user_id = ?", (user_id,))
            conn.commit()


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

    return jsonify({
        "status": "valid",
        "expire": row[0]
    })


# ================= RUN =================
def run_flask():
    app.run(host="0.0.0.0", port=PORT)


threading.Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
