import os
import json
import math
import sqlite3
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

TRACKER_DATABASE_URL = (os.getenv("TRACKER_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
TRACKER_DB_PATH = os.getenv("TRACKER_DB_PATH", "shwe_ohh_testing.db").strip() or "shwe_ohh_testing.db"
PREBET_TEST_STAKE = float(os.getenv("PREBET_TEST_STAKE", "500") or 500)
LIVEBET_TEST_STAKE = float(os.getenv("LIVEBET_TEST_STAKE", "500") or 500)
TRACKER_CURRENCY = os.getenv("TRACKER_CURRENCY", "MMK").strip() or "MMK"

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:
    psycopg = None
    dict_row = None


def _now():
    return datetime.now(timezone.utc)


def _using_postgres():
    return bool(TRACKER_DATABASE_URL.startswith("postgres://") or TRACKER_DATABASE_URL.startswith("postgresql://"))


def _pg_conn():
    if not psycopg:
        raise RuntimeError("TRACKER_DATABASE_URL is PostgreSQL but psycopg is not installed")
    return psycopg.connect(TRACKER_DATABASE_URL, row_factory=dict_row)


def _sqlite_conn():
    c = sqlite3.connect(TRACKER_DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _execute(conn, sql, params=()):
    return conn.execute(sql, params)


def init_testing_tracker():
    if _using_postgres():
        with _pg_conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS testing_predictions(
                    id BIGSERIAL PRIMARY KEY,
                    source TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    user_id BIGINT,
                    home_team TEXT,
                    away_team TEXT,
                    competition TEXT,
                    period TEXT,
                    minute INTEGER,
                    score TEXT,
                    market TEXT,
                    selection TEXT,
                    family TEXT,
                    odds DOUBLE PRECISION,
                    target_odds DOUBLE PRECISION,
                    price_kind TEXT,
                    model_probability DOUBLE PRECISION,
                    trap_level TEXT,
                    grade TEXT,
                    tip_mode TEXT,
                    forced BOOLEAN DEFAULT FALSE,
                    availability_mode TEXT,
                    stake DOUBLE PRECISION NOT NULL DEFAULT 500,
                    currency TEXT NOT NULL DEFAULT 'MMK',
                    status TEXT NOT NULL DEFAULT 'pending',
                    profit DOUBLE PRECISION,
                    final_score TEXT,
                    notes TEXT,
                    raw_json TEXT,
                    fingerprint TEXT UNIQUE
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_testing_source_status ON testing_predictions(source,status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_testing_created_at ON testing_predictions(created_at DESC)")
        return

    with _sqlite_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS testing_predictions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                user_id INTEGER,
                home_team TEXT,
                away_team TEXT,
                competition TEXT,
                period TEXT,
                minute INTEGER,
                score TEXT,
                market TEXT,
                selection TEXT,
                family TEXT,
                odds REAL,
                target_odds REAL,
                price_kind TEXT,
                model_probability REAL,
                trap_level TEXT,
                grade TEXT,
                tip_mode TEXT,
                forced INTEGER DEFAULT 0,
                availability_mode TEXT,
                stake REAL NOT NULL DEFAULT 500,
                currency TEXT NOT NULL DEFAULT 'MMK',
                status TEXT NOT NULL DEFAULT 'pending',
                profit REAL,
                final_score TEXT,
                notes TEXT,
                raw_json TEXT,
                fingerprint TEXT UNIQUE
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_testing_source_status ON testing_predictions(source,status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_testing_created_at ON testing_predictions(created_at DESC)")


def _clean_float(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _clean_int(v):
    try:
        if v is None or v == "":
            return None
        return int(float(str(v).replace("'", "").strip()))
    except Exception:
        return None


def _family_from_market(market, explicit=None):
    if explicit:
        return str(explicit).strip().lower().replace(" ", "_")
    x = str(market or "").lower()
    if "corner" in x:
        return "corners"
    if "yellow" in x or "card" in x and "red" not in x:
        return "yellow_cards"
    if "red" in x and "card" in x:
        return "red_cards"
    if "double chance" in x:
        return "double_chance"
    if "draw no bet" in x or "dnb" in x:
        return "draw_no_bet"
    if "btts" in x or "both team" in x or "each team" in x:
        return "btts"
    if "handicap" in x:
        return "handicap"
    if "team" in x and "total" in x:
        return "team_total"
    if "total" in x or "over" in x or "under" in x:
        return "total"
    if "result" in x or "1x2" in x:
        return "result"
    return "other"


def _fingerprint(p):
    keys = [
        p.get("source"), p.get("user_id"), p.get("home_team"), p.get("away_team"),
        p.get("period"), p.get("minute"), p.get("score"), p.get("market"),
        p.get("selection"), p.get("odds"), p.get("target_odds"),
    ]
    raw = "|".join("" if x is None else str(x).strip().lower() for x in keys)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_prediction(payload):
    init_testing_tracker()
    p = dict(payload or {})
    p["source"] = str(p.get("source") or "unknown").lower()
    p["created_at"] = p.get("created_at") or _now()
    p["stake"] = _clean_float(p.get("stake")) or (PREBET_TEST_STAKE if p["source"] == "prebet" else LIVEBET_TEST_STAKE)
    p["currency"] = str(p.get("currency") or TRACKER_CURRENCY)
    p["status"] = str(p.get("status") or "pending").lower()
    p["forced"] = bool(p.get("forced"))
    p["odds"] = _clean_float(p.get("odds"))
    p["target_odds"] = _clean_float(p.get("target_odds"))
    p["model_probability"] = _clean_float(p.get("model_probability"))
    if p["model_probability"] is not None and p["model_probability"] > 1.0:
        p["model_probability"] /= 100.0
    p["minute"] = _clean_int(p.get("minute"))
    p["family"] = _family_from_market(p.get("market"), p.get("family"))
    p["fingerprint"] = p.get("fingerprint") or _fingerprint(p)
    raw_json = p.get("raw_json")
    if not isinstance(raw_json, str):
        raw_json = json.dumps(raw_json or {}, ensure_ascii=False, default=str)

    columns = [
        "source","created_at","user_id","home_team","away_team","competition","period","minute","score",
        "market","selection","family","odds","target_odds","price_kind","model_probability","trap_level",
        "grade","tip_mode","forced","availability_mode","stake","currency","status","profit","final_score",
        "notes","raw_json","fingerprint",
    ]
    values = [
        p.get("source"), p.get("created_at"), p.get("user_id"), p.get("home_team"), p.get("away_team"),
        p.get("competition"), p.get("period"), p.get("minute"), p.get("score"), p.get("market"), p.get("selection"),
        p.get("family"), p.get("odds"), p.get("target_odds"), p.get("price_kind"), p.get("model_probability"),
        p.get("trap_level"), p.get("grade"), p.get("tip_mode"), p.get("forced"), p.get("availability_mode"),
        p.get("stake"), p.get("currency"), p.get("status"), p.get("profit"), p.get("final_score"), p.get("notes"),
        raw_json, p.get("fingerprint"),
    ]

    if _using_postgres():
        with _pg_conn() as c:
            row = c.execute(
                f"INSERT INTO testing_predictions({','.join(columns)}) VALUES({','.join(['%s']*len(columns))}) "
                "ON CONFLICT(fingerprint) DO UPDATE SET fingerprint=EXCLUDED.fingerprint RETURNING id",
                values,
            ).fetchone()
            return int(row["id"]) if row else None
    with _sqlite_conn() as c:
        c.execute(
            f"INSERT OR IGNORE INTO testing_predictions({','.join(columns)}) VALUES({','.join(['?']*len(columns))})",
            [v.isoformat() if isinstance(v, datetime) else int(v) if isinstance(v, bool) else v for v in values],
        )
        row = c.execute("SELECT id FROM testing_predictions WHERE fingerprint=?", (p["fingerprint"],)).fetchone()
        return int(row["id"]) if row else None


def record_prebet_tip(user_id, result, extracted=None):
    result = result or {}
    extracted = extracted or result.get("extracted_data") or {}
    match = result.get("match") or {}
    em = extracted.get("match") or {}
    v13 = result.get("v13") or {}
    tip = v13.get("tip") or {}
    if not tip:
        return None
    odds_estimated = bool(tip.get("odds_estimated"))
    actual_odds = None if odds_estimated else _clean_float(tip.get("odds"))
    target = _clean_float(tip.get("minimum_acceptable_odds")) if odds_estimated else actual_odds
    market = tip.get("market_name") or tip.get("base_market_name") or "Market"
    payload = {
        "source": "prebet",
        "user_id": user_id,
        "home_team": match.get("home_team") or em.get("home_team"),
        "away_team": match.get("away_team") or em.get("away_team"),
        "competition": match.get("competition") or extracted.get("competition"),
        "period": tip.get("period") or "regular_time",
        "minute": None,
        "score": None,
        "market": market,
        "selection": tip.get("selection"),
        "family": tip.get("market_family") or tip.get("family"),
        "odds": actual_odds,
        "target_odds": target,
        "price_kind": "threshold" if odds_estimated else "actual",
        "model_probability": tip.get("model_probability"),
        "trap_level": tip.get("bookie_trap_level"),
        "grade": tip.get("grade"),
        "tip_mode": tip.get("tip_mode"),
        "forced": str(v13.get("status") or "").upper() == "FORCED_TIP",
        "availability_mode": "OUTSIDE_PRICE_CHECK" if odds_estimated else "SCREENSHOT_ODDS",
        "stake": PREBET_TEST_STAKE,
        "raw_json": {"result": result, "extracted": extracted},
    }
    return record_prediction(payload)


def record_live_tip(user_id, extracted, result):
    extracted = extracted or {}
    result = result or {}
    tip = result.get("tip") or {}
    if not tip:
        return None
    match = extracted.get("match") or {}
    actual_odds = _clean_float(tip.get("odds"))
    target = actual_odds if actual_odds is not None else _clean_float(tip.get("minimum_take_odds"))
    p = tip.get("decision_probability") or tip.get("p") or tip.get("raw_model_probability")
    payload = {
        "source": "livebet",
        "user_id": user_id,
        "home_team": match.get("home_team"),
        "away_team": match.get("away_team"),
        "competition": extracted.get("competition"),
        "period": result.get("period"),
        "minute": result.get("minute"),
        "score": result.get("score"),
        "market": tip.get("market"),
        "selection": tip.get("selection"),
        "family": tip.get("family"),
        "odds": actual_odds,
        "target_odds": target,
        "price_kind": "actual" if actual_odds is not None else "threshold",
        "model_probability": p,
        "trap_level": tip.get("bookie_trap_level"),
        "grade": tip.get("selection_tier"),
        "tip_mode": result.get("availability_mode"),
        "forced": bool(tip.get("forced_accuracy_fallback")),
        "availability_mode": result.get("availability_mode"),
        "stake": LIVEBET_TEST_STAKE,
        "raw_json": {"result": result, "extracted": extracted},
    }
    return record_prediction(payload)


def mark_replaced(prediction_id, note="Replaced by rerank"):
    if not prediction_id:
        return False
    return _update_status(prediction_id, "replaced", profit=0.0, notes=note)


def _update_status(prediction_id, status, profit=None, final_score=None, notes=None, odds=None):
    status = str(status or "").lower()
    if _using_postgres():
        with _pg_conn() as c:
            row = c.execute(
                "UPDATE testing_predictions SET status=%s,profit=%s,final_score=COALESCE(%s,final_score),notes=COALESCE(%s,notes),odds=COALESCE(%s,odds) WHERE id=%s RETURNING id",
                (status, profit, final_score, notes, odds, int(prediction_id)),
            ).fetchone()
            return bool(row)
    with _sqlite_conn() as c:
        cur = c.execute(
            "UPDATE testing_predictions SET status=?,profit=?,final_score=COALESCE(?,final_score),notes=COALESCE(?,notes),odds=COALESCE(?,odds) WHERE id=?",
            (status, profit, final_score, notes, odds, int(prediction_id)),
        )
        return cur.rowcount > 0


def get_prediction(prediction_id):
    init_testing_tracker()
    if _using_postgres():
        with _pg_conn() as c:
            row = c.execute("SELECT * FROM testing_predictions WHERE id=%s", (int(prediction_id),)).fetchone()
            return dict(row) if row else None
    with _sqlite_conn() as c:
        row = c.execute("SELECT * FROM testing_predictions WHERE id=?", (int(prediction_id),)).fetchone()
        return dict(row) if row else None


def settle_prediction(prediction_id, outcome, actual_odds=None, final_score=None, notes=None):
    row = get_prediction(prediction_id)
    if not row:
        return None
    outcome = str(outcome or "").strip().lower().replace(" ", "_")
    aliases = {"w":"win","l":"loss","p":"push","void":"void","halfwin":"half_win","halfloss":"half_loss"}
    outcome = aliases.get(outcome, outcome)
    if outcome not in {"win","loss","push","void","half_win","half_loss"}:
        raise ValueError("Outcome must be win/loss/push/void/half_win/half_loss")
    stake = _clean_float(row.get("stake")) or 0.0
    odds = _clean_float(actual_odds) or _clean_float(row.get("odds"))
    if outcome == "loss":
        profit = -stake
    elif outcome == "half_loss":
        profit = -0.5 * stake
    elif outcome in {"push","void"}:
        profit = 0.0
    elif odds is None:
        profit = None
    elif outcome == "win":
        profit = stake * (odds - 1.0)
    else:
        profit = 0.5 * stake * (odds - 1.0)
    _update_status(prediction_id, outcome, profit=profit, final_score=final_score, notes=notes, odds=odds)
    return get_prediction(prediction_id)


def _fetch_rows(source=None, status=None, limit=500):
    init_testing_tracker()
    where, params = [], []
    placeholder = "%s" if _using_postgres() else "?"
    if source and source != "all":
        where.append(f"source={placeholder}")
        params.append(source)
    if status and status != "all":
        where.append(f"status={placeholder}")
        params.append(status)
    sql = "SELECT * FROM testing_predictions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT " + str(max(1, min(int(limit or 500), 5000)))
    if _using_postgres():
        with _pg_conn() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]
    with _sqlite_conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def list_predictions(source=None, status=None, limit=200):
    rows = _fetch_rows(source, status, limit)
    for r in rows:
        dt = r.get("created_at")
        if isinstance(dt, datetime):
            r["created_at"] = dt.isoformat()
        r.pop("raw_json", None)
    return rows


def _outcome_value(status):
    return {"win":1.0,"half_win":0.5,"half_loss":0.0,"loss":0.0}.get(status)


def _summarize_rows(rows):
    valid = [r for r in rows if r.get("status") != "replaced"]
    settled = [r for r in valid if r.get("status") in {"win","loss","push","void","half_win","half_loss"}]
    decisions = [r for r in settled if r.get("status") in {"win","loss","half_win","half_loss"}]
    weighted_wins = sum(1.0 if r.get("status") == "win" else 0.5 if r.get("status") == "half_win" else 0.0 for r in decisions)
    profit_rows = [r for r in settled if _clean_float(r.get("profit")) is not None]
    total_stake = sum(_clean_float(r.get("stake")) or 0.0 for r in profit_rows)
    profit = sum(_clean_float(r.get("profit")) or 0.0 for r in profit_rows)
    odds_vals = [_clean_float(r.get("odds")) for r in valid if _clean_float(r.get("odds"))]
    brier_items = []
    for r in decisions:
        p = _clean_float(r.get("model_probability"))
        y = _outcome_value(r.get("status"))
        if p is not None and y is not None:
            brier_items.append((p-y)**2)
    return {
        "total": len(valid),
        "pending": sum(1 for r in valid if r.get("status") == "pending"),
        "settled": len(settled),
        "wins": sum(1 for r in settled if r.get("status") == "win"),
        "losses": sum(1 for r in settled if r.get("status") == "loss"),
        "half_wins": sum(1 for r in settled if r.get("status") == "half_win"),
        "half_losses": sum(1 for r in settled if r.get("status") == "half_loss"),
        "pushes": sum(1 for r in settled if r.get("status") in {"push","void"}),
        "hit_rate": (weighted_wins / len(decisions)) if decisions else 0.0,
        "profit": profit,
        "roi": (profit / total_stake) if total_stake else 0.0,
        "staked": total_stake,
        "avg_odds": (sum(odds_vals)/len(odds_vals)) if odds_vals else None,
        "brier": (sum(brier_items)/len(brier_items)) if brier_items else None,
    }


def _band_odds(v):
    v = _clean_float(v)
    if v is None: return "Price check"
    if v < 1.30: return "<1.30"
    if v < 1.50: return "1.30–1.49"
    if v < 1.70: return "1.50–1.69"
    if v < 2.00: return "1.70–1.99"
    return "2.00+"


def _band_conf(v):
    v = _clean_float(v)
    if v is None: return "Unknown"
    if v < .55: return "<55%"
    if v < .65: return "55–64%"
    if v < .75: return "65–74%"
    if v < .85: return "75–84%"
    return "85%+"


def _breakdown(rows, key_fn, min_count=1, top=30):
    groups = {}
    for r in rows:
        if r.get("status") == "replaced":
            continue
        k = str(key_fn(r) or "Unknown")
        groups.setdefault(k, []).append(r)
    out = []
    for k, rs in groups.items():
        if len(rs) < min_count:
            continue
        s = _summarize_rows(rs)
        out.append({"name": k, **s})
    out.sort(key=lambda x: (x["settled"], x["hit_rate"], x["total"]), reverse=True)
    return out[:top]


def get_dashboard_data(source=None):
    rows = _fetch_rows(source, None, 5000)
    summary = _summarize_rows(rows)
    return {
        "generated_at": _now().isoformat(),
        "source": source or "all",
        "summary": summary,
        "progress": {
            "prebet": min(50, sum(1 for r in rows if r.get("source") == "prebet" and r.get("status") != "replaced")),
            "livebet": min(50, sum(1 for r in rows if r.get("source") == "livebet" and r.get("status") != "replaced")),
            "target": 50,
        },
        "by_source": _breakdown(rows, lambda r: r.get("source"), top=5),
        "by_market": _breakdown(rows, lambda r: r.get("family"), top=30),
        "by_league": _breakdown(rows, lambda r: r.get("competition"), top=30),
        "by_odds": _breakdown(rows, lambda r: _band_odds(r.get("odds") or r.get("target_odds")), top=10),
        "by_confidence": _breakdown(rows, lambda r: _band_conf(r.get("model_probability")), top=10),
        "by_trap": _breakdown(rows, lambda r: r.get("trap_level") or "Unknown", top=10),
        "recent": list_predictions(source=source, limit=100),
    }


def export_csv(source=None):
    import csv, io
    rows = list_predictions(source=source, limit=5000)
    fields = [
        "id","source","created_at","home_team","away_team","competition","period","minute","score","market",
        "selection","family","odds","target_odds","price_kind","model_probability","trap_level","grade","forced",
        "availability_mode","stake","currency","status","profit","final_score","notes",
    ]
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()
