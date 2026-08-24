import os
import sqlite3
from datetime import datetime, timezone, timedelta

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