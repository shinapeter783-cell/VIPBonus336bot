import os
import io
import ast
import json
import random
import string
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import qrcode
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import database as db

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("❌ BOT_TOKEN missing. Add it in Railway variables.")

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    ADMIN_ID = 0

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("VIPBonus336bot")

# ---------- Config ----------
BOT_USERNAME = "VIPBonus336bot"

try:
    PROMO_CODES = json.loads(
        os.getenv("PROMO_CODES", '{"VIP336":150,"BONUS100":100,"WELCOME50":50,"LUCKY777":77}')
    )
except Exception:
    PROMO_CODES = {"VIP336": 150, "BONUS100": 100, "WELCOME50": 50, "LUCKY777": 77}

# Spin wheel segments: (label, base points, weight)
SPIN_SEGMENTS = [
    ("😢 0 pts", 0, 15),
    ("🪙 5 pts", 5, 20),
    ("💰 10 pts", 10, 20),
    ("💎 15 pts", 15, 15),
    ("🌟 20 pts", 20, 12),
    ("🔥 25 pts", 25, 8),
    ("🎁 30 pts", 30, 6),
    ("👑 100 pts VIP JACKPOT!", 100, 2),
    ("💥 50 pts", 50, 2),
]

DAILY_BASE = 10
STREAK_BONUS = 5
STREAK_CAP = 50
REFERRAL_REWARD = 50
REFERRAL_NEW_BONUS = 25
JACKPOT_BASE = 1000

USER_LAST_CMD = {}
COOLDOWN_SECONDS = 1.0


def rate_limited(user_id: int) -> bool:
    now = datetime.utcnow().timestamp()
    last = USER_LAST_CMD.get(user_id, 0)
    if now - last < COOLDOWN_SECONDS:
        return True
    USER_LAST_CMD[user_id] = now
    return False


def weighted_spin():
    total = sum(w for _, _, w in SPIN_SEGMENTS)
    r = random.uniform(0, total)
    upto = 0
    for label, pts, w in SPIN_SEGMENTS:
        if upto + w >= r:
            return label, pts
        upto += w
    return SPIN_SEGMENTS[0][0], SPIN_SEGMENTS[0][1]


def vip_tier(points: int):
    if points >= 1000:
        return "👑 Diamond VIP", 2.0, "Double spin bonus"
    if points >= 500:
        return "💎 Platinum VIP", 1.5, "+50% spin bonus"
    if points >= 200:
        return "🥇 Gold VIP", 1.25, "+25% spin bonus"
    if points >= 50:
        return "🥈 Silver VIP", 1.1, "+10% spin bonus"
    return "🥉 Bronze", 1.0, "Standard rewards"


# ==================== CORE ====================

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    db.update_user(user.id, username=user.username, first_name=user.first_name)

    if ctx.args and ctx.args[0].startswith("ref_"):
        try:
            referrer_id = int(ctx.args[0].replace("ref_", ""))
            if referrer_id != user.id and u.get("referred_by") is None:
                db.update_user(user.id, referred_by=referrer_id)
                db.add_points(referrer_id, REFERRAL_REWARD)
                db.add_points(user.id, REFERRAL_NEW_BONUS)
                ref_u = db.get_user(referrer_id)
                refs = ref_u.get("referrals", [])
                refs.append(user.id)
                db.update_user(referrer_id, referrals=refs)
                try:
                    await ctx.bot.send_message(
                        referrer_id,
                        f"🎉 <b>New referral!</b>\n"
                        f"@{user.username or user.first_name} joined with your link.\n"
                        f"<b>+{REFERRAL_REWARD} points</b> added!",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
        except ValueError:
            pass

    u = db.get_user(user.id)
    tier_name, _, _ = vip_tier(u.get("points", 0))

    keyboard = [
        [InlineKeyboardButton("🎡 Spin", callback_data="spin"),
         InlineKeyboardButton("🎁 Daily", callback_data="daily")],
        [InlineKeyboardButton("🎟️ Redeem", callback_data="redeem"),
         InlineKeyboardButton("💰 Balance", callback_data="balance")],
        [InlineKeyboardButton("👑 VIP", callback_data="vip"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("🔗 Invite", callback_data="refer"),
         InlineKeyboardButton("📖 Help", callback_data="help")],
    ]
    name = user.first_name or "VIP"
    await update.message.reply_text(
        f"🎰 Welcome <b>{name}</b> to <b>VIPBonus336bot</b>!\n\n"
        f"💰 Points: <b>{u['points']}</b>\n"
        f"🔥 Streak: <b>{u['streak']}</b> day(s)\n"
        f"👑 Tier: <b>{tier_name}</b>\n\n"
        f"Spin, claim daily bonuses, redeem codes and climb to Diamond VIP!",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>🎰 VIPBonus336bot — Commands</b>\n\n"
        "<b>🎟️ VIP Rewards</b>\n"
        "/spin – Daily lucky wheel\n"
        "/daily – Daily bonus (streak)\n"
        "/redeem &lt;code&gt; – Redeem promo code\n"
        "/balance – Your points\n"
        "/streak – Streak details\n"
        "/vip – VIP tier & perks\n"
        "/jackpot – Weekly jackpot pool\n"
        "/leaderboard – Top 10 VIPs\n"
        "/refer – Invite link\n"
        "/referrals – Your invites\n"
        "/profile – Full profile\n\n"
        "<b>🧰 Utility</b>\n"
        "/id – Telegram ID\n"
        "/qr &lt;text&gt; – QR code\n"
        "/password [len] – Password\n"
        "/shorten &lt;url&gt; – Short URL\n"
        "/calc &lt;expr&gt; – Calculator\n\n"
        "<b>🌐 Info</b>\n"
        "/crypto &lt;symbol&gt; – Crypto price\n"
        "/weather &lt;city&gt; – Weather\n"
        "/wiki &lt;topic&gt; – Wikipedia\n"
        "/time &lt;zone&gt; – Time in zone\n"
        "/convert &lt;amt&gt; &lt;from&gt; &lt;to&gt; – Currency\n\n"
        "<b>🎲 Fun</b>\n"
        "/dice [sides] – Roll dice\n"
        "/flip – Flip coin\n"
        "/poll &lt;q&gt; – Yes/No poll\n\n"
        "<b>⚠️ Danger</b>\n"
        "/reset – Wipe your data"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"🆔 <b>Your Info</b>\n"
        f"User ID: <code>{u.id}</code>\n"
        f"Username: @{u.username if u.username else 'N/A'}\n"
        f"Chat ID: <code>{update.effective_chat.id}</code>",
        parse_mode=ParseMode.HTML,
    )


# ==================== VIP FEATURES ====================

async def spin_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    today = db.today_str()

    if u.get("last_spin_date") == today:
        return await update.message.reply_text(
            "⏳ You already spun today!\nCome back tomorrow for another spin 🎡"
        )

    await update.message.reply_text("🎡 Spinning the lucky wheel...")

    label, points = weighted_spin()
    tier_name, multiplier, _ = vip_tier(u.get("points", 0))
    final_points = int(points * multiplier)

    db.update_user(user.id, last_spin_date=today)
    db.update_user(user.id, spins_total=u.get("spins_total", 0) + 1)
    new_balance = db.add_points(user.id, final_points)

    bonus_line = ""
    if final_points > points:
        bonus_line = f"\n👑 <b>{tier_name} bonus:</b> +{final_points - points} pts"

    await update.message.reply_text(
        f"🎉 <b>Result:</b> {label}\n"
        f"🎁 Base: <b>+{points} pts</b>{bonus_line}\n"
        f"💰 New balance: <b>{new_balance} points</b>",
        parse_mode=ParseMode.HTML,
    )


async def daily_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    today = db.today_str()
    yesterday = db.yesterday_str()

    if u.get("last_daily_date") == today:
        return await update.message.reply_text("⏳ You already claimed today's bonus!")

    streak = u.get("streak", 0)
    if u.get("last_daily_date") == yesterday:
        streak += 1
    else:
        streak = 1

    bonus = min(DAILY_BASE + (streak - 1) * STREAK_BONUS, DAILY_BASE + STREAK_CAP)
    db.update_user(user.id, streak=streak, last_daily_date=today)
    new_balance = db.add_points(user.id, bonus)

    await update.message.reply_text(
        f"🎁 <b>Daily bonus claimed!</b>\n\n"
        f"🔥 Streak: <b>{streak} day(s)</b>\n"
        f"💰 Reward: <b>+{bonus} points</b>\n"
        f"🏦 Balance: <b>{new_balance} points</b>\n\n"
        f"{'⭐ Come back tomorrow to grow your streak!' if streak < 10 else '🏆 You are on fire!'}",
        parse_mode=ParseMode.HTML,
    )


async def redeem_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text(
            "Usage: /redeem <code>\nExample: /redeem VIP336"
        )
    user = update.effective_user
    u = db.get_user(user.id)
    code = ctx.args[0].strip().upper()

    if code not in PROMO_CODES:
        return await update.message.reply_text("❌ Invalid promo code.")

    used = u.get("used_promos", [])
    if code in used:
        return await update.message.reply_text("⚠️ You already redeemed this code.")

    reward = PROMO_CODES[code]
    used.append(code)
    db.update_user(user.id, used_promos=used)
    new_balance = db.add_points(user.id, reward)

    await update.message.reply_text(
        f"🎟️ <b>Promo redeemed!</b>\n"
        f"Code: <code>{code}</code>\n"
        f"Reward: <b>+{reward} points</b>\n"
        f"🏦 Balance: <b>{new_balance} points</b>",
        parse_mode=ParseMode.HTML,
    )


async def balance_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    tier_name, _, _ = vip_tier(u.get("points", 0))
    await update.message.reply_text(
        f"💰 <b>Your Balance</b>\n"
        f"Points: <b>{u['points']}</b>\n"
        f"👑 Tier: <b>{tier_name}</b>\n"
        f"🔥 Streak: <b>{u['streak']} day(s)</b>\n"
        f"🎡 Total spins: <b>{u['spins_total']}</b>\n"
        f"🎟️ Promos used: <b>{len(u.get('used_promos', []))}</b>",
        parse_mode=ParseMode.HTML,
    )


async def streak_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    streak = u.get("streak", 0)
    next_bonus = min(DAILY_BASE + streak * STREAK_BONUS, DAILY_BASE + STREAK_CAP)
    await update.message.reply_text(
        f"🔥 <b>Streak</b>\n"
        f"Current: <b>{streak} day(s)</b>\n"
        f"Tomorrow's bonus (if you continue): <b>+{next_bonus} points</b>\n\n"
        f"Claim /daily every day to keep it alive!",
        parse_mode=ParseMode.HTML,
    )


async def vip_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    points = u.get("points", 0)
    tier_name, multiplier, perks = vip_tier(points)

    thresholds = [
        ("🥈 Silver VIP", 50),
        ("🥇 Gold VIP", 200),
        ("💎 Platinum VIP", 500),
        ("👑 Diamond VIP", 1000),
    ]
    next_tier = None
    for name, threshold in thresholds:
        if points < threshold:
            next_tier = (name, threshold)
            break

    if next_tier:
        next_line = (
            f"\n📈 Next tier: <b>{next_tier[0]}</b>\n"
            f"Needs: <b>{next_tier[1] - points} more points</b>"
        )
    else:
        next_line = "\n👑 You've reached the highest tier!"

    await update.message.reply_text(
        f"👑 <b>VIP Status</b>\n\n"
        f"Current tier: <b>{tier_name}</b>\n"
        f"Points: <b>{points}</b>\n"
        f"🎡 Spin multiplier: <b>{multiplier}x</b>\n"
        f"✨ Perk: <b>{perks}</b>"
        f"{next_line}",
        parse_mode=ParseMode.HTML,
    )


async def jackpot_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    total = db.total_points_in_system()
    pool = JACKPOT_BASE + total // 10
    await update.message.reply_text(
        f"💥 <b>Weekly Jackpot Pool</b>\n\n"
        f"Current pool: <b>{pool} pts</b>\n"
        f"Participants: <b>{len(db.get_all_users())}</b>\n\n"
        f"🎯 Every Monday the top 3 VIPs split the pool:\n"
        f"🥇 50% – 🥈 30% – 🥉 20%\n\n"
        f"<i>Jackpot rewards are virtual points only — no cash value.</i>",
        parse_mode=ParseMode.HTML,
    )


async def leaderboard_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    top = db.get_leaderboard(10)
    if not top:
        return await update.message.reply_text("No users yet. Be the first to /spin!")
    lines = ["🏆 <b>Top 10 VIP Users</b>\n"]
    medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
    for i, u in enumerate(top):
        name = u.get("first_name") or u.get("username") or f"User{u['id']}"
        tier_emoji = vip_tier(u.get("points", 0))[0].split()[0]
        lines.append(f"{medals[i]} {tier_emoji} {name} — <b>{u.get('points', 0)} pts</b>")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


async def refer_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}"
    await update.message.reply_text(
        f"🔗 <b>Your Invite Link</b>\n\n"
        f"<code>{link}</code>\n\n"
        f"🎁 You get <b>+{REFERRAL_REWARD} points</b> per friend.\n"
        f"🎉 They get <b>+{REFERRAL_NEW_BONUS} points</b> too!",
        parse_mode=ParseMode.HTML,
    )


async def referrals_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = db.get_user(update.effective_user.id)
    refs = u.get("referrals", [])
    if not refs:
        return await update.message.reply_text(
            "You haven't invited anyone yet. Use /refer to get your link!"
        )
    await update.message.reply_text(
        f"👥 <b>Your Referrals</b>\n"
        f"Total invited: <b>{len(refs)}</b>\n"
        f"Points earned: <b>{len(refs) * REFERRAL_REWARD}</b>",
        parse_mode=ParseMode.HTML,
    )


async def profile_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    u = db.get_user(user.id)
    joined = datetime.utcfromtimestamp(u.get("created_at", 0)).strftime("%Y-%m-%d")
    tier_name, _, _ = vip_tier(u.get("points", 0))
    await update.message.reply_text(
        f"👤 <b>Profile — {user.first_name or 'User'}</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👑 Tier: <b>{tier_name}</b>\n"
        f"💰 Points: <b>{u['points']}</b>\n"
        f"🔥 Streak: <b>{u['streak']}</b>\n"
        f"🎡 Spins: <b>{u['spins_total']}</b>\n"
        f"🎟️ Promos used: <b>{len(u.get('used_promos', []))}</b>\n"
        f"👥 Referrals: <b>{len(u.get('referrals', []))}</b>\n"
        f"📅 Joined: <b>{joined}</b>",
        parse_mode=ParseMode.HTML,
    )


async def reset_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.update_user(
        user.id,
        points=0, streak=0, spins_total=0, referrals=[],
        used_promos=[],
        last_spin_date=None, last_daily_date=None, referred_by=None,
    )
    await update.message.reply_text(
        "♻️ Your data has been reset. Points, streak, promos and referrals cleared."
    )


# ==================== UTILITY ====================

async def qr_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Usage: /qr <text or url>")
    data = " ".join(ctx.args)[:1000]
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    await update.message.reply_photo(buf, caption="✅ QR code generated.")


async def password_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    length = 16
    if ctx.args:
        try:
            length = max(8, min(64, int(ctx.args[0])))
        except ValueError:
            return await update.message.reply_text("Usage: /password [8-64]")
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    pwd = "".join(random.SystemRandom().choice(alphabet) for _ in range(length))
    await update.message.reply_text(
        f"🔐 <b>Password</b> ({length} chars):\n<code>{pwd}</code>\n\n"
        f"<i>Do not share this message.</i>",
        parse_mode=ParseMode.HTML,
    )


async def shorten_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Usage: /shorten https://example.com")
    url = ctx.args[0]
    if not url.startswith(("http://", "https://")):
        return await update.message.reply_text("❌ URL must start with http:// or https://")
    try:
        r = requests.get("https://tinyurl.com/api-create.php", params={"url": url}, timeout=10)
        if r.status_code == 200 and r.text.startswith("http"):
            await update.message.reply_text(f"🔗 Short URL:\n{r.text}")
        else:
            await update.message.reply_text("❌ Could not shorten that URL.")
    except Exception:
        await update.message.reply_text("⚠️ Service unavailable.")


async def crypto_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Usage: /crypto btc")
    symbol = ctx.args[0].lower()
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": symbol, "vs_currencies": "usd,eur"},
            timeout=10,
        )
        data = r.json()
        if symbol not in data:
            return await update.message.reply_text(
                "❌ Unknown coin. Try: btc, eth, doge, sol, xrp."
            )
        usd = data[symbol].get("usd")
        eur = data[symbol].get("eur")
        await update.message.reply_text(
            f"💰 <b>{symbol.upper()}</b>\n"
            f"USD: <code>${usd:,}</code>\n"
            f"EUR: <code>€{eur:,}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await update.message.reply_text("⚠️ Could not fetch price.")


def weather_code_desc(code: int) -> str:
    mapping = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
        80: "Rain showers", 81: "Rain showers", 82: "Violent showers",
        95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm heavy hail",
    }
    return mapping.get(code, "Unknown")


async def weather_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Usage: /weather <city>")
    city = " ".join(ctx.args)
    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1},
            timeout=10,
        ).json()
        if not geo.get("results"):
            return await update.message.reply_text("❌ City not found.")
        loc = geo["results"][0]
        name = f"{loc['name']}, {loc.get('country', '')}".strip(", ")
        w = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                    "current": "temperature_2m,wind_speed_10m,relative_humidity_2m,weather_code"},
            timeout=10,
        ).json().get("current", {})
        desc = weather_code_desc(w.get("weather_code", 0))
        await update.message.reply_text(
            f"🌍 <b>{name}</b>\n"
            f"🌡 <code>{w.get('temperature_2m')}°C</code>\n"
            f"💧 <code>{w.get('relative_humidity_2m')}%</code>\n"
            f"💨 <code>{w.get('wind_speed_10m')} km/h</code>\n"
            f"☁️ {desc}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await update.message.reply_text("⚠️ Weather service unavailable.")


async def wiki_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Usage: /wiki <topic>")
    topic = " ".join(ctx.args)
    try:
        r = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/summary/" + topic.replace(" ", "_"),
            headers={"User-Agent": "VIPBonus336bot/1.0"},
            timeout=10,
        )
        if r.status_code != 200:
            return await update.message.reply_text("❌ No article found.")
        d = r.json()
        await update.message.reply_text(
            f"📚 <b>{d.get('title')}</b>\n\n{d.get('extract', '')[:900]}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await update.message.reply_text("⚠️ Wikipedia unavailable.")


async def time_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Usage: /time Asia/Tokyo")
    tz = ctx.args[0]
    try:
        now = datetime.now(ZoneInfo(tz))
        await update.message.reply_text(
            f"🕐 <b>{tz}</b>\n<code>{now.strftime('%Y-%m-%d %H:%M:%S')}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await update.message.reply_text("❌ Invalid timezone. Example: Asia/Tokyo")


async def convert_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) != 3:
        return await update.message.reply_text("Usage: /convert 100 USD EUR")
    try:
        amount = float(ctx.args[0])
        frm, to = ctx.args[1].upper(), ctx.args[2].upper()
    except ValueError:
        return await update.message.reply_text("❌ Invalid amount.")
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest",
            params={"amount": amount, "from": frm, "to": to},
            timeout=10,
        ).json()
        if "rates" not in r or to not in r["rates"]:
            return await update.message.reply_text("❌ Unsupported currency pair.")
        await update.message.reply_text(
            f"💱 <b>{amount} {frm}</b> = <b>{r['rates'][to]:.2f} {to}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        await update.message.reply_text("⚠️ Currency service unavailable.")


ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Num, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd, ast.FloorDiv,
)


def safe_eval(expr: str):
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, ALLOWED_NODES):
            raise ValueError("Unsafe")
    return eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})


async def calc_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Usage: /calc 2+2*5")
    expr = " ".join(ctx.args)
    try:
        res = safe_eval(expr)
        await update.message.reply_text(
            f"🧮 <code>{expr}</code> = <b>{res}</b>", parse_mode=ParseMode.HTML
        )
    except Exception:
        await update.message.reply_text("❌ Invalid expression.")


async def dice_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sides = 6
    if ctx.args:
        try:
            sides = max(2, min(1000, int(ctx.args[0])))
        except ValueError:
            pass
    roll = random.randint(1, sides)
    await update.message.reply_text(
        f"🎲 You rolled <b>{roll}</b> (1–{sides})", parse_mode=ParseMode.HTML
    )


async def flip_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🪙 <b>{random.choice(['Heads', 'Tails'])}</b>", parse_mode=ParseMode.HTML
    )


async def poll_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await update.message.reply_text("Usage: /poll Your question?")
    await update.message.reply_poll(
        question=" ".join(ctx.args)[:290],
        options=["Yes ✅", "No ❌"],
        is_anonymous=False,
    )


# ==================== CALLBACKS ====================

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "spin":
        await q.message.reply_text("Use /spin to try the lucky wheel!")
    elif data == "daily":
        await q.message.reply_text("Use /daily to claim your bonus!")
    elif data == "redeem":
        await q.message.reply_text("Use /redeem <code> to redeem a promo code.")
    elif data == "balance":
        u = db.get_user(q.from_user.id)
        tier_name, _, _ = vip_tier(u.get("points", 0))
        await q.message.reply_text(
            f"💰 <b>{u['points']} points</b>\n"
            f"👑 {tier_name}\n"
            f"🔥 Streak: <b>{u['streak']} day(s)</b>",
            parse_mode=ParseMode.HTML,
        )
    elif data == "vip":
        u = db.get_user(q.from_user.id)
        tier_name, multiplier, perks = vip_tier(u.get("points", 0))
        await q.message.reply_text(
            f"👑 <b>{tier_name}</b>\n"
            f"Multiplier: <b>{multiplier}x</b>\n"
            f"Perk: {perks}\n\nUse /vip for full details.",
            parse_mode=ParseMode.HTML,
        )
    elif data == "leaderboard":
        top = db.get_leaderboard(5)
        lines = ["🏆 <b>Top 5 VIPs</b>"]
        for i, u in enumerate(top):
            name = u.get("first_name") or u.get("username") or f"User{u['id']}"
            lines.append(f"{i+1}. {name} — {u.get('points', 0)} pts")
        await q.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    elif data == "refer":
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{q.from_user.id}"
        await q.message.reply_text(
            f"🔗 Your invite link:\n<code>{link}</code>\n\n"
            f"Earn <b>+{REFERRAL_REWARD} pts</b> per friend!",
            parse_mode=ParseMode.HTML,
        )
    elif data == "help":
        await q.message.reply_text("Use /help to see all commands.")


# ==================== FALLBACK ====================

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤔 Unknown command. Type /help.")


async def text_fallback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hi! I respond to commands. Type /help to see options.")


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=ctx.error)


# ==================== MAIN ====================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("id", id_cmd))
    app.add_handler(CommandHandler("spin", spin_cmd))
    app.add_handler(CommandHandler("daily", daily_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("streak", streak_cmd))
    app.add_handler(CommandHandler("vip", vip_cmd))
    app.add_handler(CommandHandler("jackpot", jackpot_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("refer", refer_cmd))
    app.add_handler(CommandHandler("referrals", referrals_cmd))
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("qr", qr_cmd))
    app.add_handler(CommandHandler("password", password_cmd))
    app.add_handler(CommandHandler("shorten", shorten_cmd))
    app.add_handler(CommandHandler("crypto", crypto_cmd))
    app.add_handler(CommandHandler("weather", weather_cmd))
    app.add_handler(CommandHandler("wiki", wiki_cmd))
    app.add_handler(CommandHandler("time", time_cmd))
    app.add_handler(CommandHandler("convert", convert_cmd))
    app.add_handler(CommandHandler("calc", calc_cmd))
    app.add_handler(CommandHandler("dice", dice_cmd))
    app.add_handler(CommandHandler("flip", flip_cmd))
    app.add_handler(CommandHandler("poll", poll_cmd))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_fallback))
    app.add_error_handler(on_error)

    logger.info("🎰 VIPBonus336bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
