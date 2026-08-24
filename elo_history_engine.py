from datetime import datetime
from collections import Counter

import pandas as pd
from datafc import eloratings


# =========================================================
# BETTING BAYIN
# HISTORICAL ELO ENGINE V3
# =========================================================
#
# Fix:
# datafc uses country codes inside:
#
#   team_a
#   team_b
#
# Example:
#
#   Spain     -> ES
#   Argentina -> AR
#   Austria   -> AT
#
# Instead of maintaining a huge manual country-code map,
# this engine detects the query team's code automatically.
#
# IMPORTANT:
# Only matches STRICTLY BEFORE the target date are used.
# =========================================================


# =========================================================
# DATE PARSER
# =========================================================

def parse_date(value):

    if isinstance(value, datetime):
        return value

    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()

    formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
    ]

    for fmt in formats:

        try:
            return datetime.strptime(
                str(value),
                fmt
            )

        except ValueError:
            continue

    try:

        parsed = pd.to_datetime(
            value,
            errors="coerce"
        )

        if pd.isna(parsed):
            return None

        return parsed.to_pydatetime()

    except Exception:
        return None


# =========================================================
# LOAD COUNTRY HISTORY
# =========================================================

def load_team_history(team_name):

    print(
        f"🌐 Loading Elo match history: "
        f"{team_name}"
    )

    try:

        dataframe = (
            eloratings
            .country_matches_data(team_name)
        )

    except Exception as error:

        return None, str(error)

    if dataframe is None:

        return (
            None,
            "No dataframe returned."
        )

    if dataframe.empty:

        return (
            None,
            "Empty dataframe returned."
        )

    return dataframe, None


# =========================================================
# AUTO-DETECT QUERY TEAM CODE
# =========================================================

def detect_team_code(
    dataframe,
    team_name
):

    """
    datafc returns all matches involving the queried country.

    Therefore the queried team's code should appear in
    EVERY row as either team_a or team_b.

    We detect the code that appears most consistently
    across the dataset.
    """

    if (
        "team_a" not in dataframe.columns
        or
        "team_b" not in dataframe.columns
    ):

        return None

    appearances = Counter()

    total_rows = len(dataframe)

    for _, row in dataframe.iterrows():

        team_a = str(
            row.get("team_a", "")
        ).strip()

        team_b = str(
            row.get("team_b", "")
        ).strip()

        if team_a:
            appearances[team_a] += 1

        if team_b:
            appearances[team_b] += 1

    if not appearances:
        return None

    # The queried country's code should appear
    # in almost every returned match.
    candidates = [
        (code, count)
        for code, count
        in appearances.items()
        if count >= total_rows * 0.90
    ]

    if candidates:

        candidates.sort(
            key=lambda item: item[1],
            reverse=True
        )

        return candidates[0][0]

    # Fallback:
    # most frequently appearing code.
    return appearances.most_common(1)[0][0]


# =========================================================
# GET RATING FROM ROW
# =========================================================

def get_rating_from_row(
    row,
    team_code
):

    team_a = str(
        row.get("team_a", "")
    ).strip()

    team_b = str(
        row.get("team_b", "")
    ).strip()

    if team_a == team_code:

        rating = row.get(
            "team_a_rating"
        )

        side = "team_a"

        opponent = team_b

        rank = row.get(
            "team_a_rank"
        )

    elif team_b == team_code:

        rating = row.get(
            "team_b_rating"
        )

        side = "team_b"

        opponent = team_a

        rank = row.get(
            "team_b_rank"
        )

    else:

        return None

    try:

        if pd.isna(rating):
            return None

        rating = int(
            float(rating)
        )

    except (
        TypeError,
        ValueError
    ):

        return None

    try:

        if pd.isna(rank):
            rank = None
        else:
            rank = int(
                float(rank)
            )

    except (
        TypeError,
        ValueError
    ):

        rank = None

    return {
        "rating": rating,
        "side": side,
        "opponent_code": opponent,
        "rank": rank,
    }


# =========================================================
# HISTORICAL ELO LOOKUP
# =========================================================

def get_historical_elo(
    team_name,
    as_of_date
):

    target_date = parse_date(
        as_of_date
    )

    if target_date is None:

        return {
            "team": team_name,
            "error": "Invalid target date."
        }

    dataframe, error = (
        load_team_history(
            team_name
        )
    )

    if error:

        return {
            "team": team_name,
            "error": error
        }

    required_columns = [
        "date",
        "team_a",
        "team_b",
        "team_a_rating",
        "team_b_rating",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    if missing_columns:

        return {
            "team": team_name,

            "error": (
                "Missing required columns."
            ),

            "missing_columns": (
                missing_columns
            ),

            "columns": (
                list(dataframe.columns)
            )
        }

    # =====================================================
    # DETECT COUNTRY CODE
    # =====================================================

    team_code = detect_team_code(
        dataframe,
        team_name
    )

    if not team_code:

        return {
            "team": team_name,
            "error": (
                "Could not detect team code."
            )
        }

    # =====================================================
    # DATE NORMALIZATION
    # =====================================================

    working = dataframe.copy()

    working["_parsed_date"] = (
        pd.to_datetime(
            working["date"],
            errors="coerce"
        )
    )

    working = working[
        working["_parsed_date"].notna()
    ].copy()

    if working.empty:

        return {
            "team": team_name,
            "error": "No valid dates found."
        }

    # =====================================================
    # ANTI-LEAKAGE FILTER
    # =====================================================
    #
    # STRICTLY BEFORE target match date.
    #
    # Example:
    #
    # Target:
    # Spain vs Austria
    # 2026-07-02
    #
    # Spain's 2026-07-02 rating row is NOT allowed.
    #
    # We use the latest row before 2026-07-02.
    # =====================================================

    target_timestamp = pd.Timestamp(
        target_date
    )

    working = working[
        working["_parsed_date"]
        <
        target_timestamp
    ].copy()

    if working.empty:

        return {
            "team": team_name,

            "team_code": team_code,

            "error": (
                "No Elo history before "
                "target date."
            )
        }

    working = working.sort_values(
        "_parsed_date",
        ascending=False
    )

    # =====================================================
    # FIND LATEST VALID RATING
    # =====================================================

    selected = None

    for _, row in working.iterrows():

        result = get_rating_from_row(
            row,
            team_code
        )

        if result is None:
            continue

        selected = {
            "row": row,
            **result
        }

        break

    if selected is None:

        return {
            "team": team_name,

            "team_code": team_code,

            "error": (
                "No valid historical "
                "team rating found."
            )
        }

    row = selected["row"]

    rating_date = (
        row["_parsed_date"]
        .to_pydatetime()
    )

    days_old = (
        target_date.date()
        -
        rating_date.date()
    ).days

    # =====================================================
    # MATCH RESULT INFO
    # =====================================================

    try:

        team_a_score = int(
            float(
                row.get(
                    "team_a_score"
                )
            )
        )

    except Exception:

        team_a_score = None

    try:

        team_b_score = int(
            float(
                row.get(
                    "team_b_score"
                )
            )
        )

    except Exception:

        team_b_score = None

    # =====================================================
    # OUTPUT
    # =====================================================

    return {

        "team": team_name,

        "team_code": team_code,

        "elo": selected[
            "rating"
        ],

        "rank": selected[
            "rank"
        ],

        "requested_date": (
            target_date.strftime(
                "%Y-%m-%d"
            )
        ),

        "rating_date": (
            rating_date.strftime(
                "%Y-%m-%d"
            )
        ),

        "days_since_last_rating": (
            days_old
        ),

        "previous_match": {

            "team_a": (
                row.get(
                    "team_a"
                )
            ),

            "team_b": (
                row.get(
                    "team_b"
                )
            ),

            "team_a_score": (
                team_a_score
            ),

            "team_b_score": (
                team_b_score
            ),

            "opponent_code": (
                selected[
                    "opponent_code"
                ]
            ),

            "tournament": (
                row.get(
                    "tournament"
                )
            ),

            "host": (
                row.get(
                    "host"
                )
            )
        },

        "rating_side": (
            selected[
                "side"
            ]
        ),

        "source": (
            "World Football Elo Ratings"
        ),

        "future_data_used": False,

        "same_day_data_used": False,

        "model_stage": (
            "HISTORICAL_ELO_V3"
        )
    }


# =========================================================
# OPPONENT ELO FOR MATCH
# =========================================================

def get_opponent_elo_for_match(
    opponent,
    match_date
):

    return get_historical_elo(
        team_name=opponent,
        as_of_date=match_date
    )


# =========================================================
# BATCH LOOKUP
# =========================================================

def get_historical_ratings(
    requests
):

    results = []

    for item in requests:

        team = item.get(
            "team"
        )

        date = item.get(
            "date"
        )

        result = (
            get_historical_elo(
                team_name=team,
                as_of_date=date
            )
        )

        results.append(
            result
        )

    return results