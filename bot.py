import os
import base64
import json
import tempfile
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
from groq import Groq

from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from database import (
    init_database,
    register_user,
    activate_user,
    extend_user,
    block_user,
    check_license,
    get_user,
    log_usage,
)

from pipeline_engine import (
    run_full_pipeline,
    format_final_report,
)
from v13_engine import format_v13_tip


# =========================================================
# BETTING BAYIN V13
# TELEGRAM BOT + FULL AI PIPELINE + RENDER HEALTH SERVER
# =========================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID_RAW = os.getenv("ADMIN_USER_ID", "").strip()
ADMIN_USERNAME_RAW = os.getenv("ADMIN_USERNAME", "").strip()
VISION_MODEL = os.getenv("VISION_MODEL", "qwen/qwen3.6-27b")
PORT = int(os.getenv("PORT", "10000"))

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY မတွေ့ပါ")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN မတွေ့ပါ")

ADMIN_USER_ID = (
    int(ADMIN_USER_ID_RAW)
    if ADMIN_USER_ID_RAW.isdigit()
    else None
)

ADMIN_USERNAME = ADMIN_USERNAME_RAW.lstrip("@").strip()
ADMIN_CONTACT = f"@{ADMIN_USERNAME}" if ADMIN_USERNAME else "Admin"

groq_client = Groq(api_key=GROQ_API_KEY)
init_database()


VISION_SYSTEM_PROMPT = """
You are the vision extraction engine for Betting Bayin.

Your ONLY job is to accurately read football betting screenshots.

STRICT RULES:
1. Never invent information.
2. Only extract information visible in the screenshot.
3. If something cannot be read, return null.
4. Do NOT give betting advice.
5. Do NOT predict the match.
6. Do NOT use outside knowledge.
7. Preserve decimal odds accurately.
8. Identify PRE-MATCH or LIVE.
9. Extract every visible betting market.
10. Never guess hidden markets.
11. Return valid JSON only.
12. Do not output markdown.
13. Do not output explanations.
14. Do not output <think> tags.

Return exactly:

{
  "sport": null,
  "competition": null,
  "round_or_group": null,
  "match": {
    "home_team": null,
    "away_team": null
  },
  "match_type": null,
  "start_date": null,
  "start_time": null,
  "live": {
    "is_live": false,
    "minute": null,
    "score": null
  },
  "markets": [
    {
      "market_name": "",
      "selections": [
        {
          "selection": "",
          "odds": null
        }
      ]
    }
  ],
  "unreadable_items": []
}
"""


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            payload = {
                "ok": True,
                "service": "Betting Bayin",
                "version": "V13",
                "telegram_polling": True,
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not Found")

    def do_HEAD(self):
        if self.path in ("/", "/health"):
            body = json.dumps({
                "ok": True,
                "service": "Betting Bayin",
                "version": "V13",
                "telegram_polling": True,
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return

        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="render-health-server",
        daemon=True,
    )
    thread.start()
    print(f"🌐 Health server ONLINE on 0.0.0.0:{PORT}")
    print("🩺 Health endpoint: /health")
    return server


# =========================================================
# HELPERS
# =========================================================

def is_admin(user_id):
    return (
        ADMIN_USER_ID is not None
        and user_id == ADMIN_USER_ID
    )


def image_to_data_url(image_path):
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def analyze_screenshot(image_path):
    image_url = image_to_data_url(image_path)

    response = groq_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": VISION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Read this betting screenshot and extract every visible betting detail.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ],
            },
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)



# =========================================================
# FAST ALWAYS-TIP FORMATTER
# =========================================================

def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _recursive_find_first(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] is not None:
                return obj[key]
        for value in obj.values():
            found = _recursive_find_first(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _recursive_find_first(value, keys)
            if found is not None:
                return found
    return None


def _market_display(selection, home_team, away_team):
    raw = str(selection or "").strip()
    key = raw.lower()

    mapping = {
        "home_win": f"1X2 - {home_team}",
        "w1": f"1X2 - {home_team}",
        "1": f"1X2 - {home_team}",
        "draw": "1X2 - Draw",
        "x": "1X2 - Draw",
        "away_win": f"1X2 - {away_team}",
        "w2": f"1X2 - {away_team}",
        "2": f"1X2 - {away_team}",
        "1x": f"Double Chance - 1X ({home_team} or Draw)",
        "x2": f"Double Chance - X2 (Draw or {away_team})",
        "2x": f"Double Chance - X2 (Draw or {away_team})",
        "12": "Double Chance - 12 (No Draw)",
        "yes": "Both Teams To Score - YES",
        "no": "Both Teams To Score - NO",
    }
    return mapping.get(key, raw or "Best Available Selection")


def _visible_fallback(extracted):
    candidates = []
    for market in extracted.get("markets", []) or []:
        market_name = str(market.get("market_name") or "").strip()
        for item in market.get("selections", []) or []:
            odds = _safe_float(item.get("odds"))
            selection = str(item.get("selection") or "").strip()
            if not selection or odds is None or odds <= 1.0:
                continue
            # Avoid absurdly short picks when another useful market is visible.
            score = 1.0 / odds
            candidates.append({
                "market_name": market_name,
                "selection": selection,
                "odds": odds,
                "score": score,
            })
    if not candidates:
        return None
    # "Safest visible" fallback: highest implied probability.
    return max(candidates, key=lambda x: x["score"])


def build_always_tip_report(result, extracted):
    match = extracted.get("match") or {}
    home_team = match.get("home_team") or result.get("match", {}).get("home_team") or "Home"
    away_team = match.get("away_team") or result.get("match", {}).get("away_team") or "Away"
    competition = extracted.get("competition") or result.get("competition") or "Unknown League"
    live = extracted.get("live") or {}
    bet_type = "Live Bet" if live.get("is_live") else "Pre Bet"

    # Prefer the model's value comparison even when its hard decision is PASS/DATA_CONFLICT.
    value_block = None
    for key in ("final_value", "first_value", "value", "market_value"):
        candidate = result.get(key)
        if isinstance(candidate, dict) and isinstance(candidate.get("comparison"), list):
            value_block = candidate
            break
    if value_block is None and isinstance(result.get("comparison"), list):
        value_block = result

    chosen = None
    if value_block:
        rows = []
        for row in value_block.get("comparison", []) or []:
            odds = _safe_float(row.get("odds"))
            model_p = _safe_float(row.get("model_probability"))
            ev = _safe_float(
                row.get("expected_value_percent")
                if row.get("expected_value_percent") is not None
                else row.get("expected_value")
            )
            edge = _safe_float(
                row.get("edge_percent")
                if row.get("edge_percent") is not None
                else row.get("edge")
            )
            if odds is None:
                continue
            rows.append({
                "selection": row.get("selection"),
                "odds": odds,
                "model_probability": model_p,
                "ev": ev,
                "edge": edge,
            })

        if rows:
            # First priority: highest EV; second: highest model probability.
            def rank_row(row):
                ev = row["ev"] if row["ev"] is not None else -999999
                mp = row["model_probability"] if row["model_probability"] is not None else -1
                return (ev, mp)
            chosen = max(rows, key=rank_row)

    fallback_used = False
    if chosen is None:
        fallback = _visible_fallback(extracted)
        if fallback:
            chosen = {
                "selection": fallback["selection"],
                "odds": fallback["odds"],
                "model_probability": None,
                "ev": None,
                "edge": None,
                "market_name": fallback["market_name"],
            }
            fallback_used = True

    if chosen is None:
        return (
            "👑 BETTING BAYIN\n\n"
            "⚠️ Screenshot ထဲက odds/market ကို ဖတ်မရသေးပါ။\n"
            "Market နဲ့ odds မြင်ရအောင် screenshot ကို ပြန်ပို့ပါ။"
        )

    # Confidence: use the best available model reliability signal.
    confidence_raw = _recursive_find_first(
        result,
        ["reliability_factor", "reliability", "score", "model_confidence"]
    )
    if isinstance(confidence_raw, dict):
        confidence_raw = confidence_raw.get("score") or confidence_raw.get("reliability")
    confidence = _safe_float(confidence_raw)
    if confidence is None:
        confidence = 0.20 if fallback_used else 0.35
    if confidence <= 1.0:
        confidence *= 100.0
    confidence = max(0.0, min(100.0, confidence))

    if confidence >= 70:
        confidence_label = "HIGH"
    elif confidence >= 45:
        confidence_label = "MEDIUM"
    else:
        confidence_label = "LOW"

    market_text = chosen.get("market_name")
    if not market_text:
        market_text = _market_display(chosen.get("selection"), home_team, away_team)
    else:
        market_text = f"{market_text} - {chosen.get('selection')}"

    model_probability = chosen.get("model_probability")
    probability_line = ""
    if model_probability is not None:
        if model_probability <= 1:
            model_probability *= 100
        probability_line = f"\n📊 Model Probability: {model_probability:.1f}%"

    ev = chosen.get("ev")
    ev_line = ""
    if ev is not None:
        if -1.0 <= ev <= 1.0:
            ev *= 100
        ev_line = f"\n📈 EV: {ev:+.1f}%"

    note = (
        "🧠 Model decision filter က NO BET ဖြစ်ခဲ့ပေမယ့် "
        "available markets ထဲက အကောင်းဆုံး candidate ကို fallback tip အဖြစ်ရွေးထားပါတယ်။"
        if fallback_used or str(result.get("decision", "")).upper() in {"NO_BET", "PASS", "DATA_CONFLICT"}
        else "✅ Model/value ranking အရ ရွေးထားသော tip ဖြစ်ပါတယ်။"
    )

    return (
        "👑 BETTING BAYIN\n\n"
        "🎯 BEST AVAILABLE TIP\n\n"
        f"⚽ ပွဲစဉ် (Match): {home_team} vs {away_team}\n"
        f"🏆 League: {competition}\n"
        f"🎫 လောင်းမည့်အမျိုးအစား (Bet Type): {bet_type}\n"
        f"📌 ရွေးချယ်လိုက်သော Market (Best Value Market): {market_text}\n"
        f"💰 Odds: {chosen['odds']:.3f}"
        f"{probability_line}"
        f"{ev_line}\n"
        f"🛡 ယုံကြည်မှု (Confidence): {confidence:.1f}% ({confidence_label})\n\n"
        f"{note}\n"
        "⚠️ LOW confidence ဖြစ်ရင် stake ကို လျှော့သုံးပါ။"
    )


# =========================================================
# COMMANDS
# =========================================================

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        "🆔 YOUR TELEGRAM USER ID\n\n"
        f"{user.id}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    register_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    if is_admin(user.id):
        await update.message.reply_text(
            "👑 BETTING BAYIN V13\n\n"
            "🛡 ADMIN MODE\n\n"
            f"Admin ID: {user.id}\n\n"
            "COMMANDS\n\n"
            "👤 /myid\n"
            "➕ /activate USER_ID DAYS\n"
            "⏳ /extend USER_ID DAYS\n"
            "🚫 /block USER_ID\n"
            "🔎 /status USER_ID\n\n"
            "📸 Pre-match screenshot ပို့ပါ။\n"
            "Vision → Research → Elo → Probability → Value → Final Decision ကို အလိုအလျောက် run ပါမယ်."
        )
        return

    active, status, expires_at = check_license(user.id)

    if active:
        expiry_text = expires_at.strftime("%d-%m-%Y %H:%M UTC")
        await update.message.reply_text(
            "👑 BETTING BAYIN V13\n\n"
            f"မင်္ဂလာပါ {user.first_name}!\n\n"
            "🟢 SUBSCRIPTION ACTIVE\n\n"
            f"⏳ Expire: {expiry_text}\n\n"
            "📸 1XBET Pre-Bet Screenshot ပို့နိုင်ပါပြီ."
        )
        return

    await update.message.reply_text(
        "👑 BETTING BAYIN\n\n"
        f"မင်္ဂလာပါ {user.first_name}!\n\n"
        "🔒 Subscription မရှိသေးပါ။\n\n"
        "💳 WEEKLY PLAN\n"
        "7 Days — 50,000 MMK\n\n"
        "🆔 YOUR USER ID\n"
        f"{user.id}\n\n"
        "Subscription activate လုပ်ရန် Admin ကို User ID ပို့ပေးပါ။\n"
        f"📩 Admin: {ADMIN_CONTACT}"
    )


async def subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if is_admin(user.id):
        await update.message.reply_text(
            "🛡 ADMIN ACCOUNT\n\n"
            "Admin account သည် license မလိုဘဲ အသုံးပြုနိုင်ပါတယ်."
        )
        return

    active, status, expires_at = check_license(user.id)

    if active:
        expiry_text = expires_at.strftime("%d-%m-%Y %H:%M UTC")
        await update.message.reply_text(
            "🟢 SUBSCRIPTION ACTIVE\n\n"
            f"Expire:\n{expiry_text}"
        )
    else:
        await update.message.reply_text(
            "🔴 SUBSCRIPTION INACTIVE\n\n"
            f"Status: {status.upper()}\n\n"
            "🆔 User ID:\n"
            f"{user.id}"
        )


async def activate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        await update.message.reply_text("⛔ ADMIN ONLY")
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "အသုံးပြုပုံ:\n/activate USER_ID DAYS\n\n"
            "ဥပမာ:\n/activate 123456789 7"
        )
        return

    try:
        target_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) >= 2 else 7
        if days <= 0:
            raise ValueError

        expiry = activate_user(target_id, days)
        expiry_text = expiry.strftime("%d-%m-%Y %H:%M UTC")

        await update.message.reply_text(
            "✅ LICENSE ACTIVATED\n\n"
            f"👤 User ID: {target_id}\n"
            f"📅 Days: {days}\n"
            f"⏳ Expire: {expiry_text}"
        )
    except ValueError:
        await update.message.reply_text("❌ USER_ID သို့မဟုတ် DAYS မှားနေပါတယ်.")


async def extend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        await update.message.reply_text("⛔ ADMIN ONLY")
        return

    if len(context.args) < 1:
        await update.message.reply_text(
            "အသုံးပြုပုံ:\n/extend USER_ID DAYS\n\n"
            "ဥပမာ:\n/extend 123456789 7"
        )
        return

    try:
        target_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) >= 2 else 7
        if days <= 0:
            raise ValueError

        expiry = extend_user(target_id, days)
        expiry_text = expiry.strftime("%d-%m-%Y %H:%M UTC")

        await update.message.reply_text(
            "✅ LICENSE EXTENDED\n\n"
            f"👤 User ID: {target_id}\n"
            f"➕ Added: {days} days\n"
            f"⏳ New Expire: {expiry_text}"
        )
    except ValueError:
        await update.message.reply_text("❌ USER_ID သို့မဟုတ် DAYS မှားနေပါတယ်.")


async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        await update.message.reply_text("⛔ ADMIN ONLY")
        return

    if len(context.args) != 1:
        await update.message.reply_text("အသုံးပြုပုံ:\n/block USER_ID")
        return

    try:
        target_id = int(context.args[0])
        block_user(target_id)
        await update.message.reply_text(
            "🚫 USER BLOCKED\n\n"
            f"👤 User ID: {target_id}"
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id

    if not is_admin(admin_id):
        await update.message.reply_text("⛔ ADMIN ONLY")
        return

    if len(context.args) != 1:
        await update.message.reply_text("အသုံးပြုပုံ:\n/status USER_ID")
        return

    try:
        target_id = int(context.args[0])
        user = get_user(target_id)

        if not user:
            await update.message.reply_text("❌ User ကို database ထဲမှာ မတွေ့ပါ.")
            return

        active, status, expires_at = check_license(target_id)
        expiry_text = (
            expires_at.strftime("%d-%m-%Y %H:%M UTC")
            if expires_at
            else "None"
        )
        username = user["username"]
        username_text = f"@{username}" if username else "None"

        await update.message.reply_text(
            "👤 USER STATUS\n\n"
            f"🆔 ID: {target_id}\n"
            f"👤 Name: {user['first_name']}\n"
            f"📱 Username: {username_text}\n"
            f"🔐 Status: {status.upper()}\n"
            f"⏳ Expire: {expiry_text}"
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID")


# =========================================================
# PHOTO HANDLER
# =========================================================

async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    register_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    if not is_admin(user.id):
        active, status, expires_at = check_license(user.id)
        if not active:
            await update.message.reply_text(
                "🔒 ACCESS DENIED\n\n"
                "Betting Bayin Subscription မရှိပါ သို့မဟုတ် သက်တမ်းကုန်နေပါပြီ.\n\n"
                "🆔 YOUR USER ID\n"
                f"{user.id}\n\n"
                "💳 7 Days — 50,000 MMK\n\n"
                f"📩 Admin: {ADMIN_CONTACT}"
            )
            return

    temp_path = None

    try:
        photo = update.message.photo[-1]
        telegram_file = await context.bot.get_file(photo.file_id)

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            temp_path = temp_file.name

        await telegram_file.download_to_drive(temp_path)

        # Do not send a waiting message. The user receives one final result only.
        extracted = await asyncio.to_thread(
            analyze_screenshot,
            temp_path,
        )

        result = await asyncio.to_thread(
            run_full_pipeline,
            extracted,
            False,
            False,
        )

        log_usage(user.id, "full_pipeline_analysis")

        reply = format_v13_tip(result)

        # Telegram message hard limit is 4096 chars.
        chunk_size = 3800
        for index in range(0, len(reply), chunk_size):
            await update.message.reply_text(
                reply[index:index + chunk_size]
            )

        print("\n========== BETTING BAYIN RESULT ==========")
        print(
            f"Match: {result.get('match', {}).get('home_team')} "
            f"vs {result.get('match', {}).get('away_team')}"
        )
        print(f"Decision: {result.get('decision')}")
        print(f"Reason: {result.get('reason')}")
        print("==========================================\n")

    except Exception as error:
        print("FULL PIPELINE ERROR:", repr(error))
        await update.message.reply_text(
            "❌ Analysis error ဖြစ်ပါတယ်.\n\n"
            f"Error: {type(error).__name__}\n"
            "နောက်တစ်ကြိမ် screenshot ကို ပြန်ပို့ကြည့်ပါ."
        )

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👑 BETTING BAYIN V13\n\n"
        "📸 1XBET Pre-Bet Screenshot ပို့ပေးပါ.\n\n"
        "🔐 Subscription စစ်ရန်:\n/subscription"
    )


# =========================================================
# MAIN
# =========================================================

def main():
    print("👑 BETTING BAYIN V13")
    print("🟢 Starting...")

    if ADMIN_USER_ID:
        print(f"🛡 Admin ID loaded: {ADMIN_USER_ID}")
    else:
        print("⚠️ ADMIN_USER_ID မသတ်မှတ်ရသေးပါ.")

    # Render Web Service requires an open HTTP port.
    start_health_server()

    # Telegram can be slow or intermittently blocked on some networks.
    bot_request = HTTPXRequest(
        connect_timeout=90.0,
        read_timeout=90.0,
        write_timeout=90.0,
        pool_timeout=60.0,
        connection_pool_size=8,
    )

    updates_request = HTTPXRequest(
        connect_timeout=90.0,
        read_timeout=120.0,
        write_timeout=90.0,
        pool_timeout=60.0,
        connection_pool_size=8,
    )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(bot_request)
        .get_updates_request(updates_request)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myid", myid))
    application.add_handler(CommandHandler("subscription", subscription))
    application.add_handler(CommandHandler("activate", activate_command))
    application.add_handler(CommandHandler("extend", extend_command))
    application.add_handler(CommandHandler("block", block_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    application.add_handler(
        MessageHandler(
            ~filters.PHOTO & ~filters.COMMAND,
            text_handler,
        )
    )

    print("✅ Betting Bayin ONLINE")
    print("📱 Open Telegram and send /start")

    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
            bootstrap_retries=-1,
            poll_interval=1.0,
            timeout=30,
        )
    except KeyboardInterrupt:
        print("\n🛑 Betting Bayin stopped by user.")
    except Exception as error:
        print("\n❌ Telegram polling stopped unexpectedly.")
        print(f"Error: {type(error).__name__}: {error}")
        raise


if __name__ == "__main__":
    main()