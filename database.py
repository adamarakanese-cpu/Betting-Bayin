import os
import sqlite3
from datetime import datetime, timezone, timedelta
from result_engine import build_prediction_key, market_family, market_period, calibration_key, settle_market

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("SQLITE_DB_PATH", "betting_bayin.db")

USING_POSTGRES = bool(DATABASE_URL)

if USING_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row


def utc_now():
    return datetime.now(timezone.utc)


def _sqlite_conn():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _pg_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_database():
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        telegram_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        status TEXT NOT NULL DEFAULT 'inactive',
                        expires_at TIMESTAMPTZ,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS usage_logs (
                        id BIGSERIAL PRIMARY KEY,
                        telegram_id BIGINT NOT NULL,
                        action TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
        return

    with _sqlite_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                status TEXT NOT NULL DEFAULT 'inactive',
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def register_user(telegram_id, username=None, first_name=None):
    """Create/update identity WITHOUT resetting subscription status or expiry."""
    now = utc_now()

    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (telegram_id, username, first_name, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (telegram_id) DO UPDATE SET
                        username = EXCLUDED.username,
                        first_name = EXCLUDED.first_name,
                        updated_at = EXCLUDED.updated_at
                """, (telegram_id, username, first_name, now, now))
        return

    with _sqlite_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT telegram_id FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        exists = cur.fetchone()
        if exists:
            cur.execute("""
                UPDATE users
                SET username = ?, first_name = ?, updated_at = ?
                WHERE telegram_id = ?
            """, (username, first_name, now.isoformat(), telegram_id))
        else:
            cur.execute("""
                INSERT INTO users (
                    telegram_id, username, first_name, status,
                    expires_at, created_at, updated_at
                )
                VALUES (?, ?, ?, 'inactive', NULL, ?, ?)
            """, (
                telegram_id, username, first_name,
                now.isoformat(), now.isoformat()
            ))
        conn.commit()


def get_user(telegram_id):
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
                return cur.fetchone()

    with _sqlite_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def _ensure_user(telegram_id):
    if not get_user(telegram_id):
        register_user(telegram_id)


def activate_user(telegram_id, days=7):
    _ensure_user(telegram_id)
    expiry = utc_now() + timedelta(days=days)

    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                    SET status='active', expires_at=%s, updated_at=%s
                    WHERE telegram_id=%s
                """, (expiry, utc_now(), telegram_id))
        return expiry

    with _sqlite_conn() as conn:
        conn.execute("""
            UPDATE users
            SET status='active', expires_at=?, updated_at=?
            WHERE telegram_id=?
        """, (expiry.isoformat(), utc_now().isoformat(), telegram_id))
        conn.commit()
    return expiry


def extend_user(telegram_id, days=7):
    _ensure_user(telegram_id)
    active, status, expires_at = check_license(telegram_id)
    base = expires_at if active and expires_at else utc_now()
    expiry = base + timedelta(days=days)

    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                    SET status='active', expires_at=%s, updated_at=%s
                    WHERE telegram_id=%s
                """, (expiry, utc_now(), telegram_id))
        return expiry

    with _sqlite_conn() as conn:
        conn.execute("""
            UPDATE users
            SET status='active', expires_at=?, updated_at=?
            WHERE telegram_id=?
        """, (expiry.isoformat(), utc_now().isoformat(), telegram_id))
        conn.commit()
    return expiry


def block_user(telegram_id):
    _ensure_user(telegram_id)

    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                    SET status='blocked', updated_at=%s
                    WHERE telegram_id=%s
                """, (utc_now(), telegram_id))
        return

    with _sqlite_conn() as conn:
        conn.execute("""
            UPDATE users
            SET status='blocked', updated_at=?
            WHERE telegram_id=?
        """, (utc_now().isoformat(), telegram_id))
        conn.commit()


def check_license(telegram_id):
    user = get_user(telegram_id)
    if not user:
        return False, "inactive", None

    status = str(user.get("status") or "inactive").lower()
    raw_expiry = user.get("expires_at")

    if status == "blocked":
        return False, "blocked", None

    if not raw_expiry:
        return False, status, None

    if isinstance(raw_expiry, datetime):
        expiry = raw_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    else:
        try:
            expiry = datetime.fromisoformat(str(raw_expiry))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
        except Exception:
            return False, "inactive", None

    if status != "active":
        return False, status, expiry

    if expiry <= utc_now():
        # Persist expiry state, but do not delete the user.
        if USING_POSTGRES:
            with _pg_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE users SET status='expired', updated_at=%s
                        WHERE telegram_id=%s
                    """, (utc_now(), telegram_id))
        else:
            with _sqlite_conn() as conn:
                conn.execute("""
                    UPDATE users SET status='expired', updated_at=?
                    WHERE telegram_id=?
                """, (utc_now().isoformat(), telegram_id))
                conn.commit()
        return False, "expired", expiry

    return True, "active", expiry


def log_usage(telegram_id, action):
    now = utc_now()
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO usage_logs (telegram_id, action, created_at)
                    VALUES (%s, %s, %s)
                """, (telegram_id, action, now))
        return

    with _sqlite_conn() as conn:
        conn.execute("""
            INSERT INTO usage_logs (telegram_id, action, created_at)
            VALUES (?, ?, ?)
        """, (telegram_id, action, now.isoformat()))
        conn.commit()


init_database()
# =========================================================
# PERSISTENT TIP HISTORY (Single -> Parlay workflow)
# =========================================================

def _ensure_tip_history_table():
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tip_history (
                        id BIGSERIAL PRIMARY KEY,
                        telegram_id BIGINT NOT NULL,
                        home_team TEXT NOT NULL,
                        away_team TEXT NOT NULL,
                        competition TEXT,
                        market_name TEXT NOT NULL,
                        selection TEXT NOT NULL,
                        odds DOUBLE PRECISION,
                        odds_estimated BOOLEAN NOT NULL DEFAULT FALSE,
                        estimated_odds_low DOUBLE PRECISION,
                        estimated_odds_high DOUBLE PRECISION,
                        model_probability DOUBLE PRECISION NOT NULL,
                        evidence_confidence DOUBLE PRECISION,
                        ranking_score DOUBLE PRECISION,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_tip_history_user_time
                    ON tip_history (telegram_id, created_at DESC)
                """)
        return

    with _sqlite_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tip_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                competition TEXT,
                market_name TEXT NOT NULL,
                selection TEXT NOT NULL,
                odds REAL,
                odds_estimated INTEGER NOT NULL DEFAULT 0,
                estimated_odds_low REAL,
                estimated_odds_high REAL,
                model_probability REAL NOT NULL,
                evidence_confidence REAL,
                ranking_score REAL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tip_history_user_time
            ON tip_history (telegram_id, created_at DESC)
        """)
        conn.commit()



def _stored_market_name(tip):
    market = str((tip or {}).get("market_name") or "").strip()
    period = str((tip or {}).get("period") or "regular_time").strip().lower()
    if not market:
        return market
    low = market.lower()
    if any(prefix in low for prefix in ("regular time", "1st half", "first half", "2nd half", "second half")):
        return market
    if period in {"1st_half", "first_half"}:
        return f"1st Half {market}"
    if period in {"2nd_half", "second_half"}:
        return f"2nd Half {market}"
    return f"Regular Time {market}"

def save_tip(telegram_id, result):
    """Persist the final tip shown to a user for later accumulator requests."""
    v13 = (result or {}).get("v13", {}) or {}
    tip = v13.get("tip") or {}
    if not tip:
        return False

    match = (result or {}).get("match", {}) or {}
    extracted = (result or {}).get("extracted_data", {}) or {}
    ematch = extracted.get("match", {}) or {}

    home = str(match.get("home_team") or ematch.get("home_team") or "").strip()
    away = str(match.get("away_team") or ematch.get("away_team") or "").strip()
    if not home or not away:
        return False

    row = (
        int(telegram_id),
        home,
        away,
        str(match.get("competition") or extracted.get("competition") or "").strip(),
        _stored_market_name(tip),
        str(tip.get("selection") or "").strip(),
        float(tip.get("odds") or 0.0),
        bool(tip.get("odds_estimated")),
        float(tip.get("estimated_odds_low")) if tip.get("estimated_odds_low") is not None else None,
        float(tip.get("estimated_odds_high")) if tip.get("estimated_odds_high") is not None else None,
        float(tip.get("model_probability") or 0.0),
        float(tip.get("evidence_confidence") or 0.0),
        float(tip.get("ranking_score") or 0.0),
    )

    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tip_history (
                        telegram_id, home_team, away_team, competition,
                        market_name, selection, odds, odds_estimated,
                        estimated_odds_low, estimated_odds_high,
                        model_probability, evidence_confidence, ranking_score
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, row)
        _save_prediction_safe(result)
        return True

    with _sqlite_conn() as conn:
        conn.execute("""
            INSERT INTO tip_history (
                telegram_id, home_team, away_team, competition,
                market_name, selection, odds, odds_estimated,
                estimated_odds_low, estimated_odds_high,
                model_probability, evidence_confidence, ranking_score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, row + (utc_now().isoformat(),))
        conn.commit()
    _save_prediction_safe(result)
    return True


def get_recent_tips(telegram_id, limit=5):
    limit = max(2, min(int(limit or 5), 10))
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM tip_history
                    WHERE telegram_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                """, (int(telegram_id), limit))
                rows = cur.fetchall() or []
                return [dict(r) for r in reversed(rows)]

    with _sqlite_conn() as conn:
        cur = conn.execute("""
            SELECT * FROM tip_history
            WHERE telegram_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """, (int(telegram_id), limit))
        rows = [dict(r) for r in cur.fetchall()]
        return list(reversed(rows))


def clear_tip_history(telegram_id):
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM tip_history WHERE telegram_id = %s", (int(telegram_id),))
        return
    with _sqlite_conn() as conn:
        conn.execute("DELETE FROM tip_history WHERE telegram_id = ?", (int(telegram_id),))
        conn.commit()


_ensure_tip_history_table()


# =========================================================
# VERIFIED RESULT TRACKING + PERFORMANCE CALIBRATION (V16)
# =========================================================

def _ensure_result_tracking_table():
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS prediction_results (
                        id BIGSERIAL PRIMARY KEY,
                        prediction_key TEXT UNIQUE NOT NULL,
                        home_team TEXT NOT NULL,
                        away_team TEXT NOT NULL,
                        competition TEXT,
                        match_date_text TEXT,
                        start_time_text TEXT,
                        market_name TEXT NOT NULL,
                        selection TEXT NOT NULL,
                        market_family TEXT NOT NULL,
                        calibration_key TEXT NOT NULL,
                        odds DOUBLE PRECISION,
                        odds_estimated BOOLEAN NOT NULL DEFAULT FALSE,
                        model_probability DOUBLE PRECISION NOT NULL,
                        evidence_confidence DOUBLE PRECISION,
                        ranking_score DOUBLE PRECISION,
                        result_status TEXT NOT NULL DEFAULT 'pending',
                        final_home_score INTEGER,
                        final_away_score INTEGER,
                        result_source TEXT,
                        result_confidence DOUBLE PRECISION,
                        settlement_note TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_checked_at TIMESTAMPTZ,
                        settled_at TIMESTAMPTZ
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_prediction_results_pending
                    ON prediction_results (result_status, created_at, last_checked_at)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_prediction_results_calibration
                    ON prediction_results (calibration_key, result_status)
                """)
        return

    with _sqlite_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prediction_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_key TEXT UNIQUE NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                competition TEXT,
                match_date_text TEXT,
                start_time_text TEXT,
                market_name TEXT NOT NULL,
                selection TEXT NOT NULL,
                market_family TEXT NOT NULL,
                calibration_key TEXT NOT NULL,
                odds REAL,
                odds_estimated INTEGER NOT NULL DEFAULT 0,
                model_probability REAL NOT NULL,
                evidence_confidence REAL,
                ranking_score REAL,
                result_status TEXT NOT NULL DEFAULT 'pending',
                final_home_score INTEGER,
                final_away_score INTEGER,
                result_source TEXT,
                result_confidence REAL,
                settlement_note TEXT,
                created_at TEXT NOT NULL,
                last_checked_at TEXT,
                settled_at TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_prediction_results_pending
            ON prediction_results (result_status, created_at, last_checked_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_prediction_results_calibration
            ON prediction_results (calibration_key, result_status)
        """)
        conn.commit()


def _prediction_payload(result):
    v13 = (result or {}).get("v13", {}) or {}
    tip = v13.get("tip") or {}
    if not tip:
        return None
    match = (result or {}).get("match", {}) or {}
    extracted = (result or {}).get("extracted_data", {}) or {}
    ematch = extracted.get("match", {}) or {}
    home = str(match.get("home_team") or ematch.get("home_team") or "").strip()
    away = str(match.get("away_team") or ematch.get("away_team") or "").strip()
    if not home or not away:
        return None
    competition = str(match.get("competition") or extracted.get("competition") or "").strip()
    match_date = str(extracted.get("start_date") or "").strip()
    # If the screenshot omits the date, use the analysis day to avoid collisions
    # when the same clubs meet again in a later fixture.
    key_date = match_date or utc_now().strftime("%Y-%m-%d")
    start_time = str(extracted.get("start_time") or "").strip()
    market = _stored_market_name(tip)
    selection = str(tip.get("selection") or "").strip()
    if not market or not selection:
        return None
    pkey = build_prediction_key(home, away, competition, key_date, market, selection)
    return {
        "prediction_key": pkey,
        "home_team": home,
        "away_team": away,
        "competition": competition,
        "match_date_text": match_date,
        "start_time_text": start_time,
        "market_name": market,
        "selection": selection,
        "market_family": (
            market_family(market)
            if market_period(market) == "regular_time"
            else f"{market_period(market)}:{market_family(market)}"
        ),
        "calibration_key": calibration_key(market, selection),
        "odds": float(tip.get("odds") or 0.0),
        "odds_estimated": bool(tip.get("odds_estimated")),
        "model_probability": float(tip.get("model_probability") or 0.0),
        "evidence_confidence": float(tip.get("evidence_confidence") or 0.0),
        "ranking_score": float(tip.get("ranking_score") or 0.0),
    }


def save_prediction_result(result):
    """Save one canonical prediction per match/market/selection.

    Repeated customer requests for the same prediction do not inflate the
    performance sample, because prediction_key is unique.
    """
    row = _prediction_payload(result)
    if not row:
        return False
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO prediction_results (
                        prediction_key, home_team, away_team, competition,
                        match_date_text, start_time_text, market_name, selection,
                        market_family, calibration_key, odds, odds_estimated,
                        model_probability, evidence_confidence, ranking_score
                    ) VALUES (
                        %(prediction_key)s, %(home_team)s, %(away_team)s, %(competition)s,
                        %(match_date_text)s, %(start_time_text)s, %(market_name)s, %(selection)s,
                        %(market_family)s, %(calibration_key)s, %(odds)s, %(odds_estimated)s,
                        %(model_probability)s, %(evidence_confidence)s, %(ranking_score)s
                    )
                    ON CONFLICT (prediction_key) DO NOTHING
                """, row)
        return True

    with _sqlite_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO prediction_results (
                prediction_key, home_team, away_team, competition,
                match_date_text, start_time_text, market_name, selection,
                market_family, calibration_key, odds, odds_estimated,
                model_probability, evidence_confidence, ranking_score, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["prediction_key"], row["home_team"], row["away_team"], row["competition"],
            row["match_date_text"], row["start_time_text"], row["market_name"], row["selection"],
            row["market_family"], row["calibration_key"], row["odds"], int(row["odds_estimated"]),
            row["model_probability"], row["evidence_confidence"], row["ranking_score"],
            utc_now().isoformat(),
        ))
        conn.commit()
    return True


def _save_prediction_safe(result):
    try:
        save_prediction_result(result)
    except Exception as error:
        # Result tracking must never break customer tip delivery.
        print("⚠️ Could not save prediction result:", repr(error))


def get_prediction_by_id(prediction_id):
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM prediction_results WHERE id=%s", (int(prediction_id),))
                row = cur.fetchone()
                return dict(row) if row else None
    with _sqlite_conn() as conn:
        row = conn.execute("SELECT * FROM prediction_results WHERE id=?", (int(prediction_id),)).fetchone()
        return dict(row) if row else None


def get_pending_predictions(limit=10, min_age_hours=2.5, recheck_after_hours=6.0, include_unresolved=False):
    limit = max(1, min(int(limit or 10), 50))
    now = utc_now()
    created_before = now - timedelta(hours=max(0.0, float(min_age_hours)))
    checked_before = now - timedelta(hours=max(0.0, float(recheck_after_hours)))
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                if include_unresolved:
                    cur.execute("""
                        SELECT * FROM prediction_results
                        WHERE result_status IN ('pending','unresolved')
                          AND created_at <= %s
                          AND (last_checked_at IS NULL OR last_checked_at <= %s)
                        ORDER BY created_at ASC, id ASC
                        LIMIT %s
                    """, (created_before, checked_before, limit))
                else:
                    cur.execute("""
                        SELECT * FROM prediction_results
                        WHERE result_status = 'pending'
                          AND created_at <= %s
                          AND (last_checked_at IS NULL OR last_checked_at <= %s)
                        ORDER BY created_at ASC, id ASC
                        LIMIT %s
                    """, (created_before, checked_before, limit))
                return [dict(r) for r in (cur.fetchall() or [])]
    with _sqlite_conn() as conn:
        if include_unresolved:
            sql = """
                SELECT * FROM prediction_results
                WHERE result_status IN ('pending','unresolved')
                  AND created_at <= ?
                  AND (last_checked_at IS NULL OR last_checked_at <= ?)
                ORDER BY created_at ASC, id ASC
                LIMIT ?
            """
        else:
            sql = """
                SELECT * FROM prediction_results
                WHERE result_status = 'pending'
                  AND created_at <= ?
                  AND (last_checked_at IS NULL OR last_checked_at <= ?)
                ORDER BY created_at ASC, id ASC
                LIMIT ?
            """
        rows = conn.execute(sql, (created_before.isoformat(), checked_before.isoformat(), limit)).fetchall()
        return [dict(r) for r in rows]


def mark_prediction_checked(prediction_id, note=None):
    now = utc_now()
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE prediction_results
                    SET last_checked_at=%s,
                        settlement_note=COALESCE(%s, settlement_note)
                    WHERE id=%s
                """, (now, note, int(prediction_id)))
        return
    with _sqlite_conn() as conn:
        conn.execute("""
            UPDATE prediction_results
            SET last_checked_at=?, settlement_note=COALESCE(?, settlement_note)
            WHERE id=?
        """, (now.isoformat(), note, int(prediction_id)))
        conn.commit()


def settle_prediction_score(prediction_id, home_score, away_score, source="manual_score", confidence=1.0):
    row = get_prediction_by_id(prediction_id)
    if not row:
        return None
    status = settle_market(row.get("market_name"), row.get("selection"), home_score, away_score)
    final_status = status or "unresolved"
    now = utc_now()
    note = None if status else "Final score verified, but this market needs extra settlement data."
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE prediction_results
                    SET result_status=%s, final_home_score=%s, final_away_score=%s,
                        result_source=%s, result_confidence=%s, settlement_note=%s,
                        last_checked_at=%s, settled_at=%s
                    WHERE id=%s
                """, (
                    final_status, int(home_score), int(away_score), str(source or ""),
                    float(confidence or 0.0), note, now, now if status else None, int(prediction_id)
                ))
    else:
        with _sqlite_conn() as conn:
            conn.execute("""
                UPDATE prediction_results
                SET result_status=?, final_home_score=?, final_away_score=?,
                    result_source=?, result_confidence=?, settlement_note=?,
                    last_checked_at=?, settled_at=?
                WHERE id=?
            """, (
                final_status, int(home_score), int(away_score), str(source or ""),
                float(confidence or 0.0), note, now.isoformat(), now.isoformat() if status else None,
                int(prediction_id)
            ))
            conn.commit()
    try:
        from performance_engine import invalidate_feedback_cache
        invalidate_feedback_cache()
    except Exception:
        pass
    return get_prediction_by_id(prediction_id)


def settle_prediction_manual(prediction_id, status, note="Admin manual settlement"):
    status = str(status or "").lower().strip()
    if status not in {"win", "loss", "void"}:
        raise ValueError("status must be win, loss, or void")
    now = utc_now()
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE prediction_results
                    SET result_status=%s, result_source='admin_manual', result_confidence=1.0,
                        settlement_note=%s, last_checked_at=%s, settled_at=%s
                    WHERE id=%s
                """, (status, note, now, now, int(prediction_id)))
    else:
        with _sqlite_conn() as conn:
            conn.execute("""
                UPDATE prediction_results
                SET result_status=?, result_source='admin_manual', result_confidence=1.0,
                    settlement_note=?, last_checked_at=?, settled_at=?
                WHERE id=?
            """, (status, note, now.isoformat(), now.isoformat(), int(prediction_id)))
            conn.commit()
    try:
        from performance_engine import invalidate_feedback_cache
        invalidate_feedback_cache()
    except Exception:
        pass
    return get_prediction_by_id(prediction_id)


def get_performance_rows(limit=5000):
    limit = max(1, min(int(limit or 5000), 20000))
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM prediction_results
                    WHERE result_status IN ('win','loss','void')
                    ORDER BY settled_at DESC NULLS LAST, id DESC
                    LIMIT %s
                """, (limit,))
                return [dict(r) for r in (cur.fetchall() or [])]
    with _sqlite_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM prediction_results
            WHERE result_status IN ('win','loss','void')
            ORDER BY settled_at DESC, id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def _calibration_stat(rows):
    decisive = [r for r in rows if r.get("result_status") in {"win", "loss"}]
    n = len(decisive)
    if not n:
        return None
    wins = sum(1 for r in decisive if r.get("result_status") == "win")
    hit_rate = wins / n
    avg_p = sum(float(r.get("model_probability") or 0.0) for r in decisive) / n
    raw_error = hit_rate - avg_p
    shrink = n / (n + 40.0)
    adjustment = max(-0.04, min(0.04, raw_error * shrink))
    return {
        "sample": n,
        "wins": wins,
        "losses": n - wins,
        "hit_rate": hit_rate,
        "avg_probability": avg_p,
        "adjustment": adjustment,
    }


def get_performance_calibration_map(min_key_samples=18, min_family_samples=30):
    rows = get_performance_rows()
    by_key, by_family = {}, {}
    for r in rows:
        if r.get("result_status") not in {"win", "loss"}:
            continue
        by_key.setdefault(str(r.get("calibration_key") or ""), []).append(r)
        by_family.setdefault(str(r.get("market_family") or ""), []).append(r)

    keys = {}
    for key, group in by_key.items():
        stat = _calibration_stat(group)
        if stat and stat["sample"] >= min_key_samples:
            keys[key] = stat
    families = {}
    for fam, group in by_family.items():
        stat = _calibration_stat(group)
        if stat and stat["sample"] >= min_family_samples:
            families[fam] = stat
    return {"keys": keys, "families": families}


def get_performance_summary():
    rows = get_performance_rows()
    wins = sum(1 for r in rows if r.get("result_status") == "win")
    losses = sum(1 for r in rows if r.get("result_status") == "loss")
    voids = sum(1 for r in rows if r.get("result_status") == "void")
    decisive = wins + losses
    hit_rate = (wins / decisive) if decisive else 0.0

    actual = [r for r in rows if not bool(r.get("odds_estimated")) and float(r.get("odds") or 0) > 1]
    profit = 0.0
    staked = 0
    for r in actual:
        status = r.get("result_status")
        if status == "void":
            continue
        staked += 1
        if status == "win":
            profit += float(r.get("odds") or 0.0) - 1.0
        elif status == "loss":
            profit -= 1.0
    roi = (profit / staked) if staked else 0.0

    brier_rows = [r for r in rows if r.get("result_status") in {"win", "loss"}]
    brier = 0.0
    if brier_rows:
        brier = sum(
            (float(r.get("model_probability") or 0.0) - (1.0 if r.get("result_status") == "win" else 0.0)) ** 2
            for r in brier_rows
        ) / len(brier_rows)

    cal = get_performance_calibration_map()
    return {
        "total_settled": len(rows),
        "wins": wins, "losses": losses, "voids": voids,
        "decisive": decisive, "hit_rate": hit_rate,
        "actual_odds_bets": staked, "profit_units": profit, "roi": roi,
        "brier_score": brier,
        "calibration_active_keys": len(cal.get("keys", {})),
        "calibration_active_families": len(cal.get("families", {})),
    }


def get_tracking_counts():
    if USING_POSTGRES:
        with _pg_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT result_status, COUNT(*) AS n
                    FROM prediction_results GROUP BY result_status
                """)
                return {str(r["result_status"]): int(r["n"]) for r in (cur.fetchall() or [])}
    with _sqlite_conn() as conn:
        rows = conn.execute("SELECT result_status, COUNT(*) AS n FROM prediction_results GROUP BY result_status").fetchall()
        return {str(r["result_status"]): int(r["n"]) for r in rows}


_ensure_result_tracking_table()
