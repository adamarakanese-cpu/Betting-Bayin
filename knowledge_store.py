"""Persistent league/team intelligence extracted from verified research.
Uses the main PostgreSQL database on Render when configured; SQLite locally.
This is a cache of verified research, not invented football knowledge.
"""
import json, os, re
from datetime import datetime, timezone, timedelta

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
USING_POSTGRES = bool(DATABASE_URL)
SQLITE_PATH = os.getenv('SQLITE_DB_PATH', 'betting_bayin.db')
if USING_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row
else:
    import sqlite3


def _key(v): return re.sub(r'\s+', ' ', str(v or '').strip().lower())
def _now(): return datetime.now(timezone.utc)

def _conn():
    if USING_POSTGRES: return psycopg.connect(DATABASE_URL, row_factory=dict_row)
    c = sqlite3.connect(SQLITE_PATH); c.row_factory = sqlite3.Row; return c

def init_knowledge_store():
    with _conn() as conn:
        cur = conn.cursor()
        if USING_POSTGRES:
            cur.execute('''CREATE TABLE IF NOT EXISTS football_knowledge (
                entity_key TEXT PRIMARY KEY, entity_type TEXT NOT NULL, display_name TEXT,
                payload JSONB NOT NULL, sample_size INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
        else:
            cur.execute('''CREATE TABLE IF NOT EXISTS football_knowledge (
                entity_key TEXT PRIMARY KEY, entity_type TEXT NOT NULL, display_name TEXT,
                payload TEXT NOT NULL, sample_size INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL)''')
        conn.commit()

def _save(entity_type, name, payload):
    if not name or not isinstance(payload, dict) or not payload: return
    sample = int(payload.get('sample_size') or 0)
    if sample <= 0: return
    key = f'{entity_type}:{_key(name)}'; now = _now()
    with _conn() as conn:
        cur = conn.cursor()
        if USING_POSTGRES:
            cur.execute('''INSERT INTO football_knowledge(entity_key,entity_type,display_name,payload,sample_size,updated_at)
                VALUES(%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT(entity_key) DO UPDATE SET
                display_name=EXCLUDED.display_name,payload=EXCLUDED.payload,sample_size=EXCLUDED.sample_size,updated_at=EXCLUDED.updated_at''',
                (key, entity_type, name, json.dumps(payload, ensure_ascii=False), sample, now))
        else:
            cur.execute('''INSERT OR REPLACE INTO football_knowledge(entity_key,entity_type,display_name,payload,sample_size,updated_at)
                VALUES(?,?,?,?,?,?)''',(key,entity_type,name,json.dumps(payload,ensure_ascii=False),sample,now.isoformat()))
        conn.commit()

def save_research_knowledge(research):
    research = research or {}
    _save('league', research.get('competition'), research.get('league_profile') or {})
    _save('team', research.get('home_team'), research.get('home_team_profile') or {})
    _save('team', research.get('away_team'), research.get('away_team_profile') or {})

def get_profile(entity_type, name, max_age_days=30):
    if not name: return None
    key=f'{entity_type}:{_key(name)}'
    with _conn() as conn:
        cur=conn.cursor(); q='SELECT * FROM football_knowledge WHERE entity_key=%s' if USING_POSTGRES else 'SELECT * FROM football_knowledge WHERE entity_key=?'
        cur.execute(q,(key,)); row=cur.fetchone()
    if not row: return None
    row=dict(row); updated=row.get('updated_at')
    if isinstance(updated,str):
        try: updated=datetime.fromisoformat(updated)
        except Exception: updated=None
    if updated and updated.tzinfo is None: updated=updated.replace(tzinfo=timezone.utc)
    if updated and _now()-updated > timedelta(days=max_age_days): return None
    payload=row.get('payload')
    if isinstance(payload,str):
        try: payload=json.loads(payload)
        except Exception: return None
    return payload if isinstance(payload,dict) else None

init_knowledge_store()
