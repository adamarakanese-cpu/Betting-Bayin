from datetime import datetime
from math import exp

from elo_history_engine import (
    get_historical_elo,
)


# =========================================================
# BETTING BAYIN
# INDEPENDENT STRENGTH ENGINE V4
# =========================================================
#
# INPUTS
#
# - Recent verified matches
# - Recency
# - Source trust
# - Competition importance
# - Venue
# - Historical opponent Elo
# - OWN TEAM historical Elo
#
# IMPORTANT
#
# - Bookmaker odds are NOT used.
# - Future Elo data is NOT allowed.
# - Own-team Elo is taken as of the target match date.
# =========================================================


BASE_ELO = 1700.0

ELO_SCALE = 400.0


# =========================================================
# HELPERS
# =========================================================

def clamp(
    value,
    low=0.0,
    high=1.0
):
    return max(
        low,
        min(
            high,
            value
        )
    )


def parse_date(
    value
):
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

    return None


# =========================================================
# RECENCY WEIGHT
# =========================================================

def recency_weight(
    match_date,
    target_date
):
    match_dt = parse_date(
        match_date
    )

    target_dt = parse_date(
        target_date
    )

    if (
        not match_dt
        or not target_dt
    ):

        return 0.30

    days = max(
        0,
        (
            target_dt
            -
            match_dt
        ).days
    )

    weight = exp(
        -days / 150.0
    )

    return clamp(
        weight,
        0.10,
        1.00
    )


# =========================================================
# SOURCE WEIGHT
# =========================================================

def source_weight(
    match
):
    if match.get(
        "trusted_source"
    ) is True:

        return 1.00

    domain = str(
        match.get(
            "source_domain",
            ""
        )
    ).lower()

    medium_sources = [
        "national-football-teams.com",
        "soccerway.com",
        "worldfootball.net",
        "flashscore.com",
    ]

    if any(
        item in domain
        for item in medium_sources
    ):

        return 0.70

    if "wikipedia.org" in domain:

        return 0.55

    return 0.50


# =========================================================
# COMPETITION WEIGHT
# =========================================================

def competition_weight(
    competition
):
    text = str(
        competition
        or ""
    ).lower()

    if (
        "world cup" in text
        and
        "qualification" not in text
        and
        "qualifier" not in text
    ):

        return 1.10

    if (
        "euro" in text
        and
        "qualification" not in text
        and
        "qualifier" not in text
    ):

        return 1.08

    if (
        "nations league"
        in text
    ):

        return 1.00

    if (
        "qualification" in text
        or
        "qualifier" in text
    ):

        return 1.00

    if "friendly" in text:

        return 0.75

    return 0.90


# =========================================================
# VENUE WEIGHT
# =========================================================

def venue_weight(
    venue,
    team_role
):
    venue = str(
        venue
        or ""
    ).lower()

    if venue == "neutral":

        return 0.95

    if venue == "unknown":

        return 0.95

    if venue == "away":

        return 1.08

    if venue == "home":

        return 0.94

    return 0.95


# =========================================================
# ELO HELPERS
# =========================================================

def elo_strength_score(
    elo
):
    """
    Convert Elo rating into 0-1 strength scale.

    BASE_ELO 1700 ~= 0.50

    Higher Elo -> above 0.50
    Lower Elo  -> below 0.50
    """

    if elo is None:

        return 0.50

    try:

        elo = float(
            elo
        )

    except Exception:

        return 0.50

    exponent = (
        BASE_ELO
        -
        elo
    ) / ELO_SCALE

    score = (
        1.0
        /
        (
            1.0
            +
            10.0 ** exponent
        )
    )

    return clamp(
        score
    )


# =========================================================
# OWN TEAM HISTORICAL ELO
# =========================================================

def get_team_elo(
    team_name,
    target_date
):
    if (
        not team_name
        or not target_date
    ):

        return {
            "team":
                team_name,

            "elo":
                None,

            "rank":
                None,

            "rating_date":
                None,

            "available":
                False,

            "future_data_used":
                False,

            "same_day_data_used":
                False,

            "strength_score":
                0.50,

            "error":
                "Team or target date missing."
        }

    try:

        result = (
            get_historical_elo(
                team_name=
                    team_name,

                as_of_date=
                    target_date
            )
        )

    except Exception as error:

        return {
            "team":
                team_name,

            "elo":
                None,

            "rank":
                None,

            "rating_date":
                None,

            "available":
                False,

            "future_data_used":
                False,

            "same_day_data_used":
                False,

            "strength_score":
                0.50,

            "error":
                str(error)
        }

    if result.get(
        "error"
    ):

        return {
            "team":
                team_name,

            "elo":
                None,

            "rank":
                None,

            "rating_date":
                None,

            "available":
                False,

            "future_data_used":
                False,

            "same_day_data_used":
                False,

            "strength_score":
                0.50,

            "error":
                result.get(
                    "error"
                )
        }

    elo = result.get(
        "elo"
    )

    future_data = bool(
        result.get(
            "future_data_used",
            False
        )
    )

    # HARD LEAKAGE BLOCK
    if future_data:

        return {
            "team":
                team_name,

            "elo":
                None,

            "rank":
                None,

            "rating_date":
                result.get(
                    "rating_date"
                ),

            "available":
                False,

            "future_data_used":
                True,

            "same_day_data_used":
                result.get(
                    "same_day_data_used",
                    False
                ),

            "strength_score":
                0.50,

            "error":
                "Future Elo leakage detected."
        }

    return {
        "team":
            team_name,

        "elo":
            elo,

        "rank":
            result.get(
                "rank"
            ),

        "rating_date":
            result.get(
                "rating_date"
            ),

        "days_since_last_rating":
            result.get(
                "days_since_last_rating"
            ),

        "available":
            elo is not None,

        "future_data_used":
            False,

        "same_day_data_used":
            result.get(
                "same_day_data_used",
                False
            ),

        "strength_score":
            round(
                elo_strength_score(
                    elo
                ),
                3
            ),

        "error":
            None
    }


# =========================================================
# OPPONENT ELO WEIGHT
# =========================================================

def opponent_elo_weight(
    opponent_elo
):
    if opponent_elo is None:

        return 1.00

    adjustment = (
        opponent_elo
        -
        BASE_ELO
    ) / 1000.0

    return clamp(
        1.0
        +
        adjustment,
        0.65,
        1.35
    )


# =========================================================
# RESULT SCORE
# =========================================================

def result_score(
    result
):
    result = str(
        result
        or ""
    ).upper()

    if result == "W":

        return 1.0

    if result == "D":

        return 0.5

    if result == "L":

        return 0.0

    return 0.5


# =========================================================
# OPPONENT-ADJUSTED RESULT
# =========================================================

def opponent_adjusted_result(
    result,
    opponent_elo
):
    base = (
        result_score(
            result
        )
    )

    if opponent_elo is None:

        return base

    difference = (
        opponent_elo
        -
        BASE_ELO
    )

    if base == 1.0:

        adjustment = (
            difference
            /
            1400.0
        )

    elif base == 0.0:

        adjustment = (
            difference
            /
            1800.0
        )

    else:

        adjustment = (
            difference
            /
            1600.0
        )

    return clamp(
        base
        +
        adjustment
    )


# =========================================================
# HISTORICAL OPPONENT ELO
# =========================================================

def get_match_opponent_elo(
    match
):
    opponent = (
        match.get(
            "opponent"
        )
    )

    match_date = (
        match.get(
            "date"
        )
    )

    if (
        not opponent
        or not match_date
    ):

        return {
            "elo":
                None,

            "available":
                False,

            "error":
                (
                    "Opponent or date missing."
                )
        }

    try:

        result = (
            get_historical_elo(
                team_name=
                    opponent,

                as_of_date=
                    match_date
            )
        )

    except Exception as error:

        return {
            "elo":
                None,

            "available":
                False,

            "error":
                str(error)
        }

    if result.get(
        "error"
    ):

        return {
            "elo":
                None,

            "available":
                False,

            "error":
                result.get(
                    "error"
                )
        }

    if result.get(
        "future_data_used",
        False
    ):

        return {
            "elo":
                None,

            "available":
                False,

            "future_data_used":
                True,

            "error":
                (
                    "Future Elo leakage detected."
                )
        }

    return {
        "elo":
            result.get(
                "elo"
            ),

        "rank":
            result.get(
                "rank"
            ),

        "rating_date":
            result.get(
                "rating_date"
            ),

        "days_since_last_rating":
            result.get(
                "days_since_last_rating"
            ),

        "available":
            (
                result.get(
                    "elo"
                )
                is not None
            ),

        "future_data_used":
            False,

        "same_day_data_used":
            result.get(
                "same_day_data_used",
                False
            )
    }


# =========================================================
# TEAM METRICS
# =========================================================

def calculate_team_metrics(
    team_name,
    matches,
    target_date,
    role
):
    if not matches:

        return {
            "matches":
                0,

            "effective_sample":
                0.0,

            "weighted_ppm":
                None,

            "weighted_goals_for":
                None,

            "weighted_goals_against":
                None,

            "trusted_ratio":
                0.0,

            "opponent_elo_coverage":
                0.0,

            "match_details":
                []
        }

    total_weight = 0.0

    weighted_points = 0.0

    weighted_goals_for = 0.0

    weighted_goals_against = 0.0

    trusted_count = 0

    opponent_elo_count = 0

    match_details = []

    for match in matches:

        date = (
            match.get(
                "date"
            )
        )

        competition = (
            match.get(
                "competition"
            )
        )

        venue = (
            match.get(
                "venue"
            )
        )

        # ---------------------------------------------
        # Weights
        # ---------------------------------------------

        rw = (
            recency_weight(
                date,
                target_date
            )
        )

        sw = (
            source_weight(
                match
            )
        )

        cw = (
            competition_weight(
                competition
            )
        )

        vw = (
            venue_weight(
                venue,
                role
            )
        )

        # ---------------------------------------------
        # Historical opponent Elo
        # ---------------------------------------------

        elo_data = (
            get_match_opponent_elo(
                match
            )
        )

        opponent_elo = (
            elo_data.get(
                "elo"
            )
        )

        if opponent_elo is not None:

            opponent_elo_count += 1

        ew = (
            opponent_elo_weight(
                opponent_elo
            )
        )

        final_weight = (
            rw
            *
            sw
            *
            cw
            *
            vw
            *
            ew
        )

        if match.get(
            "trusted_source"
        ) is True:

            trusted_count += 1

        result = (
            match.get(
                "result"
            )
        )

        adjusted_result = (
            opponent_adjusted_result(
                result,
                opponent_elo
            )
        )

        points_equivalent = (
            adjusted_result
            *
            3.0
        )

        try:

            goals_for = float(
                match.get(
                    "goals_for",
                    0
                )
            )

        except Exception:

            goals_for = 0.0

        try:

            goals_against = float(
                match.get(
                    "goals_against",
                    0
                )
            )

        except Exception:

            goals_against = 0.0

        total_weight += (
            final_weight
        )

        weighted_points += (
            points_equivalent
            *
            final_weight
        )

        weighted_goals_for += (
            goals_for
            *
            final_weight
        )

        weighted_goals_against += (
            goals_against
            *
            final_weight
        )

        match_details.append({

            "date":
                date,

            "opponent":
                match.get(
                    "opponent"
                ),

            "competition":
                competition,

            "venue":
                venue,

            "result":
                result,

            "goals_for":
                goals_for,

            "goals_against":
                goals_against,

            "opponent_elo":
                opponent_elo,

            "opponent_elo_rank":
                elo_data.get(
                    "rank"
                ),

            "opponent_elo_date":
                elo_data.get(
                    "rating_date"
                ),

            "opponent_elo_available":
                elo_data.get(
                    "available",
                    False
                ),

            "future_elo_used":
                elo_data.get(
                    "future_data_used",
                    False
                ),

            "adjusted_result":
                round(
                    adjusted_result,
                    3
                ),

            "recency_weight":
                round(
                    rw,
                    3
                ),

            "source_weight":
                round(
                    sw,
                    3
                ),

            "competition_weight":
                round(
                    cw,
                    3
                ),

            "venue_weight":
                round(
                    vw,
                    3
                ),

            "opponent_weight":
                round(
                    ew,
                    3
                ),

            "final_weight":
                round(
                    final_weight,
                    3
                )
        })

    if total_weight <= 0:

        return {
            "matches":
                len(
                    matches
                ),

            "effective_sample":
                0.0,

            "weighted_ppm":
                None,

            "weighted_goals_for":
                None,

            "weighted_goals_against":
                None,

            "trusted_ratio":
                0.0,

            "opponent_elo_coverage":
                0.0,

            "match_details":
                match_details
        }

    weighted_ppm = (
        weighted_points
        /
        total_weight
    )

    avg_goals_for = (
        weighted_goals_for
        /
        total_weight
    )

    avg_goals_against = (
        weighted_goals_against
        /
        total_weight
    )

    trust_ratio = (
        trusted_count
        /
        len(matches)
    )

    elo_coverage = (
        opponent_elo_count
        /
        len(matches)
    )

    return {

        "matches":
            len(matches),

        "effective_sample":
            round(
                total_weight,
                3
            ),

        "weighted_ppm":
            round(
                weighted_ppm,
                3
            ),

        "weighted_goals_for":
            round(
                avg_goals_for,
                3
            ),

        "weighted_goals_against":
            round(
                avg_goals_against,
                3
            ),

        "trusted_ratio":
            round(
                trust_ratio,
                3
            ),

        "opponent_elo_coverage":
            round(
                elo_coverage,
                3
            ),

        "match_details":
            match_details
    }


# =========================================================
# RATINGS V4
# =========================================================

def calculate_ratings(
    metrics,
    own_elo_data
):
    if (
        not metrics
        or
        metrics.get(
            "weighted_ppm"
        ) is None
    ):

        own_elo_score = (
            own_elo_data.get(
                "strength_score",
                0.50
            )
        )

        return {
            "form":
                0.50,

            "attack":
                0.50,

            "defence":
                0.50,

            "performance_strength":
                0.50,

            "elo_strength":
                round(
                    own_elo_score,
                    3
                ),

            "raw_strength":
                round(
                    (
                        0.50
                        *
                        0.55
                        +
                        own_elo_score
                        *
                        0.45
                    ),
                    3
                ),

            "data_confidence":
                0.20
                if own_elo_data.get(
                    "available"
                )
                else 0.0,

            "adjusted_strength":
                0.50
        }

    ppm = (
        metrics[
            "weighted_ppm"
        ]
    )

    goals_for = (
        metrics[
            "weighted_goals_for"
        ]
    )

    goals_against = (
        metrics[
            "weighted_goals_against"
        ]
    )

    effective_sample = (
        metrics[
            "effective_sample"
        ]
    )

    trust_ratio = (
        metrics[
            "trusted_ratio"
        ]
    )

    opponent_elo_coverage = (
        metrics[
            "opponent_elo_coverage"
        ]
    )

    # =====================================================
    # FORM
    # =====================================================

    form = clamp(
        ppm
        /
        3.0
    )

    # =====================================================
    # ATTACK
    # =====================================================

    attack = clamp(
        goals_for
        /
        3.0
    )

    # =====================================================
    # DEFENCE
    # =====================================================

    defence = clamp(
        1.0
        -
        (
            goals_against
            /
            3.5
        )
    )

    # =====================================================
    # PERFORMANCE STRENGTH
    # =====================================================

    performance_strength = (
        form
        *
        0.45
        +
        attack
        *
        0.30
        +
        defence
        *
        0.25
    )

    # =====================================================
    # OWN TEAM ELO STRENGTH
    # =====================================================

    elo_available = bool(
        own_elo_data.get(
            "available",
            False
        )
    )

    elo_strength = (
        own_elo_data.get(
            "strength_score",
            0.50
        )
    )

    # =====================================================
    # COMBINE PERFORMANCE + OWN ELO
    # =====================================================

    if elo_available:

        raw_strength = (
            performance_strength
            *
            0.55
            +
            elo_strength
            *
            0.45
        )

    else:

        raw_strength = (
            performance_strength
        )

    raw_strength = (
        clamp(
            raw_strength
        )
    )

    # =====================================================
    # DATA CONFIDENCE
    # =====================================================

    sample_confidence = (
        clamp(
            effective_sample
            /
            3.0
        )
    )

    own_elo_confidence = (
        1.0
        if elo_available
        else 0.0
    )

    data_confidence = (

        sample_confidence
        *
        0.35

        +

        trust_ratio
        *
        0.25

        +

        opponent_elo_coverage
        *
        0.20

        +

        own_elo_confidence
        *
        0.20
    )

    data_confidence = (
        clamp(
            data_confidence
        )
    )

    # =====================================================
    # SHRINK LOW CONFIDENCE TOWARD NEUTRAL
    # =====================================================

    adjusted_strength = (

        raw_strength
        *
        data_confidence

        +

        0.50
        *
        (
            1.0
            -
            data_confidence
        )
    )

    return {

        "form":
            round(
                form,
                3
            ),

        "attack":
            round(
                attack,
                3
            ),

        "defence":
            round(
                defence,
                3
            ),

        "performance_strength":
            round(
                performance_strength,
                3
            ),

        "elo_strength":
            round(
                elo_strength,
                3
            ),

        "raw_strength":
            round(
                raw_strength,
                3
            ),

        "data_confidence":
            round(
                data_confidence,
                3
            ),

        "adjusted_strength":
            round(
                adjusted_strength,
                3
            )
    }


# =========================================================
# MAIN STRENGTH MODEL V4
# =========================================================

def calculate_match_strength(
    research
):
    home_team = (
        research.get(
            "home_team"
        )
    )

    away_team = (
        research.get(
            "away_team"
        )
    )

    target_date = (
        research.get(
            "match_date"
        )
    )

    home_matches = (
        research.get(
            "home_recent_matches",
            []
        )
        or []
    )

    away_matches = (
        research.get(
            "away_recent_matches",
            []
        )
        or []
    )

    print()
    print(
        "🌍 Loading historical "
        "opponent Elo..."
    )

    # =====================================================
    # RECENT MATCH METRICS
    # =====================================================

    home_metrics = (
        calculate_team_metrics(
            team_name=
                home_team,

            matches=
                home_matches,

            target_date=
                target_date,

            role=
                "home"
        )
    )

    away_metrics = (
        calculate_team_metrics(
            team_name=
                away_team,

            matches=
                away_matches,

            target_date=
                target_date,

            role=
                "away"
        )
    )

    # =====================================================
    # OWN TEAM ELO
    # =====================================================

    print()
    print(
        "🌍 Loading own-team "
        "historical Elo..."
    )

    home_elo = (
        get_team_elo(
            home_team,
            target_date
        )
    )

    away_elo = (
        get_team_elo(
            away_team,
            target_date
        )
    )

    if home_elo.get(
        "available"
    ):

        print(
            f"🏠 {home_team} Elo: "
            f"{home_elo.get('elo')} "
            f"| Rank #{home_elo.get('rank')}"
        )

    else:

        print(
            f"⚠️ {home_team} Elo unavailable."
        )

    if away_elo.get(
        "available"
    ):

        print(
            f"✈️ {away_team} Elo: "
            f"{away_elo.get('elo')} "
            f"| Rank #{away_elo.get('rank')}"
        )

    else:

        print(
            f"⚠️ {away_team} Elo unavailable."
        )

    # =====================================================
    # RATINGS
    # =====================================================

    home_ratings = (
        calculate_ratings(
            home_metrics,
            home_elo
        )
    )

    away_ratings = (
        calculate_ratings(
            away_metrics,
            away_elo
        )
    )

    home_strength = (
        home_ratings[
            "adjusted_strength"
        ]
    )

    away_strength = (
        away_ratings[
            "adjusted_strength"
        ]
    )

    difference = (
        home_strength
        -
        away_strength
    )

    # =====================================================
    # ELO DIFFERENCE
    # =====================================================

    home_elo_value = (
        home_elo.get(
            "elo"
        )
    )

    away_elo_value = (
        away_elo.get(
            "elo"
        )
    )

    if (
        home_elo_value is not None
        and
        away_elo_value is not None
    ):

        elo_difference = (
            home_elo_value
            -
            away_elo_value
        )

    else:

        elo_difference = None

    # =====================================================
    # RELIABILITY
    # =====================================================

    min_confidence = min(
        home_ratings[
            "data_confidence"
        ],
        away_ratings[
            "data_confidence"
        ]
    )

    home_elo_coverage = (
        home_metrics[
            "opponent_elo_coverage"
        ]
    )

    away_elo_coverage = (
        away_metrics[
            "opponent_elo_coverage"
        ]
    )

    reliability_reasons = []

    if min_confidence < 0.55:

        reliability_reasons.append(
            "One or both teams have "
            "low data confidence."
        )

    if home_elo_coverage < 0.60:

        reliability_reasons.append(
            "Home-team opponent Elo "
            "coverage below 60%."
        )

    if away_elo_coverage < 0.60:

        reliability_reasons.append(
            "Away-team opponent Elo "
            "coverage below 60%."
        )

    if (
        home_metrics[
            "trusted_ratio"
        ]
        <
        0.40
    ):

        reliability_reasons.append(
            "Home-team trusted source "
            "coverage below 40%."
        )

    if (
        away_metrics[
            "trusted_ratio"
        ]
        <
        0.40
    ):

        reliability_reasons.append(
            "Away-team trusted source "
            "coverage below 40%."
        )

    if not home_elo.get(
        "available"
    ):

        reliability_reasons.append(
            "Home-team own Elo unavailable."
        )

    if not away_elo.get(
        "available"
    ):

        reliability_reasons.append(
            "Away-team own Elo unavailable."
        )

    if home_elo.get(
        "future_data_used"
    ):

        reliability_reasons.append(
            "Home Elo future-data leakage "
            "detected."
        )

    if away_elo.get(
        "future_data_used"
    ):

        reliability_reasons.append(
            "Away Elo future-data leakage "
            "detected."
        )

    if not reliability_reasons:

        reliability_status = (
            "HIGH"
            if min_confidence >= 0.75
            else "MEDIUM"
        )

    else:

        reliability_status = (
            "LOW"
        )

    # =====================================================
    # RAW LEAN
    # =====================================================

    if difference >= 0.03:

        raw_lean = (
            home_team
        )

    elif difference <= -0.03:

        raw_lean = (
            away_team
        )

    else:

        raw_lean = (
            "EVEN"
        )

    # =====================================================
    # RELIABLE LEAN
    # =====================================================

    if reliability_status == "LOW":

        reliable_lean = (
            "INCONCLUSIVE"
        )

    else:

        reliable_lean = (
            raw_lean
        )

    # =====================================================
    # RETURN
    # =====================================================

    return {

        "home": {

            "team":
                home_team,

            "role":
                "home",

            "metrics":
                home_metrics,

            "ratings":
                home_ratings,

            "own_elo":
                home_elo
        },

        "away": {

            "team":
                away_team,

            "role":
                "away",

            "metrics":
                away_metrics,

            "ratings":
                away_ratings,

            "own_elo":
                away_elo
        },

        "strength_difference":
            round(
                difference,
                3
            ),

        "elo_difference":
            (
                round(
                    elo_difference,
                    1
                )
                if elo_difference
                is not None
                else None
            ),

        "raw_lean":
            raw_lean,

        "reliable_lean":
            reliable_lean,

        "reliability": {

            "status":
                reliability_status,

            "minimum_confidence":
                round(
                    min_confidence,
                    3
                ),

            "reasons":
                reliability_reasons
        },

        "bookmaker_odds_used":
            False,

        "own_team_elo_used":
            (
                home_elo.get(
                    "available"
                )
                and
                away_elo.get(
                    "available"
                )
            ),

        "opponent_strength_used":
            True,

        "opponent_strength_source":
            (
                "Historical World Football Elo"
            ),

        "own_strength_source":
            (
                "Historical World Football Elo"
            ),

        "future_elo_leakage_allowed":
            False,

        "model_stage":
            (
                "INDEPENDENT_TEAM_STRENGTH_V4"
            )
    }


# =========================================================
# FORMAT OUTPUT
# =========================================================

def format_strength_report(
    result
):
    home = (
        result[
            "home"
        ]
    )

    away = (
        result[
            "away"
        ]
    )

    hr = (
        home[
            "ratings"
        ]
    )

    hm = (
        home[
            "metrics"
        ]
    )

    he = (
        home[
            "own_elo"
        ]
    )

    ar = (
        away[
            "ratings"
        ]
    )

    am = (
        away[
            "metrics"
        ]
    )

    ae = (
        away[
            "own_elo"
        ]
    )

    lines = []

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "👑 BETTING BAYIN"
    )

    lines.append(
        "INDEPENDENT STRENGTH MODEL V4"
    )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append("")

    # =====================================================
    # HOME
    # =====================================================

    lines.append(
        f"🏠 {home['team']}"
    )

    lines.append(
        f"Form: "
        f"{hr['form'] * 100:.1f}/100"
    )

    lines.append(
        f"Attack: "
        f"{hr['attack'] * 100:.1f}/100"
    )

    lines.append(
        f"Defence: "
        f"{hr['defence'] * 100:.1f}/100"
    )

    lines.append(
        f"Performance Strength: "
        f"{hr['performance_strength'] * 100:.1f}/100"
    )

    lines.append(
        f"Own Elo: "
        f"{he.get('elo')}"
    )

    lines.append(
        f"Own Elo Rank: "
        f"#{he.get('rank')}"
    )

    lines.append(
        f"Elo Strength: "
        f"{hr['elo_strength'] * 100:.1f}/100"
    )

    lines.append(
        f"Trusted Data: "
        f"{hm['trusted_ratio'] * 100:.0f}%"
    )

    lines.append(
        f"Opponent Elo Coverage: "
        f"{hm['opponent_elo_coverage'] * 100:.0f}%"
    )

    lines.append(
        f"Data Confidence: "
        f"{hr['data_confidence'] * 100:.1f}%"
    )

    lines.append(
        f"Final Strength: "
        f"{hr['adjusted_strength'] * 100:.1f}/100"
    )

    lines.append("")

    # =====================================================
    # AWAY
    # =====================================================

    lines.append(
        f"✈️ {away['team']}"
    )

    lines.append(
        f"Form: "
        f"{ar['form'] * 100:.1f}/100"
    )

    lines.append(
        f"Attack: "
        f"{ar['attack'] * 100:.1f}/100"
    )

    lines.append(
        f"Defence: "
        f"{ar['defence'] * 100:.1f}/100"
    )

    lines.append(
        f"Performance Strength: "
        f"{ar['performance_strength'] * 100:.1f}/100"
    )

    lines.append(
        f"Own Elo: "
        f"{ae.get('elo')}"
    )

    lines.append(
        f"Own Elo Rank: "
        f"#{ae.get('rank')}"
    )

    lines.append(
        f"Elo Strength: "
        f"{ar['elo_strength'] * 100:.1f}/100"
    )

    lines.append(
        f"Trusted Data: "
        f"{am['trusted_ratio'] * 100:.0f}%"
    )

    lines.append(
        f"Opponent Elo Coverage: "
        f"{am['opponent_elo_coverage'] * 100:.0f}%"
    )

    lines.append(
        f"Data Confidence: "
        f"{ar['data_confidence'] * 100:.1f}%"
    )

    lines.append(
        f"Final Strength: "
        f"{ar['adjusted_strength'] * 100:.1f}/100"
    )

    lines.append("")

    # =====================================================
    # COMPARISON
    # =====================================================

    lines.append(
        "⚖️ Strength Difference: "
        f"{result['strength_difference']:+.3f}"
    )

    if result.get(
        "elo_difference"
    ) is not None:

        lines.append(
            "🌍 Elo Difference: "
            f"{result['elo_difference']:+.0f}"
        )

    lines.append("")

    lines.append(
        "📐 Raw Lean: "
        f"{result['raw_lean']}"
    )

    lines.append(
        "🛡 Reliable Lean: "
        f"{result['reliable_lean']}"
    )

    lines.append(
        "🎯 Model Confidence: "
        f"{result['reliability']['status']}"
    )

    if result[
        "reliability"
    ][
        "reasons"
    ]:

        lines.append("")

        lines.append(
            "Reliability Check:"
        )

        for reason in result[
            "reliability"
        ][
            "reasons"
        ]:

            lines.append(
                f"• {reason}"
            )

    lines.append("")

    lines.append(
        "🚫 Bookmaker odds used: NO"
    )

    lines.append(
        "✅ Own-team historical Elo used: "
        + (
            "YES"
            if result[
                "own_team_elo_used"
            ]
            else "NO"
        )
    )

    lines.append(
        "✅ Opponent historical Elo used: YES"
    )

    lines.append(
        "🛡 Future Elo leakage: BLOCKED"
    )

    return "\n".join(
        lines
    )