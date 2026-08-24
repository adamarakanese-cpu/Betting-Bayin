import json
import sqlite3
import hashlib
from datetime import datetime, timezone, timedelta

import requests


# =========================================================
# BETTING BAYIN
# DATA ENGINE V7
# Cache + OpenFootball Adapter
# =========================================================

DB_PATH = "betting_bayin_data.db"

CACHE_HOURS = 6

OPENFOOTBALL_BASE = (
    "https://raw.githubusercontent.com/"
    "openfootball/football.json/master"
)

REQUEST_TIMEOUT = 20


# =========================================================
# DATABASE
# =========================================================

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_data_database():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS research_cache (
            cache_key TEXT PRIMARY KEY,
            home_team TEXT,
            away_team TEXT,
            competition TEXT,
            match_date TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS structured_match_cache (
            cache_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            team_name TEXT,
            season TEXT,
            competition TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_data_database()


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def dt_to_string(value):
    return value.isoformat()


def string_to_dt(value):
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


# =========================================================
# CACHE KEYS
# =========================================================

def normalize(value):
    return (
        str(value or "")
        .strip()
        .lower()
    )


def make_fixture_key(
    home_team,
    away_team,
    competition,
    match_date
):
    raw = "|".join([
        normalize(home_team),
        normalize(away_team),
        normalize(competition),
        normalize(match_date),
    ])

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


# =========================================================
# VERIFIED RESEARCH CACHE
# =========================================================

def save_research_cache(
    home_team,
    away_team,
    competition,
    match_date,
    payload
):
    cache_key = make_fixture_key(
        home_team,
        away_team,
        competition,
        match_date
    )

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO research_cache (
            cache_key,
            home_team,
            away_team,
            competition,
            match_date,
            payload,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        cache_key,
        home_team,
        away_team,
        competition,
        match_date,
        json.dumps(
            payload,
            ensure_ascii=False
        ),
        dt_to_string(
            utc_now()
        )
    ))

    conn.commit()
    conn.close()


def get_research_cache(
    home_team,
    away_team,
    competition,
    match_date,
    max_age_hours=CACHE_HOURS
):
    cache_key = make_fixture_key(
        home_team,
        away_team,
        competition,
        match_date
    )

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM research_cache
        WHERE cache_key = ?
    """, (
        cache_key,
    ))

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    created_at = string_to_dt(
        row["created_at"]
    )

    if not created_at:
        return None

    age = (
        utc_now()
        - created_at
    )

    if age > timedelta(
        hours=max_age_hours
    ):
        return None

    try:
        return json.loads(
            row["payload"]
        )
    except Exception:
        return None


# =========================================================
# OPENFOOTBALL LEAGUE MAP
# =========================================================

LEAGUE_CODES = {
    "premier league": "en.1",
    "english premier league": "en.1",

    "bundesliga": "de.1",
    "german bundesliga": "de.1",

    "la liga": "es.1",
    "primera division": "es.1",
    "primera división": "es.1",

    "serie a": "it.1",

    "ligue 1": "fr.1",
}


# =========================================================
# SEASON RESOLVER
# =========================================================

def resolve_season(
    match_date
):
    """
    European club season assumption:
    July-Dec -> YYYY-(YY+1)
    Jan-Jun  -> (YYYY-1)-YY
    """

    formats = [
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]

    parsed = None

    for fmt in formats:
        try:
            parsed = datetime.strptime(
                match_date,
                fmt
            )
            break
        except Exception:
            pass

    if not parsed:
        return None

    year = parsed.year

    if parsed.month >= 7:
        return (
            f"{year}-"
            f"{str(year + 1)[-2:]}"
        )

    return (
        f"{year - 1}-"
        f"{str(year)[-2:]}"
    )


# =========================================================
# OPENFOOTBALL DOWNLOAD
# =========================================================

def fetch_openfootball_dataset(
    competition,
    match_date
):
    code = LEAGUE_CODES.get(
        normalize(competition)
    )

    if not code:
        return None

    season = resolve_season(
        match_date
    )

    if not season:
        return None

    url = (
        f"{OPENFOOTBALL_BASE}/"
        f"{season}/{code}.json"
    )

    try:
        response = requests.get(
            url,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code != 200:
            return None

        data = response.json()

        return {
            "source": "OpenFootball",
            "url": url,
            "season": season,
            "competition_code": code,
            "data": data
        }

    except Exception:
        return None


# =========================================================
# TEAM NAME MATCHING
# =========================================================

def clean_team_name(value):
    value = normalize(value)

    removals = [
        " fc",
        " afc",
        " cf",
        " calcio",
    ]

    for suffix in removals:
        if value.endswith(suffix):
            value = value[
                :-len(suffix)
            ]

    return value.strip()


def team_names_match(
    a,
    b
):
    a = clean_team_name(a)
    b = clean_team_name(b)

    if not a or not b:
        return False

    if a == b:
        return True

    if a in b:
        return True

    if b in a:
        return True

    return False


# =========================================================
# SCORE PARSER
# =========================================================

def get_ft_score(
    score
):
    if isinstance(
        score,
        dict
    ):
        ft = score.get("ft")

        if (
            isinstance(ft, list)
            and len(ft) >= 2
        ):
            return (
                ft[0],
                ft[1]
            )

    if (
        isinstance(score, list)
        and len(score) >= 2
    ):
        return (
            score[0],
            score[1]
        )

    return (
        None,
        None
    )


# =========================================================
# TEAM HISTORY
# =========================================================

def openfootball_team_history(
    team_name,
    competition,
    match_date,
    limit=5
):
    dataset = (
        fetch_openfootball_dataset(
            competition,
            match_date
        )
    )

    if not dataset:
        return []

    matches = (
        dataset["data"].get(
            "matches",
            []
        )
    )

    target_formats = [
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]

    target_date = None

    for fmt in target_formats:
        try:
            target_date = (
                datetime.strptime(
                    match_date,
                    fmt
                )
            )
            break
        except Exception:
            pass

    if not target_date:
        return []

    results = []

    for match in matches:
        date_text = match.get(
            "date"
        )

        try:
            event_date = (
                datetime.strptime(
                    date_text,
                    "%Y-%m-%d"
                )
            )
        except Exception:
            continue

        if event_date >= target_date:
            continue

        team1 = match.get(
            "team1"
        )

        team2 = match.get(
            "team2"
        )

        is_home = team_names_match(
            team_name,
            team1
        )

        is_away = team_names_match(
            team_name,
            team2
        )

        if not (
            is_home
            or is_away
        ):
            continue

        home_score, away_score = (
            get_ft_score(
                match.get("score")
            )
        )

        if (
            home_score is None
            or away_score is None
        ):
            continue

        if is_home:
            goals_for = home_score
            goals_against = away_score
            opponent = team2
            venue = "home"
        else:
            goals_for = away_score
            goals_against = home_score
            opponent = team1
            venue = "away"

        if goals_for > goals_against:
            result = "W"
        elif goals_for == goals_against:
            result = "D"
        else:
            result = "L"

        results.append({
            "date": date_text,
            "opponent": opponent,
            "venue": venue,
            "goals_for": goals_for,
            "goals_against": (
                goals_against
            ),
            "result": result,
            "competition": (
                dataset[
                    "data"
                ].get(
                    "name",
                    competition
                )
            ),
            "source_url": (
                dataset["url"]
            ),
            "source_domain": (
                "raw.githubusercontent.com"
            ),
            "trusted_source": True,
            "structured_source": (
                "OpenFootball"
            )
        })

    results.sort(
        key=lambda x: x["date"],
        reverse=True
    )

    return results[:limit]