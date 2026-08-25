import os
import base64
import json
import tempfile
import asyncio
import threading
import html
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv
from groq import Groq

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
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
    save_tip,
    get_recent_tips,
    get_performance_summary,
    get_tracking_counts,
    get_pending_predictions,
    settle_prediction_score,
    settle_prediction_manual,
)

from pipeline_engine import (
    run_full_pipeline,
    format_final_report,
)
from v13_engine import format_v13_tip
from parlay_engine import build_best_parlay, format_parlay
from result_tracker import check_pending_results, start_result_tracker
from screenshot_merge import merge_extractions


# =========================================================
# BETTING BAYIN V16.2 PRE-BET
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
10. For every market, identify the visible time scope: regular_time, 1st_half, 2nd_half, or unknown. Tabs/headers such as Regular time, 1st half and 2nd half determine this field.
11. Never mix Regular Time prices with 1st Half or 2nd Half prices.
12. Never guess hidden markets.
13. Return valid JSON only.
14. Do not output markdown.
15. Do not output explanations.
16. Do not output <think> tags.

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
      "period": "regular_time|1st_half|2nd_half|unknown",
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
                "version": "V16.2 PRE-BET",
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
                "version": "V16.2 PRE-BET",
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
        "x2": f"Double Chance - 2X (Draw or {away_team})",
        "2x": f"Double Chance - 2X (Draw or {away_team})",
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
# TELEGRAM MENU UI
# =========================================================

MENU_SUBSCRIBE = "💳 Subscription ဝယ်ယူရန်"
MENU_START = "▶️ Start"
MENU_BALANCE = "📊 လက်ကျန်စစ်ရန်"
MENU_ADMIN = "👨‍💻 Admin နှင့်ပြောရန်"
MENU_HELP = "📖 အသုံးပြုနည်း"


def main_menu_keyboard():
    """Persistent customer menu. Keep the betting engine separate from the UI layer."""
    return ReplyKeyboardMarkup(
        [
            [MENU_SUBSCRIBE],
            [MENU_START, MENU_BALANCE],
            [MENU_ADMIN, MENU_HELP],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Select an option...",
    )


def admin_inline_keyboard():
    if not ADMIN_USERNAME:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Admin Chat ဖွင့်ရန်", url=f"https://t.me/{ADMIN_USERNAME}")]
    ])


def remaining_subscription_text(expires_at):
    if not expires_at:
        return "0 ရက်"
    now = datetime.now(timezone.utc)
    expiry = expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    seconds = max(0, int((expiry - now).total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        return f"{days} ရက် {hours} နာရီ"
    if hours > 0:
        return f"{hours} နာရီ {minutes} မိနစ်"
    return f"{minutes} မိနစ်"


async def show_start_ready(update: Update):
    await update.message.reply_text(
        "👑 BETTING BAYIN PRE-BET\n\n"
        "📸 1XBET Pre-Bet Screenshot ပို့ပါ။\n"
        "🎯 Single Tip ကို အလိုအလျောက်ရွေးပေးပါမယ်။\n\n"
        "🔥 မောင်းတွဲချင်ရင် Screenshot တွေ တစ်ပွဲချင်းပို့ပြီး ၅ပွဲပြည့်တဲ့အခါ\n"
        "‘ခုနက 5 ပွဲကို မောင်းတွဲ’ လို့ပို့နိုင်ပါတယ်။\n"
        "၅ပွဲထဲမှ အကောင်းဆုံးပွဲများကိုရွေးချယ်ပြီးပြန်ပို့ပေးပါမယ်။",
        reply_markup=main_menu_keyboard(),
    )


async def show_balance(update: Update, user):
    if is_admin(user.id):
        await update.message.reply_text(
            "🛡 ADMIN ACCOUNT\n\nSubscription မလိုပါ။",
            reply_markup=main_menu_keyboard(),
        )
        return

    active, status, expires_at = check_license(user.id)
    if active:
        expiry_text = expires_at.strftime("%d-%m-%Y %H:%M UTC")
        await update.message.reply_text(
            "📊 SUBSCRIPTION လက်ကျန်\n\n"
            "🟢 Status: ACTIVE\n"
            f"⏳ လက်ကျန်: {remaining_subscription_text(expires_at)}\n"
            f"📅 Expire: {expiry_text}",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            "📊 SUBSCRIPTION လက်ကျန်\n\n"
            f"🔴 Status: {str(status).upper()}\n"
            "⏳ လက်ကျန်: 0 ရက်\n\n"
            "Subscription ဝယ်ယူလိုပါ <b>Subscription ဝယ်ယူရန်</b> ခလုတ်ကိုနှိပ်ပေးပါ။",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML",
        )


async def show_subscription_purchase(update: Update, user):
    await update.message.reply_text(
        "💳 BETTING BAYIN SUBSCRIPTION\n\n"
        "📦 WEEKLY PLAN\n"
        "7 Days — 50,000 MMK\n\n"
        "🆔 YOUR USER ID\n"
        f"{user.id}\n\n"
        "ငွေပေးချေမှုနဲ့ Activate လုပ်ရန် Admin ကို ဒီ User ID ပို့ပါ။\n"
        f"📩 Admin: {ADMIN_CONTACT}",
        reply_markup=admin_inline_keyboard(),
    )


async def show_admin_contact(update: Update):
    await update.message.reply_text(
        "👨‍💻 ADMIN SUPPORT\n\n"
        f"📩 {ADMIN_CONTACT}\n\n"
        "Subscription / Payment / Account ပြဿနာများကို Admin နှင့်ပြောနိုင်ပါတယ်။",
        reply_markup=admin_inline_keyboard(),
    )


async def show_help(update: Update):
    await update.message.reply_text(
        "📖 BETTING BAYIN အသုံးပြုနည်း\n\n"
        "1️⃣ ▶️ Start ကိုနှိပ်ပါ။\n"
        "2️⃣ 1XBET Pre-Bet Match Screenshot တစ်ပုံပို့ပါ။\n"
        "3️⃣ Bot က အကောင်းဆုံး Single Tip ကို ပြန်ပေးပါမယ်။\n"
        "4️⃣ မောင်းတွဲချင်ရင် Screenshot တွေ တစ်ပွဲချင်းပို့ပြီး ၅ပွဲပြည့်အောင်ပို့ပါ။\n"
        "5️⃣ ပြီးရင် ‘ခုနက 5 ပွဲကို မောင်းတွဲ’ လို့ပို့ပါ။\n\n"
        "⚠️ Live match screenshot မဟုတ်ဘဲ Pre-Bet screenshot ပို့ပါ။",
        reply_markup=main_menu_keyboard(),
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
            "👑 BETTING BAYIN PRE-BET\n\n"
            "🛡 ADMIN MODE\n\n"
            f"Admin ID: {user.id}\n\n"
            "COMMANDS\n"
            "👤 /myid\n"
            "➕ /activate USER_ID DAYS\n"
            "⏳ /extend USER_ID DAYS\n"
            "🚫 /block USER_ID\n"
            "🔎 /status USER_ID\n"
            "📊 /performance\n"
            "⏳ /pending\n"
            "🔎 /checkresults\n"
            "✅ /settle ID 2-1\n\n"
            "📸 Pre-match screenshot ပို့နိုင်ပါတယ်။",
            reply_markup=main_menu_keyboard(),
        )
        return

    active, status, expires_at = check_license(user.id)

    if active:
        expiry_text = expires_at.strftime("%d-%m-%Y %H:%M UTC")
        await update.message.reply_text(
            "👑 BETTING BAYIN PRE-BET\n\n"
            f"မင်္ဂလာပါ {user.first_name}!\n\n"
            "🟢 SUBSCRIPTION ACTIVE\n"
            f"⏳ လက်ကျန်: {remaining_subscription_text(expires_at)}\n"
            f"📅 Expire: {expiry_text}\n\n"
            "📸 1XBET Pre-Bet Screenshot ပို့နိုင်ပါပြီ။",
            reply_markup=main_menu_keyboard(),
        )
        return

    safe_first_name = html.escape(user.first_name or "User")
    await update.message.reply_text(
        "👑 BETTING BAYIN\n\n"
        f"မင်္ဂလာပါ {safe_first_name}!\n\n"
        "🔒 Subscription မရှိသေးပါ။\n\n"
        "💳 WEEKLY PLAN\n"
        "7 Days — 50,000 MMK\n\n"
        "🆔 YOUR USER ID\n"
        f"{user.id}\n\n"
        "Subscription ဝယ်ယူလိုပါ <b>Subscription ဝယ်ယူရန်</b> ခလုတ်ကိုနှိပ်ပေးပါ။",
        reply_markup=main_menu_keyboard(),
        parse_mode="HTML",
    )


async def subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_balance(update, update.effective_user)


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
# RESULT TRACKING / PERFORMANCE ADMIN COMMANDS
# =========================================================

async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ADMIN ONLY")
        return
    summary = await asyncio.to_thread(get_performance_summary)
    counts = await asyncio.to_thread(get_tracking_counts)
    await update.message.reply_text(
        "📊 BETTING BAYIN PERFORMANCE\n\n"
        f"✅ Settled: {summary['total_settled']}\n"
        f"🟢 Win: {summary['wins']}\n"
        f"🔴 Loss: {summary['losses']}\n"
        f"⚪ Void: {summary['voids']}\n"
        f"🎯 Hit Rate: {summary['hit_rate'] * 100:.1f}%\n"
        f"📐 Brier Score: {summary['brier_score']:.3f}\n\n"
        f"💰 Actual-Odds Bets: {summary['actual_odds_bets']}\n"
        f"📈 Profit: {summary['profit_units']:+.2f} units\n"
        f"💹 ROI: {summary['roi'] * 100:+.1f}%\n\n"
        f"🧠 Active Calibration Keys: {summary['calibration_active_keys']}\n"
        f"🧠 Active Market Families: {summary['calibration_active_families']}\n"
        f"⏳ Pending: {counts.get('pending', 0)} | Unresolved: {counts.get('unresolved', 0)}"
    )


async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ADMIN ONLY")
        return
    rows = await asyncio.to_thread(get_pending_predictions, 10, 0.0, 0.0, True)
    if not rows:
        await update.message.reply_text("✅ Pending prediction မရှိပါ။")
        return
    lines = ["⏳ PENDING RESULT CHECKS", ""]
    for row in rows:
        lines.append(
            f"#{row['id']} ⚽ {row.get('home_team')} vs {row.get('away_team')}\n"
            f"🎯 {row.get('market_name')} — {row.get('selection')}\n"
            f"📅 {row.get('match_date_text') or 'N/A'}"
        )
        lines.append("")
    lines.append("Manual score: /settle ID 2-1\nManual override: /settle ID win|loss|void")
    await update.message.reply_text("\n".join(lines)[:3900])


async def checkresults_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ADMIN ONLY")
        return
    await update.message.reply_text("🔎 Pending results စစ်နေပါတယ်…")
    summary = await asyncio.to_thread(check_pending_results, 10, True)
    await update.message.reply_text(
        "📊 RESULT CHECK COMPLETE\n\n"
        f"🔎 Checked: {summary.get('checked', 0)}\n"
        f"✅ Settled: {summary.get('settled', 0)}\n"
        f"⚠️ Unresolved: {summary.get('unresolved', 0)}"
    )


async def settle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ ADMIN ONLY")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "အသုံးပြုပုံ:\n/settle ID 2-1\n/settle ID win|loss|void"
        )
        return
    try:
        prediction_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid prediction ID")
        return

    value = str(context.args[1]).strip().lower().replace("–", "-")
    try:
        if value in {"win", "loss", "void"}:
            row = await asyncio.to_thread(settle_prediction_manual, prediction_id, value)
        else:
            import re
            m = re.fullmatch(r"(\d+)\s*[-:]\s*(\d+)", value)
            if not m:
                raise ValueError("Use score like 2-1 or win/loss/void")
            row = await asyncio.to_thread(
                settle_prediction_score,
                prediction_id,
                int(m.group(1)),
                int(m.group(2)),
                "admin_score",
                1.0,
            )
        if not row:
            await update.message.reply_text("❌ Prediction ID မတွေ့ပါ။")
            return
        await update.message.reply_text(
            f"✅ #{prediction_id} → {str(row.get('result_status')).upper()}\n"
            f"⚽ {row.get('home_team')} vs {row.get('away_team')}\n"
            f"🎯 {row.get('market_name')} — {row.get('selection')}"
        )
    except Exception as error:
        await update.message.reply_text(f"❌ Settle error: {error}")


# =========================================================
# PHOTO HANDLER
# =========================================================

MEDIA_GROUP_WAIT_SECONDS = 2.5
MAX_SCREENSHOTS_PER_MATCH_BATCH = 8


def _match_group_key(extracted, fallback_index):
    match = extracted.get("match") or {}
    home = " ".join(str(match.get("home_team") or "").strip().lower().split())
    away = " ".join(str(match.get("away_team") or "").strip().lower().split())
    if home and away:
        return (home, away)
    # Never merge unreadable/unknown matches merely because names are missing.
    return ("__unknown__", str(fallback_index))


async def _process_extracted_match(update, context, user, extracted):
    # Final Pre-Bet release: never analyze a live screenshot as pre-match.
    live = extracted.get("live", {}) or {}
    match_type = str(extracted.get("match_type") or "").strip().lower()
    if bool(live.get("is_live")) or "live" in match_type:
        await update.message.reply_text(
            "⚠️ BETTING BAYIN PRE-BET ONLY\n\n"
            "Live match screenshot မဟုတ်ဘဲ ပွဲမစခင် Pre-Bet screenshot ပို့ပေးပါ။"
        )
        return

    result = await asyncio.to_thread(
        run_full_pipeline,
        extracted,
        False,
        False,
    )

    log_usage(user.id, "full_pipeline_analysis")
    await asyncio.to_thread(save_tip, user.id, result)

    reply = format_v13_tip(result)
    chunk_size = 3800
    for index in range(0, len(reply), chunk_size):
        await update.message.reply_text(reply[index:index + chunk_size])

    print("\n========== BETTING BAYIN RESULT ==========")
    print(
        f"Match: {result.get('match', {}).get('home_team')} "
        f"vs {result.get('match', {}).get('away_team')}"
    )
    print(f"Decision: {result.get('decision')}")
    print(f"Reason: {result.get('reason')}")
    print(f"Screenshots merged: {extracted.get('screenshots_merged', 1)}")
    print("==========================================\n")


async def _process_photo_file_ids(update, context, file_ids):
    """Download, read and merge all screenshots before choosing one tip.

    Telegram albums arrive as separate updates with the same media_group_id.
    V16.2 waits briefly, reads every page, merges all visible markets/odds for
    the same match, then runs the prediction once. If an album contains several
    different matches, each match is analyzed separately rather than mixed.
    """
    user = update.effective_user
    temp_paths = []

    try:
        # Stable de-dup and a defensive cap.
        unique_ids = []
        seen = set()
        for file_id in file_ids:
            if file_id and file_id not in seen:
                seen.add(file_id)
                unique_ids.append(file_id)
        unique_ids = unique_ids[:MAX_SCREENSHOTS_PER_MATCH_BATCH]

        for file_id in unique_ids:
            telegram_file = await context.bot.get_file(file_id)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
                temp_path = temp_file.name
            temp_paths.append(temp_path)
            await telegram_file.download_to_drive(temp_path)

        # Accuracy first: extract every screenshot. This ensures Total/Handicap/
        # other pages sent in the same Telegram album are not silently ignored.
        extractions = []
        for temp_path in temp_paths:
            extractions.append(await asyncio.to_thread(analyze_screenshot, temp_path))

        # Group by match identity. Same-match pages are merged; different matches
        # in one album remain independent.
        groups = {}
        order = []
        for idx, extracted in enumerate(extractions):
            key = _match_group_key(extracted, idx)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(extracted)

        for key in order:
            merged = merge_extractions(groups[key])
            await _process_extracted_match(update, context, user, merged)

    except Exception as error:
        print("FULL PIPELINE ERROR:", repr(error))
        await update.message.reply_text(
            "❌ Analysis error ဖြစ်ပါတယ်.\n\n"
            f"Error: {type(error).__name__}\n"
            "Screenshot ကို ပြန်ပို့ကြည့်ပါ။"
        )
    finally:
        for temp_path in temp_paths:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass


async def _process_media_group_after_delay(application, group_key):
    await asyncio.sleep(MEDIA_GROUP_WAIT_SECONDS)
    groups = application.bot_data.setdefault("photo_media_groups", {})
    group = groups.pop(group_key, None)
    if not group:
        return
    await _process_photo_file_ids(
        group["update"],
        group["context"],
        group["file_ids"],
    )


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

    photo = update.message.photo[-1]
    media_group_id = update.message.media_group_id

    if media_group_id:
        # Telegram sends an album as separate updates. Buffer by media_group_id
        # and analyze only once after all pages have arrived.
        groups = context.application.bot_data.setdefault("photo_media_groups", {})
        group_key = f"{update.effective_chat.id}:{user.id}:{media_group_id}"
        group = groups.get(group_key)
        if group is None:
            group = {
                "file_ids": [],
                "update": update,
                "context": context,
                "task": None,
            }
            groups[group_key] = group
        group["update"] = update
        group["context"] = context
        if photo.file_id not in group["file_ids"]:
            group["file_ids"].append(photo.file_id)
        if group.get("task") is None or group["task"].done():
            group["task"] = asyncio.create_task(
                _process_media_group_after_delay(context.application, group_key)
            )
        return

    await _process_photo_file_ids(update, context, [photo.file_id])


async def _build_parlay_reply(user_id, text):
    # Accept natural language such as: "ခုနက ၅ ပွဲကို မောင်းတွဲ" / "last 5 parlay".
    raw = str(text or "")
    digit_map = str.maketrans("၀၁၂၃၄၅၆၇၈၉", "0123456789")
    normalized = raw.translate(digit_map).lower()

    import re
    match = re.search(r"\b(\d{1,2})\b", normalized)
    pool_size = int(match.group(1)) if match else 5
    pool_size = max(2, min(pool_size, 10))

    rows = await asyncio.to_thread(get_recent_tips, user_id, pool_size)
    parlay = build_best_parlay(rows, requested_pool_size=pool_size)
    return format_parlay(parlay)


async def parlay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        active, status, expires_at = check_license(user.id)
        if not active:
            await update.message.reply_text("🔒 Subscription မရှိပါ သို့မဟုတ် သက်တမ်းကုန်နေပါပြီ။")
            return
    text = " ".join(context.args) if context.args else "5"
    await update.message.reply_text(await _build_parlay_reply(user.id, text))


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = str(update.message.text or "").strip()
    low = text.lower()

    register_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    # Persistent keyboard actions
    if text == MENU_START or low == "start":
        await show_start_ready(update)
        return
    if text == MENU_BALANCE:
        await show_balance(update, user)
        return
    if text == MENU_SUBSCRIBE:
        await show_subscription_purchase(update, user)
        return
    if text == MENU_ADMIN:
        await show_admin_contact(update)
        return
    if text == MENU_HELP:
        await show_help(update)
        return

    # Natural-language parlay workflow remains unchanged.
    parlay_words = ("မောင်း", "တွဲ", "parlay", "accumulator", "acca", "combo")
    if any(word in low for word in parlay_words):
        if not is_admin(user.id):
            active, status, expires_at = check_license(user.id)
            if not active:
                await update.message.reply_text(
                    "🔒 Subscription မရှိပါ သို့မဟုတ် သက်တမ်းကုန်နေပါပြီ။",
                    reply_markup=main_menu_keyboard(),
                )
                return
        await update.message.reply_text(await _build_parlay_reply(user.id, text), reply_markup=main_menu_keyboard())
        return

    await update.message.reply_text(
        "👑 BETTING BAYIN PRE-BET\n\n"
        "အောက်က Menu ကနေ ရွေးချယ်နိုင်ပါတယ်။\n"
        "📸 Tip ယူရန် Pre-Bet Screenshot ကို တိုက်ရိုက်ပို့နိုင်ပါတယ်။",
        reply_markup=main_menu_keyboard(),
    )


# =========================================================
# MAIN
# =========================================================

def main():
    print("👑 BETTING BAYIN PRE-BET MENU")
    print("🟢 Starting...")

    if ADMIN_USER_ID:
        print(f"🛡 Admin ID loaded: {ADMIN_USER_ID}")
    else:
        print("⚠️ ADMIN_USER_ID မသတ်မှတ်ရသေးပါ.")

    # Render Web Service requires an open HTTP port.
    start_health_server()
    # V16 result tracking runs independently and never blocks Telegram replies.
    start_result_tracker(interval_seconds=3600)

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
    application.add_handler(CommandHandler("parlay", parlay_command))
    application.add_handler(CommandHandler("performance", performance_command))
    application.add_handler(CommandHandler("pending", pending_command))
    application.add_handler(CommandHandler("checkresults", checkresults_command))
    application.add_handler(CommandHandler("settle", settle_command))
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