import os
import base64
import json
import tempfile
import asyncio
import threading
import html
import re
import time
import hashlib
import copy
import httpx
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
from match_reconcile import reconcile_album_extractions


# =========================================================
# SHWE OHH V20.5 PREBET STATE GUARD
# TELEGRAM BOT + FULL AI PIPELINE + RENDER HEALTH SERVER
# =========================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-5.4-mini").strip()
VISION_PROVIDER = os.getenv("VISION_PROVIDER", "auto").strip().lower()
OPENAI_VISION_TIMEOUT = float(os.getenv("OPENAI_VISION_TIMEOUT", "35"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_USER_ID_RAW = os.getenv("ADMIN_USER_ID", "").strip()
ADMIN_USER_IDS_RAW = os.getenv("ADMIN_USER_IDS", "").strip()
ADMIN_USERNAME_RAW = os.getenv("ADMIN_USERNAME", "shweohh_admin").strip()
VISION_MODEL = os.getenv("VISION_MODEL", "qwen/qwen3.6-27b")
PORT = int(os.getenv("PORT", "10000"))

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY မတွေ့ပါ")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN မတွေ့ပါ")

# Dual-admin support. Keep the original owner and the Shwe Ohh admin account.
DEFAULT_ADMIN_USER_IDS = {1051898916, 7806672181}
ADMIN_USER_IDS = set(DEFAULT_ADMIN_USER_IDS)
if ADMIN_USER_ID_RAW.isdigit():
    ADMIN_USER_IDS.add(int(ADMIN_USER_ID_RAW))
for raw_id in ADMIN_USER_IDS_RAW.replace(";", ",").split(","):
    raw_id = raw_id.strip()
    if raw_id.isdigit():
        ADMIN_USER_IDS.add(int(raw_id))

# Backward-compatible single value for older code/logging.
ADMIN_USER_ID = int(ADMIN_USER_ID_RAW) if ADMIN_USER_ID_RAW.isdigit() else None

ADMIN_USERNAME = ADMIN_USERNAME_RAW.lstrip("@").strip() or "shweohh_admin"
ADMIN_CONTACT = f"@{ADMIN_USERNAME}" if ADMIN_USERNAME else "Admin"

groq_client = Groq(api_key=GROQ_API_KEY)
init_database()


VISION_SYSTEM_PROMPT = """
You are the vision extraction engine for Shwe Ohh.

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
17. PRE-MATCH CLASSIFICATION IS CRITICAL: if the screenshot visibly says "Pre-match betting", "Pre-match", "Prematch", "Starts in", or shows a scheduled future kickoff date/time, classify it as PRE-MATCH.
18. A pre-match screen may display "(0-0), Pre-match betting". The 0-0 there is NOT a live score. Do not set live.is_live=true for that.
19. Never interpret a countdown such as "Starts in 00:03" or "Starts in 49:23" as a live match minute.
20. Set live.is_live=true only when the match is actually in play and the screenshot shows strong live evidence such as "Time elapsed", a running match minute, 1st-half/2nd-half live state, halftime, or an in-play score.
21. Set match_type to exactly one of: "pre_match", "live", or "unknown". If an explicit pre-match signal is visible, it overrides a displayed 0-0.

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
                "service": "Shwe Ohh",
                "version": "V20.5 PREBET STATE GUARD",
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
                "service": "Shwe Ohh",
                "version": "V20.5 PREBET STATE GUARD",
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
    try:
        return int(user_id) in ADMIN_USER_IDS
    except (TypeError, ValueError):
        return False


def image_to_data_url(image_path):
    with open(image_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{encoded}"


def _clean_vision_json(content):
    text = str(content or "").strip()
    text = text.replace("```json", "").replace("```JSON", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _make_safe_vision_copy(image_path):
    """Normalize unusually large/problematic Telegram images for a retry.

    Telegram albums can contain tall screenshots. Some otherwise valid image
    payloads can be rejected by the upstream vision endpoint with HTTP 400.
    This fallback keeps the original untouched and creates a conservative JPEG
    copy only when a retry is needed.
    """
    try:
        from PIL import Image, ImageOps
    except Exception:
        return None

    safe_path = None
    try:
        with Image.open(image_path) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            max_side = max(img.size)
            if max_side > 2400:
                scale = 2400.0 / float(max_side)
                img = img.resize(
                    (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as out:
                safe_path = out.name
            img.save(safe_path, format="JPEG", quality=88, optimize=True)
        return safe_path
    except Exception:
        if safe_path and os.path.exists(safe_path):
            try:
                os.remove(safe_path)
            except Exception:
                pass
        return None


def _vision_request(image_path, json_mode=True):
    image_url = image_to_data_url(image_path)
    kwargs = dict(
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
                        "text": (
                            "Read this betting screenshot and extract every visible betting detail. "
                            "Return JSON only."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ],
            },
        ],
        temperature=0,
        max_completion_tokens=4096,
        reasoning_effort="none",
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    response = groq_client.chat.completions.create(**kwargs)
    return _clean_vision_json(response.choices[0].message.content)


def analyze_screenshot(image_path):
    """Robust single-page extraction with safe retries.

    Attempt 1 uses the original Telegram image in JSON mode. If the vision API
    rejects that image with a BadRequest or returns malformed JSON, retry a
    normalized JPEG. A final retry removes response_format while keeping the
    prompt JSON-only.
    """
    errors = []
    safe_path = None
    try:
        for path, json_mode in [(image_path, True)]:
            try:
                return _vision_request(path, json_mode=json_mode)
            except Exception as error:
                errors.append(repr(error))

        safe_path = _make_safe_vision_copy(image_path)
        retry_path = safe_path or image_path

        for json_mode in (True, False):
            try:
                return _vision_request(retry_path, json_mode=json_mode)
            except Exception as error:
                errors.append(repr(error))

        raise RuntimeError("Vision extraction failed after retries: " + " | ".join(errors[-3:]))
    finally:
        if safe_path and os.path.exists(safe_path):
            try:
                os.remove(safe_path)
            except Exception:
                pass



# =========================================================
# V18 FAST VISION ROUTER / CACHE
# =========================================================

_VISION_CACHE = {}
_VISION_CACHE_LOCK = threading.Lock()
_VISION_CACHE_MAX = int(os.getenv("VISION_CACHE_MAX", "128"))

def _image_fingerprint(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def _cache_get(key):
    with _VISION_CACHE_LOCK:
        value = _VISION_CACHE.get(key)
        return copy.deepcopy(value) if value is not None else None

def _cache_put(key, value):
    with _VISION_CACHE_LOCK:
        if len(_VISION_CACHE) >= _VISION_CACHE_MAX:
            try:
                _VISION_CACHE.pop(next(iter(_VISION_CACHE)))
            except Exception:
                _VISION_CACHE.clear()
        _VISION_CACHE[key] = copy.deepcopy(value)

def _openai_extract_images(image_paths):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not configured")
    content = [{
        "type": "text",
        "text": (
            "These images are pages/screenshots for ONE football pre-bet fixture. "
            "Read ALL pages together, merge all visible markets and odds, preserve each market period, "
            "and return exactly one JSON object matching the system schema. Never invent hidden data. JSON only."
        ),
    }]
    for path in image_paths:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_data_url(path), "detail": "low"},
        })
    payload = {
        "model": OPENAI_VISION_MODEL,
        "messages": [
            {"role": "system", "content": VISION_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 3500,
    }
    with httpx.Client(timeout=OPENAI_VISION_TIMEOUT) as client:
        r = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
    return _clean_vision_json(data["choices"][0]["message"]["content"])

def analyze_images_fast(image_paths):
    """V18: one OpenAI request for a whole album; Groq parallel fallback."""
    paths = list(image_paths or [])
    if not paths:
        raise ValueError("No image paths")
    cache_key = "album:" + ":".join(_image_fingerprint(p) for p in paths)
    cached = _cache_get(cache_key)
    if cached is not None:
        cached["vision_provider"] = "cache"
        return cached

    errors = []
    use_openai = OPENAI_API_KEY and VISION_PROVIDER in {"auto", "openai"}
    if use_openai:
        try:
            started = time.perf_counter()
            result = _openai_extract_images(paths)
            result["vision_provider"] = "openai"
            result["vision_seconds"] = round(time.perf_counter() - started, 3)
            result["screenshots_merged"] = len(paths)
            _cache_put(cache_key, result)
            return result
        except Exception as e:
            errors.append(f"openai: {type(e).__name__}: {e}")
            print("OPENAI VISION FALLBACK:", errors[-1])
            if VISION_PROVIDER == "openai":
                raise

    # Existing Groq path remains a production fallback.
    started = time.perf_counter()
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(6, len(paths))) as pool:
        futures = [pool.submit(analyze_screenshot, p) for p in paths]
        extracted = []
        for idx, f in enumerate(futures, 1):
            try:
                extracted.append(f.result())
            except Exception as e:
                errors.append(f"groq page {idx}: {type(e).__name__}: {e}")
    if not extracted:
        raise RuntimeError("Vision failed: " + " | ".join(errors[-5:]))
    reconciled, identity_meta = reconcile_album_extractions(extracted)
    result = merge_extractions(reconciled)
    result["album_identity"] = identity_meta
    result["vision_provider"] = "groq"
    result["vision_seconds"] = round(time.perf_counter() - started, 3)
    result["vision_page_errors"] = errors
    result["screenshots_merged"] = len(paths)
    _cache_put(cache_key, result)
    return result


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
            "👑 SHWE OHH\n\n"
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
        "👑 SHWE OHH\n\n"
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
        "👑 SHWE OHH PRE-BET — FINAL\n\n"
        "📸 1XBET Pre-Bet Screenshot ပို့ပါ။\n"
        "🎯 အကောင်းဆုံး Single Tip တစ်ခုကို အလိုအလျောက်ရွေးပေးပါမယ်။\n"
        "💰 Final target: 1.80+ value odds\n"
        "🛡 Bookie Trap + Price Reality Guard: ACTIVE",
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
        "💳 SHWE OHH SUBSCRIPTION\n\n"
        "📦 WEEKLY PLAN\n"
        "7 Days — 20,000 MMK\n\n"
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
        "📖 SHWE OHH PRE-BET FINAL အသုံးပြုနည်း\n\n"
        "1️⃣ ▶️ Start ကိုနှိပ်ပါ။\n"
        "2️⃣ 1XBET Pre-Bet Match Screenshot ပို့ပါ။\n"
        "3️⃣ Bot က screenshot market + model-derived market universe ကိုယှဉ်ပြီး Single Tip တစ်ခုရွေးပေးပါမယ်။\n"
        "4️⃣ 1.80+ price discipline နဲ့ Bookie Trap / Price Reality Guard ကိုအသုံးပြုပါတယ်။\n\n"
        "⚠️ Live match screenshot မဟုတ်ဘဲ Pre-Bet screenshot ပို့ပါ။\n"
        "⚠️ FINAL release က Single Bet Only ဖြစ်ပါတယ်။",
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
            "👑 SHWE OHH PRE-BET\n\n"
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
            "👑 SHWE OHH PRE-BET\n\n"
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
        "👑 SHWE OHH\n\n"
        f"မင်္ဂလာပါ {safe_first_name}!\n\n"
        "🔒 Subscription မရှိသေးပါ။\n\n"
        "💳 WEEKLY PLAN\n"
        "7 Days — 20,000 MMK\n\n"
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
        "📊 SHWE OHH PERFORMANCE\n\n"
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

MEDIA_GROUP_WAIT_SECONDS = float(os.getenv("MEDIA_GROUP_WAIT_SECONDS", "0.55"))
MAX_SCREENSHOTS_PER_MATCH_BATCH = 8


def _match_group_key(extracted, fallback_index):
    match = extracted.get("match") or {}
    home = " ".join(str(match.get("home_team") or "").strip().lower().split())
    away = " ".join(str(match.get("away_team") or "").strip().lower().split())
    if home and away:
        return (home, away)
    # Never merge unreadable/unknown matches merely because names are missing.
    return ("__unknown__", str(fallback_index))


def _normalize_match_type_text(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _extract_numeric_minute(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    text = str(value).strip().lower()
    # Countdown-like clock values are not trusted as live minutes by themselves.
    if ":" in text:
        return None
    m = re.search(r"(?<!\d)(\d{1,3})(?:st|nd|rd|th)?\s*'?", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def _classify_extracted_match_state(extracted):
    """Return pre_match/live/unknown using conservative, explicit evidence.

    Vision models occasionally misread a pre-match countdown or the text
    "(0-0), Pre-match betting" as a live score.  For the PRE-BET bot, explicit
    bookmaker pre-match signals must override that false positive.
    """
    extracted = extracted or {}
    live = extracted.get("live", {}) or {}
    match_type = _normalize_match_type_text(extracted.get("match_type"))

    pre_tokens = (
        "pre match", "prematch", "pre bet", "prebet",
        "before match", "pre match betting", "pre betting",
    )
    live_tokens = (
        "live", "in play", "inplay", "time elapsed",
        "1st half", "first half", "2nd half", "second half", "halftime",
    )

    explicit_pre = any(token in match_type for token in pre_tokens)
    explicit_live = any(token in match_type for token in live_tokens) and not explicit_pre

    start_date = str(extracted.get("start_date") or "").strip()
    start_time = str(extracted.get("start_time") or "").strip()
    scheduled_kickoff_visible = bool(start_date or start_time)

    minute = _extract_numeric_minute(live.get("minute"))
    score = str(live.get("score") or "").strip()
    score_match = re.fullmatch(r"\s*(\d{1,2})\s*[-:]\s*(\d{1,2})\s*", score)
    nonzero_score = False
    if score_match:
        nonzero_score = int(score_match.group(1)) + int(score_match.group(2)) > 0

    # Hard pre-match override: explicit pre-match wording wins even if the vision
    # provider accidentally set is_live=True because it saw a decorative 0-0.
    if explicit_pre:
        return "pre_match"

    # A scheduled kickoff plus no genuine running minute is strong pre-match evidence.
    # This catches screenshots that show "Starts in ..." but the extractor only
    # retained the date/time fields.
    if scheduled_kickoff_visible and not explicit_live:
        return "pre_match"

    # Strong live evidence requires an actual running minute, or an explicit live
    # classification paired with in-play score/state.  A lone is_live boolean is
    # intentionally not enough because that was the false-positive source.
    if minute is not None and minute > 0:
        return "live"
    if explicit_live and (nonzero_score or bool(live.get("is_live"))):
        return "live"

    if bool(live.get("is_live")) and score_match and not scheduled_kickoff_visible:
        return "live"

    # In a PRE-BET-only bot, a screenshot with readable teams + markets but no
    # strong live evidence should be allowed through instead of being rejected.
    match = extracted.get("match", {}) or {}
    has_teams = bool(match.get("home_team") and match.get("away_team"))
    has_markets = bool(extracted.get("markets"))
    if has_teams and has_markets:
        return "pre_match"

    return "unknown"


def _normalize_extracted_prebet_state(extracted):
    state = _classify_extracted_match_state(extracted)
    extracted = dict(extracted or {})
    live = dict(extracted.get("live", {}) or {})
    extracted["match_type"] = state
    if state == "pre_match":
        live["is_live"] = False
        # A decorative pre-match 0-0/countdown must not leak into live logic.
        live["minute"] = None
        live["score"] = None
    extracted["live"] = live
    extracted["prebet_state_guard"] = {"classified_state": state}
    return extracted


async def _process_extracted_match(update, context, user, extracted):
    # V20.5: normalize vision state before rejecting anything as live.
    extracted = _normalize_extracted_prebet_state(extracted)
    state = extracted.get("match_type")
    if state == "live":
        await update.message.reply_text(
            "⚠️ SHWE OHH PRE-BET ONLY\n\n"
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

    print("\n========== SHWE OHH RESULT ==========")
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

        # V18 fast path: one multimodal request can read the entire album at once.
        # This removes N serial/parallel provider round-trips and preserves all visible pages.
        vision_started = time.perf_counter()
        merged = await asyncio.to_thread(analyze_images_fast, temp_paths)
        merged["screenshots_received"] = len(unique_ids)
        merged["screenshots_extracted"] = len(unique_ids)
        print(
            f"V18 VISION: provider={merged.get('vision_provider')} "
            f"pages={len(unique_ids)} seconds={time.perf_counter()-vision_started:.2f}"
        )
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
                "Shwe Ohh Subscription မရှိပါ သို့မဟုတ် သက်တမ်းကုန်နေပါပြီ.\n\n"
                "🆔 YOUR USER ID\n"
                f"{user.id}\n\n"
                "💳 7 Days — 20,000 MMK\n\n"
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
        # Debounce from the LAST received album page, not the first one.
        # This is both faster and safer for 3-8 screenshot albums.
        old_task = group.get("task")
        if old_task is not None and not old_task.done():
            old_task.cancel()
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

    # FINAL release is Single Bet Only. Keep legacy parlay code disabled.
    parlay_words = ("မောင်း", "တွဲ", "parlay", "accumulator", "acca", "combo")
    if any(word in low for word in parlay_words):
        await update.message.reply_text(
            "🎯 SHWE OHH PRE-BET FINAL က Single Bet Only ဖြစ်ပါတယ်။\n"
            "📸 Pre-Bet Screenshot တစ်ပွဲပို့ပြီး Single Tip ယူပါ။",
            reply_markup=main_menu_keyboard(),
        )
        return

    await update.message.reply_text(
        "👑 SHWE OHH PRE-BET\n\n"
        "အောက်က Menu ကနေ ရွေးချယ်နိုင်ပါတယ်။\n"
        "📸 Tip ယူရန် Pre-Bet Screenshot ကို တိုက်ရိုက်ပို့နိုင်ပါတယ်။",
        reply_markup=main_menu_keyboard(),
    )


# =========================================================
# MAIN
# =========================================================

def main():
    print("👑 SHWE OHH V20.5 PREBET STATE GUARD")
    print(f"⚡ Vision provider: {VISION_PROVIDER}; OpenAI configured: {bool(OPENAI_API_KEY)}")
    print("🟢 Starting...")

    print(f"🛡 Admin IDs loaded: {sorted(ADMIN_USER_IDS)}")
    print(f"📩 Public admin: {ADMIN_CONTACT}")

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

    print("✅ Shwe Ohh ONLINE")
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
        print("\n🛑 Shwe Ohh stopped by user.")
    except Exception as error:
        print("\n❌ Telegram polling stopped unexpectedly.")
        print(f"Error: {type(error).__name__}: {error}")
        raise


if __name__ == "__main__":
    main()