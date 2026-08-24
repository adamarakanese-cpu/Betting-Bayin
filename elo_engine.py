import os
import csv
import json
import time
from io import StringIO

import requests


# =========================================================
# BETTING BAYIN
# WORLD FOOTBALL ELO ENGINE V2
#
# IMPORTANT:
# World.tsv layout:
# column 0 = current rank
# column 1 = previous rank
# column 2 = team code
# column 3 = CURRENT ELO RATING
# =========================================================

CACHE_FILE = "elo_cache.json"

WORLD_URL = (
    "https://www.eloratings.net/World.tsv"
)

TEAMS_URL = (
    "https://www.eloratings.net/en.teams.tsv"
)

TIMEOUT = 20

CACHE_SECONDS = (
    6 * 60 * 60
)


# =========================================================
# CACHE
# =========================================================

def load_cache():

    if not os.path.exists(
        CACHE_FILE
    ):
        return None

    try:

        with open(
            CACHE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

        created_at = data.get(
            "created_at",
            0
        )

        age = (
            time.time()
            - created_at
        )

        if age > CACHE_SECONDS:
            return None

        return data

    except Exception:
        return None


def save_cache(payload):

    data = {
        "created_at": (
            time.time()
        ),
        "payload": payload
    }

    with open(
        CACHE_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


def clear_cache():

    if os.path.exists(
        CACHE_FILE
    ):

        os.remove(
            CACHE_FILE
        )


# =========================================================
# DOWNLOAD
# =========================================================

def download_text(url):

    response = requests.get(
        url,
        timeout=TIMEOUT,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "BettingBayin/2.0"
            )
        }
    )

    response.raise_for_status()

    return response.text


# =========================================================
# TEAM CODE MAP
# =========================================================

def parse_team_codes(text):

    rows = []

    reader = csv.reader(
        StringIO(text),
        delimiter="\t"
    )

    for row in reader:

        if len(row) < 2:
            continue

        code = (
            row[0]
            .strip()
        )

        name = (
            row[-1]
            .strip()
        )

        if not code:
            continue

        if not name:
            continue

        rows.append({
            "code": code,
            "name": name
        })

    return rows


# =========================================================
# WORLD.TSV PARSER
# =========================================================

def parse_world_ratings(text):

    results = []

    reader = csv.reader(
        StringIO(text),
        delimiter="\t"
    )

    for row in reader:

        # We need at least:
        #
        # 0 rank
        # 1 previous rank
        # 2 country code
        # 3 current Elo

        if len(row) < 4:
            continue

        try:

            rank = int(
                row[0].strip()
            )

            team_code = (
                row[2]
                .strip()
            )

            current_elo = int(
                row[3].strip()
            )

        except (
            TypeError,
            ValueError
        ):
            continue

        # Sanity range
        if not (
            800
            <= current_elo
            <= 3000
        ):
            continue

        results.append({
            "rank": rank,
            "team_code": (
                team_code
            ),
            "elo": (
                current_elo
            ),
            "raw_row": [
                value.strip()
                for value in row
            ]
        })

    return results


# =========================================================
# NORMALIZATION
# =========================================================

def normalize_name(value):

    value = str(
        value or ""
    ).strip().lower()

    aliases = {
        "usa": (
            "united states"
        ),

        "u.s.a.": (
            "united states"
        ),

        "korea republic": (
            "south korea"
        ),

        "republic of korea": (
            "south korea"
        ),

        "czech republic": (
            "czechia"
        ),

        "bosnia-herzegovina": (
            "bosnia and herzegovina"
        ),

        "bosnia & herzegovina": (
            "bosnia and herzegovina"
        ),
    }

    return aliases.get(
        value,
        value
    )


def names_match(a, b):

    a = normalize_name(a)

    b = normalize_name(b)

    if not a or not b:
        return False

    return (
        a == b
        or a in b
        or b in a
    )


# =========================================================
# BUILD CURRENT TABLE
# =========================================================

def build_current_ratings(
    force_refresh=False
):

    if force_refresh:

        clear_cache()

    cached = load_cache()

    if cached:

        print(
            "💾 Elo cache hit."
        )

        return cached[
            "payload"
        ]

    print(
        "🌐 Downloading World "
        "Football Elo data..."
    )

    teams_text = (
        download_text(
            TEAMS_URL
        )
    )

    world_text = (
        download_text(
            WORLD_URL
        )
    )

    team_codes = (
        parse_team_codes(
            teams_text
        )
    )

    ratings = (
        parse_world_ratings(
            world_text
        )
    )

    payload = {
        "team_codes": (
            team_codes
        ),
        "ratings": ratings,
        "source": (
            "World Football "
            "Elo Ratings"
        ),
        "source_url": (
            WORLD_URL
        )
    }

    save_cache(
        payload
    )

    print(
        "💾 Elo data cached."
    )

    return payload


# =========================================================
# TEAM LOOKUP
# =========================================================

def find_team_code(
    team_name,
    team_codes
):

    for item in team_codes:

        if names_match(
            team_name,
            item["name"]
        ):

            return item

    return None


def find_rating_by_team(
    team_name,
    data
):

    code_match = (
        find_team_code(
            team_name,
            data["team_codes"]
        )
    )

    if not code_match:

        return None

    wanted_code = (
        code_match[
            "code"
        ]
        .strip()
        .upper()
    )

    for item in data[
        "ratings"
    ]:

        row_code = (
            item[
                "team_code"
            ]
            .strip()
            .upper()
        )

        if row_code == wanted_code:

            return {
                "team": (
                    team_name
                ),

                "elo": (
                    item["elo"]
                ),

                "rank": (
                    item["rank"]
                ),

                "team_code": (
                    wanted_code
                ),

                "source": (
                    "World Football "
                    "Elo Ratings"
                ),

                "source_url": (
                    WORLD_URL
                ),

                "raw_row": (
                    item[
                        "raw_row"
                    ]
                )
            }

    return None


# =========================================================
# MULTI TEAM
# =========================================================

def get_team_ratings(
    team_names,
    force_refresh=False
):

    data = build_current_ratings(
        force_refresh=(
            force_refresh
        )
    )

    results = {}

    for team in team_names:

        results[
            team
        ] = (
            find_rating_by_team(
                team,
                data
            )
        )

    return results