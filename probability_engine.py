from math import exp, factorial, sqrt


# =========================================================
# BETTING BAYIN
# INDEPENDENT PROBABILITY ENGINE V2
# =========================================================
#
# Compatible with:
# - Strength Engine V4
# - Calibration Engine V1
# - Value Engine V1
#
# INPUTS
#
# - Verified recent form
# - Attack / defence
# - Performance strength
# - Own-team historical Elo strength
# - Opponent historical Elo coverage
# - Source trust
# - Data confidence
#
# OUTPUTS
#
# - Expected goals
# - 1X2 probabilities
# - Fair odds
# - Double chance
# - Goal totals
# - BTTS
# - Team scoring
# - Correct-score probabilities
# - Model reliability
# - Sanity checks
#
# IMPORTANT
#
# - Bookmaker odds are NOT used.
# - Market prices are NOT used.
# - Future Elo leakage must already be blocked
#   by Strength Engine V4.
#
# =========================================================


MAX_GOALS = 10


# =========================================================
# GENERIC FOOTBALL SCORING BASELINE
# =========================================================
#
# This is a generic structural prior.
# It is NOT bookmaker-derived.
#
# Total baseline:
# 1.40 + 1.15 = 2.55 expected goals.
#
# =========================================================

BASE_HOME_XG = 1.40
BASE_AWAY_XG = 1.15


# =========================================================
# MODEL WEIGHTS
# =========================================================
#
# Keep the components separated:
#
# Attack / defence matchup
# Performance difference
# Elo strength difference
#
# Strength V4 already combines these concepts
# for its final strength number, so V2 does NOT
# simply inject adjusted_strength heavily again.
#
# =========================================================

ATTACK_DEFENCE_WEIGHT = 0.90

PERFORMANCE_DIFF_WEIGHT = 0.40

ELO_DIFF_WEIGHT = 0.55

FINAL_STRENGTH_STABILIZER = 0.15


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


def safe_float(
    value,
    default=0.5
):
    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError
    ):
        return default


def fair_odds(
    probability
):
    if (
        probability is None
        or probability <= 0
    ):
        return None

    return round(
        1.0
        /
        probability,
        3
    )


# =========================================================
# STRENGTH RESULT HELPERS
# =========================================================

def get_team_components(
    team_data
):
    ratings = (
        team_data.get(
            "ratings",
            {}
        )
        or {}
    )

    metrics = (
        team_data.get(
            "metrics",
            {}
        )
        or {}
    )

    own_elo = (
        team_data.get(
            "own_elo",
            {}
        )
        or {}
    )

    return {
        "form":
            safe_float(
                ratings.get(
                    "form"
                ),
                0.50
            ),

        "attack":
            safe_float(
                ratings.get(
                    "attack"
                ),
                0.50
            ),

        "defence":
            safe_float(
                ratings.get(
                    "defence"
                ),
                0.50
            ),

        "performance_strength":
            safe_float(
                ratings.get(
                    "performance_strength"
                ),
                safe_float(
                    ratings.get(
                        "raw_strength"
                    ),
                    0.50
                )
            ),

        "elo_strength":
            safe_float(
                ratings.get(
                    "elo_strength"
                ),
                safe_float(
                    own_elo.get(
                        "strength_score"
                    ),
                    0.50
                )
            ),

        "adjusted_strength":
            safe_float(
                ratings.get(
                    "adjusted_strength"
                ),
                0.50
            ),

        "data_confidence":
            safe_float(
                ratings.get(
                    "data_confidence"
                ),
                0.0
            ),

        "trusted_ratio":
            safe_float(
                metrics.get(
                    "trusted_ratio"
                ),
                0.0
            ),

        "opponent_elo_coverage":
            safe_float(
                metrics.get(
                    "opponent_elo_coverage"
                ),
                0.0
            ),

        "own_elo_available":
            bool(
                own_elo.get(
                    "available",
                    False
                )
            ),

        "own_elo_value":
            own_elo.get(
                "elo"
            ),

        "own_elo_rank":
            own_elo.get(
                "rank"
            ),
    }


# =========================================================
# MODEL CONFIDENCE V2
# =========================================================

def calculate_model_confidence(
    strength_result
):
    home = (
        strength_result[
            "home"
        ]
    )

    away = (
        strength_result[
            "away"
        ]
    )

    hc = (
        get_team_components(
            home
        )
    )

    ac = (
        get_team_components(
            away
        )
    )

    home_conf = (
        clamp(
            hc[
                "data_confidence"
            ]
        )
    )

    away_conf = (
        clamp(
            ac[
                "data_confidence"
            ]
        )
    )

    home_opp_elo = (
        clamp(
            hc[
                "opponent_elo_coverage"
            ]
        )
    )

    away_opp_elo = (
        clamp(
            ac[
                "opponent_elo_coverage"
            ]
        )
    )

    home_trust = (
        clamp(
            hc[
                "trusted_ratio"
            ]
        )
    )

    away_trust = (
        clamp(
            ac[
                "trusted_ratio"
            ]
        )
    )

    home_own_elo = (
        1.0
        if hc[
            "own_elo_available"
        ]
        else 0.0
    )

    away_own_elo = (
        1.0
        if ac[
            "own_elo_available"
        ]
        else 0.0
    )

    average_data_confidence = (
        home_conf
        +
        away_conf
    ) / 2.0

    minimum_team_confidence = min(
        home_conf,
        away_conf
    )

    average_elo_coverage = (
        home_opp_elo
        +
        away_opp_elo
    ) / 2.0

    average_source_trust = (
        home_trust
        +
        away_trust
    ) / 2.0

    own_elo_coverage = (
        home_own_elo
        +
        away_own_elo
    ) / 2.0

    # =====================================================
    # V2 RELIABILITY SCORE
    # =====================================================
    #
    # Data confidence remains the largest component.
    #
    # Own-team Elo is explicitly included because
    # Strength V4 now uses it as a fundamental signal.
    #
    # =====================================================

    confidence_score = (

        average_data_confidence
        *
        0.45

        +

        average_elo_coverage
        *
        0.20

        +

        average_source_trust
        *
        0.20

        +

        own_elo_coverage
        *
        0.15
    )

    confidence_score = (
        clamp(
            confidence_score
        )
    )

    reasons = []

    if (
        minimum_team_confidence
        <
        0.45
    ):
        reasons.append(
            "One team's data confidence "
            "is below 45%."
        )

    if (
        average_source_trust
        <
        0.50
    ):
        reasons.append(
            "Average source trust "
            "is below 50%."
        )

    if (
        average_elo_coverage
        <
        0.60
    ):
        reasons.append(
            "Opponent Elo coverage "
            "is below 60%."
        )

    if (
        own_elo_coverage
        <
        1.0
    ):
        reasons.append(
            "Own-team historical Elo "
            "is incomplete."
        )

    # =====================================================
    # STATUS
    # =====================================================

    if (
        minimum_team_confidence
        <
        0.45
    ):
        status = (
            "LOW"
        )

    elif (
        confidence_score
        >=
        0.82
        and
        minimum_team_confidence
        >=
        0.70
        and
        average_source_trust
        >=
        0.65
    ):
        status = (
            "HIGH"
        )

    elif (
        confidence_score
        >=
        0.65
        and
        minimum_team_confidence
        >=
        0.55
    ):
        status = (
            "MEDIUM"
        )

    else:
        status = (
            "LOW"
        )

    return {
        "score":
            round(
                confidence_score,
                3
            ),

        "status":
            status,

        "minimum_team_confidence":
            round(
                minimum_team_confidence,
                3
            ),

        "average_data_confidence":
            round(
                average_data_confidence,
                3
            ),

        "average_elo_coverage":
            round(
                average_elo_coverage,
                3
            ),

        "average_source_trust":
            round(
                average_source_trust,
                3
            ),

        "own_elo_coverage":
            round(
                own_elo_coverage,
                3
            ),

        "reasons":
            reasons,
    }


# =========================================================
# INFORMATION WEIGHT
# =========================================================

def calculate_information_weight(
    home_confidence,
    away_confidence
):
    home_confidence = (
        clamp(
            home_confidence
        )
    )

    away_confidence = (
        clamp(
            away_confidence
        )
    )

    average_confidence = (
        home_confidence
        +
        away_confidence
    ) / 2.0

    weakest_confidence = min(
        home_confidence,
        away_confidence
    )

    # =====================================================
    # Weakest side matters strongly.
    #
    # A match with:
    # Home = 99%
    # Away = 25%
    #
    # should NOT behave like a 62% reliable dataset.
    # =====================================================

    matchup_confidence = (

        weakest_confidence
        *
        0.60

        +

        average_confidence
        *
        0.40
    )

    matchup_confidence = (
        clamp(
            matchup_confidence
        )
    )

    # Keep some model information,
    # but low confidence strongly shrinks
    # predictions toward baseline.

    information_weight = (
        0.30
        +
        matchup_confidence
        *
        0.70
    )

    information_weight = (
        clamp(
            information_weight,
            0.30,
            1.00
        )
    )

    return {
        "matchup_confidence":
            matchup_confidence,

        "information_weight":
            information_weight,

        "average_confidence":
            average_confidence,

        "weakest_confidence":
            weakest_confidence,
    }


# =========================================================
# EXPECTED GOALS V2
# =========================================================

def calculate_expected_goals(
    strength_result
):
    home = (
        strength_result[
            "home"
        ]
    )

    away = (
        strength_result[
            "away"
        ]
    )

    hc = (
        get_team_components(
            home
        )
    )

    ac = (
        get_team_components(
            away
        )
    )

    # =====================================================
    # CORE COMPONENTS
    # =====================================================

    home_attack = (
        hc[
            "attack"
        ]
    )

    home_defence = (
        hc[
            "defence"
        ]
    )

    away_attack = (
        ac[
            "attack"
        ]
    )

    away_defence = (
        ac[
            "defence"
        ]
    )

    home_performance = (
        hc[
            "performance_strength"
        ]
    )

    away_performance = (
        ac[
            "performance_strength"
        ]
    )

    home_elo_strength = (
        hc[
            "elo_strength"
        ]
    )

    away_elo_strength = (
        ac[
            "elo_strength"
        ]
    )

    home_final_strength = (
        hc[
            "adjusted_strength"
        ]
    )

    away_final_strength = (
        ac[
            "adjusted_strength"
        ]
    )

    home_conf = (
        hc[
            "data_confidence"
        ]
    )

    away_conf = (
        ac[
            "data_confidence"
        ]
    )

    # =====================================================
    # ATTACK vs DEFENCE
    # =====================================================

    home_attack_edge = (
        home_attack
        -
        away_defence
    )

    away_attack_edge = (
        away_attack
        -
        home_defence
    )

    # =====================================================
    # PERFORMANCE DIFFERENCE
    # =====================================================

    performance_difference = (
        home_performance
        -
        away_performance
    )

    # =====================================================
    # OWN ELO DIFFERENCE
    #
    # We use normalized Elo-strength scores,
    # NOT raw Elo points directly.
    # =====================================================

    elo_strength_difference = (
        home_elo_strength
        -
        away_elo_strength
    )

    # =====================================================
    # FINAL STRENGTH DIFFERENCE
    #
    # Low weight only.
    #
    # This is a stabilizer because adjusted strength
    # already contains performance + Elo.
    # =====================================================

    final_strength_difference = (
        home_final_strength
        -
        away_final_strength
    )

    # =====================================================
    # RAW XG
    # =====================================================

    raw_home_xg = (

        BASE_HOME_XG

        +

        home_attack_edge
        *
        ATTACK_DEFENCE_WEIGHT

        +

        performance_difference
        *
        PERFORMANCE_DIFF_WEIGHT

        +

        elo_strength_difference
        *
        ELO_DIFF_WEIGHT

        +

        final_strength_difference
        *
        FINAL_STRENGTH_STABILIZER
    )

    raw_away_xg = (

        BASE_AWAY_XG

        +

        away_attack_edge
        *
        ATTACK_DEFENCE_WEIGHT

        -

        performance_difference
        *
        PERFORMANCE_DIFF_WEIGHT

        -

        elo_strength_difference
        *
        ELO_DIFF_WEIGHT

        -

        final_strength_difference
        *
        FINAL_STRENGTH_STABILIZER
    )

    # =====================================================
    # RAW LIMITS
    # =====================================================

    raw_home_xg = (
        clamp(
            raw_home_xg,
            0.30,
            3.50
        )
    )

    raw_away_xg = (
        clamp(
            raw_away_xg,
            0.25,
            3.25
        )
    )

    # =====================================================
    # INFORMATION / UNCERTAINTY SHRINKAGE
    # =====================================================

    information = (
        calculate_information_weight(
            home_conf,
            away_conf
        )
    )

    information_weight = (
        information[
            "information_weight"
        ]
    )

    matchup_confidence = (
        information[
            "matchup_confidence"
        ]
    )

    # =====================================================
    # SHRINK TOWARD GENERIC FOOTBALL BASELINE
    # =====================================================

    home_xg = (

        BASE_HOME_XG

        +

        (
            raw_home_xg
            -
            BASE_HOME_XG
        )
        *
        information_weight
    )

    away_xg = (

        BASE_AWAY_XG

        +

        (
            raw_away_xg
            -
            BASE_AWAY_XG
        )
        *
        information_weight
    )

    # =====================================================
    # TOTAL-GOALS STABILITY
    # =====================================================
    #
    # Prevent a moderate-strength difference from
    # accidentally creating extreme total-goal models.
    #
    # This does NOT force total xG to 2.55.
    #
    # =====================================================

    total_xg = (
        home_xg
        +
        away_xg
    )

    if total_xg > 4.50:

        scale = (
            4.50
            /
            total_xg
        )

        home_xg *= (
            scale
        )

        away_xg *= (
            scale
        )

    elif total_xg < 1.20:

        scale = (
            1.20
            /
            max(
                total_xg,
                0.01
            )
        )

        home_xg *= (
            scale
        )

        away_xg *= (
            scale
        )

    # =====================================================
    # FINAL LIMITS
    # =====================================================

    home_xg = (
        clamp(
            home_xg,
            0.30,
            3.50
        )
    )

    away_xg = (
        clamp(
            away_xg,
            0.25,
            3.25
        )
    )

    return {
        "home_xg":
            round(
                home_xg,
                3
            ),

        "away_xg":
            round(
                away_xg,
                3
            ),

        "total_xg":
            round(
                home_xg
                +
                away_xg,
                3
            ),

        "raw_home_xg":
            round(
                raw_home_xg,
                3
            ),

        "raw_away_xg":
            round(
                raw_away_xg,
                3
            ),

        "base_home_xg":
            BASE_HOME_XG,

        "base_away_xg":
            BASE_AWAY_XG,

        "home_attack_edge":
            round(
                home_attack_edge,
                3
            ),

        "away_attack_edge":
            round(
                away_attack_edge,
                3
            ),

        "performance_difference":
            round(
                performance_difference,
                3
            ),

        "elo_strength_difference":
            round(
                elo_strength_difference,
                3
            ),

        "final_strength_difference":
            round(
                final_strength_difference,
                3
            ),

        # Keep legacy key for compatibility.
        "strength_difference":
            round(
                final_strength_difference,
                3
            ),

        "matchup_confidence":
            round(
                matchup_confidence,
                3
            ),

        "information_weight":
            round(
                information_weight,
                3
            ),

        "average_confidence":
            round(
                information[
                    "average_confidence"
                ],
                3
            ),

        "weakest_confidence":
            round(
                information[
                    "weakest_confidence"
                ],
                3
            ),

        "home_elo_strength":
            round(
                home_elo_strength,
                3
            ),

        "away_elo_strength":
            round(
                away_elo_strength,
                3
            ),

        "home_own_elo":
            hc[
                "own_elo_value"
            ],

        "away_own_elo":
            ac[
                "own_elo_value"
            ],

        "model_version":
            "XG_V2",
    }


# =========================================================
# POISSON
# =========================================================

def poisson_probability(
    goals,
    expected_goals
):
    return (

        exp(
            -expected_goals
        )

        *

        expected_goals
        **
        goals

        /

        factorial(
            goals
        )
    )


# =========================================================
# SCORE MATRIX
# =========================================================

def build_score_matrix(
    home_xg,
    away_xg
):
    matrix = []

    total_probability = (
        0.0
    )

    for home_goals in range(
        MAX_GOALS + 1
    ):

        home_probability = (
            poisson_probability(
                home_goals,
                home_xg
            )
        )

        for away_goals in range(
            MAX_GOALS + 1
        ):

            away_probability = (
                poisson_probability(
                    away_goals,
                    away_xg
                )
            )

            probability = (
                home_probability
                *
                away_probability
            )

            total_probability += (
                probability
            )

            matrix.append({
                "home_goals":
                    home_goals,

                "away_goals":
                    away_goals,

                "probability":
                    probability,
            })

    # =====================================================
    # Normalize truncated matrix
    # =====================================================

    if total_probability > 0:

        for score in matrix:

            score[
                "probability"
            ] = (

                score[
                    "probability"
                ]

                /

                total_probability
            )

    return matrix


# =========================================================
# 1X2
# =========================================================

def calculate_1x2(
    matrix
):
    home_win = (
        0.0
    )

    draw = (
        0.0
    )

    away_win = (
        0.0
    )

    for score in matrix:

        home_goals = (
            score[
                "home_goals"
            ]
        )

        away_goals = (
            score[
                "away_goals"
            ]
        )

        probability = (
            score[
                "probability"
            ]
        )

        if (
            home_goals
            >
            away_goals
        ):

            home_win += (
                probability
            )

        elif (
            home_goals
            ==
            away_goals
        ):

            draw += (
                probability
            )

        else:

            away_win += (
                probability
            )

    total = (
        home_win
        +
        draw
        +
        away_win
    )

    return {
        "home_win":
            round(
                home_win,
                6
            ),

        "draw":
            round(
                draw,
                6
            ),

        "away_win":
            round(
                away_win,
                6
            ),

        "total":
            round(
                total,
                6
            ),

        "fair_odds": {

            "home_win":
                fair_odds(
                    home_win
                ),

            "draw":
                fair_odds(
                    draw
                ),

            "away_win":
                fair_odds(
                    away_win
                ),
        },
    }


# =========================================================
# DOUBLE CHANCE
# =========================================================

def calculate_double_chance(
    one_x_two
):
    home = (
        one_x_two[
            "home_win"
        ]
    )

    draw = (
        one_x_two[
            "draw"
        ]
    )

    away = (
        one_x_two[
            "away_win"
        ]
    )

    one_x = (
        home
        +
        draw
    )

    x_two = (
        draw
        +
        away
    )

    twelve = (
        home
        +
        away
    )

    return {
        "1X":
            round(
                one_x,
                6
            ),

        "X2":
            round(
                x_two,
                6
            ),

        "12":
            round(
                twelve,
                6
            ),

        "fair_odds": {

            "1X":
                fair_odds(
                    one_x
                ),

            "X2":
                fair_odds(
                    x_two
                ),

            "12":
                fair_odds(
                    twelve
                ),
        },
    }


# =========================================================
# TOTAL GOALS
# =========================================================

def calculate_totals(
    matrix
):
    over_15 = (
        0.0
    )

    under_15 = (
        0.0
    )

    over_25 = (
        0.0
    )

    under_25 = (
        0.0
    )

    over_35 = (
        0.0
    )

    under_35 = (
        0.0
    )

    for score in matrix:

        total_goals = (

            score[
                "home_goals"
            ]

            +

            score[
                "away_goals"
            ]
        )

        probability = (
            score[
                "probability"
            ]
        )

        if total_goals > 1.5:

            over_15 += (
                probability
            )

        else:

            under_15 += (
                probability
            )

        if total_goals > 2.5:

            over_25 += (
                probability
            )

        else:

            under_25 += (
                probability
            )

        if total_goals > 3.5:

            over_35 += (
                probability
            )

        else:

            under_35 += (
                probability
            )

    return {
        "over_1_5":
            round(
                over_15,
                6
            ),

        "under_1_5":
            round(
                under_15,
                6
            ),

        "over_2_5":
            round(
                over_25,
                6
            ),

        "under_2_5":
            round(
                under_25,
                6
            ),

        "over_3_5":
            round(
                over_35,
                6
            ),

        "under_3_5":
            round(
                under_35,
                6
            ),

        "fair_odds": {

            "over_1_5":
                fair_odds(
                    over_15
                ),

            "under_1_5":
                fair_odds(
                    under_15
                ),

            "over_2_5":
                fair_odds(
                    over_25
                ),

            "under_2_5":
                fair_odds(
                    under_25
                ),

            "over_3_5":
                fair_odds(
                    over_35
                ),

            "under_3_5":
                fair_odds(
                    under_35
                ),
        },
    }


# =========================================================
# BTTS
# =========================================================

def calculate_btts(
    matrix
):
    yes = (
        0.0
    )

    no = (
        0.0
    )

    for score in matrix:

        probability = (
            score[
                "probability"
            ]
        )

        if (
            score[
                "home_goals"
            ]
            >
            0
            and
            score[
                "away_goals"
            ]
            >
            0
        ):

            yes += (
                probability
            )

        else:

            no += (
                probability
            )

    return {
        "yes":
            round(
                yes,
                6
            ),

        "no":
            round(
                no,
                6
            ),

        "fair_odds": {

            "yes":
                fair_odds(
                    yes
                ),

            "no":
                fair_odds(
                    no
                ),
        },
    }


# =========================================================
# TEAM SCORING
# =========================================================

def calculate_team_scoring(
    home_xg,
    away_xg
):
    home_to_score = (

        1.0
        -
        exp(
            -home_xg
        )
    )

    away_to_score = (

        1.0
        -
        exp(
            -away_xg
        )
    )

    home_clean_sheet = (
        exp(
            -away_xg
        )
    )

    away_clean_sheet = (
        exp(
            -home_xg
        )
    )

    return {
        "home_to_score":
            round(
                home_to_score,
                6
            ),

        "away_to_score":
            round(
                away_to_score,
                6
            ),

        "home_clean_sheet":
            round(
                home_clean_sheet,
                6
            ),

        "away_clean_sheet":
            round(
                away_clean_sheet,
                6
            ),

        "fair_odds": {

            "home_to_score":
                fair_odds(
                    home_to_score
                ),

            "away_to_score":
                fair_odds(
                    away_to_score
                ),

            "home_clean_sheet":
                fair_odds(
                    home_clean_sheet
                ),

            "away_clean_sheet":
                fair_odds(
                    away_clean_sheet
                ),
        },
    }


# =========================================================
# MOST LIKELY SCORES
# =========================================================

def most_likely_scores(
    matrix,
    limit=5
):
    ordered = sorted(
        matrix,
        key=lambda item:
            item[
                "probability"
            ],
        reverse=True
    )

    output = []

    for score in ordered[
        :limit
    ]:

        output.append({

            "score":
                (
                    f"{score['home_goals']}"
                    "-"
                    f"{score['away_goals']}"
                ),

            "probability":
                round(
                    score[
                        "probability"
                    ],
                    6
                ),
        })

    return output


# =========================================================
# PROBABILITY UNCERTAINTY
# =========================================================

def calculate_uncertainty(
    one_x_two,
    confidence
):
    confidence_score = (
        safe_float(
            confidence.get(
                "score"
            ),
            0.0
        )
    )

    minimum_team_confidence = (
        safe_float(
            confidence.get(
                "minimum_team_confidence"
            ),
            0.0
        )
    )

    # =====================================================
    # Larger uncertainty when model confidence is low.
    #
    # This is NOT a statistical confidence interval.
    # It is an engineering uncertainty band.
    # =====================================================

    reliability = (

        confidence_score
        *
        0.60

        +

        minimum_team_confidence
        *
        0.40
    )

    reliability = (
        clamp(
            reliability
        )
    )

    uncertainty_margin = (

        0.04

        +

        (
            1.0
            -
            reliability
        )
        *
        0.12
    )

    uncertainty_margin = (
        clamp(
            uncertainty_margin,
            0.04,
            0.16
        )
    )

    ranges = {}

    for key in (
        "home_win",
        "draw",
        "away_win",
    ):

        probability = (
            one_x_two[
                key
            ]
        )

        ranges[
            key
        ] = {

            "low":
                round(
                    clamp(
                        probability
                        -
                        uncertainty_margin,
                        0.0,
                        1.0
                    ),
                    6
                ),

            "high":
                round(
                    clamp(
                        probability
                        +
                        uncertainty_margin,
                        0.0,
                        1.0
                    ),
                    6
                ),
        }

    return {
        "reliability":
            round(
                reliability,
                3
            ),

        "margin":
            round(
                uncertainty_margin,
                3
            ),

        "ranges":
            ranges,

        "type":
            "ENGINEERING_UNCERTAINTY_BAND",
    }


# =========================================================
# SANITY CHECKS V2
# =========================================================

def run_sanity_checks(
    matrix,
    one_x_two,
    totals,
    btts,
    expected_goals
):
    matrix_total = sum(
        score[
            "probability"
        ]
        for score in matrix
    )

    one_x_two_total = (

        one_x_two[
            "home_win"
        ]

        +

        one_x_two[
            "draw"
        ]

        +

        one_x_two[
            "away_win"
        ]
    )

    over_under_15_total = (

        totals[
            "over_1_5"
        ]

        +

        totals[
            "under_1_5"
        ]
    )

    over_under_25_total = (

        totals[
            "over_2_5"
        ]

        +

        totals[
            "under_2_5"
        ]
    )

    over_under_35_total = (

        totals[
            "over_3_5"
        ]

        +

        totals[
            "under_3_5"
        ]
    )

    btts_total = (

        btts[
            "yes"
        ]

        +

        btts[
            "no"
        ]
    )

    tolerance = (
        0.0001
    )

    home_xg = (
        expected_goals[
            "home_xg"
        ]
    )

    away_xg = (
        expected_goals[
            "away_xg"
        ]
    )

    checks = {

        "score_matrix_sum":
            abs(
                matrix_total
                -
                1.0
            )
            <=
            tolerance,

        "one_x_two_sum":
            abs(
                one_x_two_total
                -
                1.0
            )
            <=
            tolerance,

        "over_under_1_5_sum":
            abs(
                over_under_15_total
                -
                1.0
            )
            <=
            tolerance,

        "over_under_2_5_sum":
            abs(
                over_under_25_total
                -
                1.0
            )
            <=
            tolerance,

        "over_under_3_5_sum":
            abs(
                over_under_35_total
                -
                1.0
            )
            <=
            tolerance,

        "btts_sum":
            abs(
                btts_total
                -
                1.0
            )
            <=
            tolerance,

        "home_xg_valid":
            (
                0.30
                <=
                home_xg
                <=
                3.50
            ),

        "away_xg_valid":
            (
                0.25
                <=
                away_xg
                <=
                3.25
            ),

        "total_xg_valid":
            (
                1.20
                <=
                (
                    home_xg
                    +
                    away_xg
                )
                <=
                4.50
            ),
    }

    checks[
        "all_passed"
    ] = all(
        checks.values()
    )

    return checks


# =========================================================
# MODEL SIGNAL SUMMARY
# =========================================================

def build_model_signals(
    strength_result,
    expected_goals,
    one_x_two
):
    home_team = (
        strength_result[
            "home"
        ][
            "team"
        ]
    )

    away_team = (
        strength_result[
            "away"
        ][
            "team"
        ]
    )

    strength_difference = (
        expected_goals[
            "final_strength_difference"
        ]
    )

    elo_difference = (
        expected_goals[
            "elo_strength_difference"
        ]
    )

    xg_difference = (
        expected_goals[
            "home_xg"
        ]
        -
        expected_goals[
            "away_xg"
        ]
    )

    if (
        one_x_two[
            "home_win"
        ]
        >
        one_x_two[
            "away_win"
        ]
    ):

        probability_lean = (
            home_team
        )

    elif (
        one_x_two[
            "away_win"
        ]
        >
        one_x_two[
            "home_win"
        ]
    ):

        probability_lean = (
            away_team
        )

    else:

        probability_lean = (
            "EVEN"
        )

    return {
        "strength_lean":
            strength_result.get(
                "reliable_lean"
            ),

        "probability_lean":
            probability_lean,

        "strength_difference":
            round(
                strength_difference,
                3
            ),

        "elo_strength_difference":
            round(
                elo_difference,
                3
            ),

        "xg_difference":
            round(
                xg_difference,
                3
            ),

        "signals_aligned":
            (
                strength_result.get(
                    "reliable_lean"
                )
                ==
                probability_lean
            ),
    }


# =========================================================
# MAIN MODEL V2
# =========================================================

def calculate_match_probabilities(
    strength_result
):
    # =====================================================
    # EXPECTED GOALS
    # =====================================================

    expected_goals = (
        calculate_expected_goals(
            strength_result
        )
    )

    home_xg = (
        expected_goals[
            "home_xg"
        ]
    )

    away_xg = (
        expected_goals[
            "away_xg"
        ]
    )

    # =====================================================
    # SCORE MATRIX
    # =====================================================

    matrix = (
        build_score_matrix(
            home_xg,
            away_xg
        )
    )

    # =====================================================
    # MARKETS
    # =====================================================

    one_x_two = (
        calculate_1x2(
            matrix
        )
    )

    double_chance = (
        calculate_double_chance(
            one_x_two
        )
    )

    totals = (
        calculate_totals(
            matrix
        )
    )

    btts = (
        calculate_btts(
            matrix
        )
    )

    team_scoring = (
        calculate_team_scoring(
            home_xg,
            away_xg
        )
    )

    scores = (
        most_likely_scores(
            matrix,
            limit=5
        )
    )

    # =====================================================
    # CONFIDENCE
    # =====================================================

    confidence = (
        calculate_model_confidence(
            strength_result
        )
    )

    # =====================================================
    # UNCERTAINTY
    # =====================================================

    uncertainty = (
        calculate_uncertainty(
            one_x_two,
            confidence
        )
    )

    # =====================================================
    # SANITY
    # =====================================================

    sanity = (
        run_sanity_checks(
            matrix,
            one_x_two,
            totals,
            btts,
            expected_goals
        )
    )

    # =====================================================
    # SIGNAL SUMMARY
    # =====================================================

    model_signals = (
        build_model_signals(
            strength_result,
            expected_goals,
            one_x_two
        )
    )

    return {

        "home_team":
            strength_result[
                "home"
            ][
                "team"
            ],

        "away_team":
            strength_result[
                "away"
            ][
                "team"
            ],

        "expected_goals":
            expected_goals,

        "one_x_two":
            one_x_two,

        "double_chance":
            double_chance,

        "totals":
            totals,

        "btts":
            btts,

        "team_scoring":
            team_scoring,

        "most_likely_scores":
            scores,

        "model_confidence":
            confidence,

        "uncertainty":
            uncertainty,

        "model_signals":
            model_signals,

        "sanity_checks":
            sanity,

        "bookmaker_odds_used":
            False,

        "own_team_elo_used":
            bool(
                strength_result.get(
                    "own_team_elo_used",
                    False
                )
            ),

        "model_stage":
            "INDEPENDENT_PROBABILITY_V2",
    }


# =========================================================
# FORMAT REPORT
# =========================================================

def format_probability_report(
    result
):
    home_team = (
        result[
            "home_team"
        ]
    )

    away_team = (
        result[
            "away_team"
        ]
    )

    xg = (
        result[
            "expected_goals"
        ]
    )

    one_x_two = (
        result[
            "one_x_two"
        ]
    )

    totals = (
        result[
            "totals"
        ]
    )

    btts = (
        result[
            "btts"
        ]
    )

    dc = (
        result[
            "double_chance"
        ]
    )

    confidence = (
        result[
            "model_confidence"
        ]
    )

    uncertainty = (
        result[
            "uncertainty"
        ]
    )

    signals = (
        result[
            "model_signals"
        ]
    )

    lines = []

    # =====================================================
    # HEADER
    # =====================================================

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "👑 BETTING BAYIN"
    )

    lines.append(
        "INDEPENDENT PROBABILITY MODEL V2"
    )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append("")

    lines.append(
        f"⚽ {home_team} vs {away_team}"
    )

    lines.append("")

    # =====================================================
    # EXPECTED GOALS
    # =====================================================

    lines.append(
        "🥅 EXPECTED GOALS"
    )

    lines.append(
        f"🏠 {home_team}: "
        f"{xg['home_xg']:.2f}"
    )

    lines.append(
        f"✈️ {away_team}: "
        f"{xg['away_xg']:.2f}"
    )

    lines.append(
        f"⚽ Total xG: "
        f"{xg['total_xg']:.2f}"
    )

    lines.append("")

    # =====================================================
    # MODEL SIGNALS
    # =====================================================

    lines.append(
        "🧠 MODEL SIGNALS"
    )

    lines.append(
        "Strength Lean: "
        f"{signals['strength_lean']}"
    )

    lines.append(
        "Probability Lean: "
        f"{signals['probability_lean']}"
    )

    lines.append(
        "Elo Strength Diff: "
        f"{signals['elo_strength_difference']:+.3f}"
    )

    lines.append(
        "Final Strength Diff: "
        f"{signals['strength_difference']:+.3f}"
    )

    lines.append(
        "xG Diff: "
        f"{signals['xg_difference']:+.3f}"
    )

    lines.append(
        "Signals Aligned: "
        + (
            "YES"
            if signals[
                "signals_aligned"
            ]
            else "NO"
        )
    )

    lines.append("")

    # =====================================================
    # 1X2
    # =====================================================

    lines.append(
        "🎯 1X2"
    )

    lines.append(
        f"🏠 {home_team}: "
        f"{one_x_two['home_win'] * 100:.1f}% "
        f"| Fair "
        f"{one_x_two['fair_odds']['home_win']:.2f}"
    )

    lines.append(
        f"🤝 Draw: "
        f"{one_x_two['draw'] * 100:.1f}% "
        f"| Fair "
        f"{one_x_two['fair_odds']['draw']:.2f}"
    )

    lines.append(
        f"✈️ {away_team}: "
        f"{one_x_two['away_win'] * 100:.1f}% "
        f"| Fair "
        f"{one_x_two['fair_odds']['away_win']:.2f}"
    )

    lines.append("")

    # =====================================================
    # UNCERTAINTY
    # =====================================================

    margin = (
        uncertainty[
            "margin"
        ]
        *
        100
    )

    lines.append(
        "⚠️ MODEL UNCERTAINTY"
    )

    lines.append(
        f"Approx. probability band: "
        f"±{margin:.1f}%"
    )

    lines.append(
        f"Reliability: "
        f"{uncertainty['reliability'] * 100:.1f}%"
    )

    lines.append("")

    # =====================================================
    # DOUBLE CHANCE
    # =====================================================

    lines.append(
        "🛡 DOUBLE CHANCE"
    )

    lines.append(
        f"1X: "
        f"{dc['1X'] * 100:.1f}% "
        f"| Fair "
        f"{dc['fair_odds']['1X']:.2f}"
    )

    lines.append(
        f"X2: "
        f"{dc['X2'] * 100:.1f}% "
        f"| Fair "
        f"{dc['fair_odds']['X2']:.2f}"
    )

    lines.append(
        f"12: "
        f"{dc['12'] * 100:.1f}% "
        f"| Fair "
        f"{dc['fair_odds']['12']:.2f}"
    )

    lines.append("")

    # =====================================================
    # TOTALS
    # =====================================================

    lines.append(
        "⚽ TOTAL GOALS"
    )

    lines.append(
        f"Over 1.5: "
        f"{totals['over_1_5'] * 100:.1f}% "
        f"| Fair "
        f"{totals['fair_odds']['over_1_5']:.2f}"
    )

    lines.append(
        f"Under 1.5: "
        f"{totals['under_1_5'] * 100:.1f}% "
        f"| Fair "
        f"{totals['fair_odds']['under_1_5']:.2f}"
    )

    lines.append(
        f"Over 2.5: "
        f"{totals['over_2_5'] * 100:.1f}% "
        f"| Fair "
        f"{totals['fair_odds']['over_2_5']:.2f}"
    )

    lines.append(
        f"Under 2.5: "
        f"{totals['under_2_5'] * 100:.1f}% "
        f"| Fair "
        f"{totals['fair_odds']['under_2_5']:.2f}"
    )

    lines.append(
        f"Over 3.5: "
        f"{totals['over_3_5'] * 100:.1f}% "
        f"| Fair "
        f"{totals['fair_odds']['over_3_5']:.2f}"
    )

    lines.append(
        f"Under 3.5: "
        f"{totals['under_3_5'] * 100:.1f}% "
        f"| Fair "
        f"{totals['fair_odds']['under_3_5']:.2f}"
    )

    lines.append("")

    # =====================================================
    # BTTS
    # =====================================================

    lines.append(
        "🥅 BTTS"
    )

    lines.append(
        f"YES: "
        f"{btts['yes'] * 100:.1f}% "
        f"| Fair "
        f"{btts['fair_odds']['yes']:.2f}"
    )

    lines.append(
        f"NO: "
        f"{btts['no'] * 100:.1f}% "
        f"| Fair "
        f"{btts['fair_odds']['no']:.2f}"
    )

    lines.append("")

    # =====================================================
    # MOST LIKELY SCORES
    # =====================================================

    lines.append(
        "🔢 MOST LIKELY SCORES"
    )

    for index, score in enumerate(
        result[
            "most_likely_scores"
        ],
        start=1
    ):

        lines.append(
            f"{index}. "
            f"{score['score']} — "
            f"{score['probability'] * 100:.1f}%"
        )

    lines.append("")

    # =====================================================
    # CONFIDENCE
    # =====================================================

    lines.append(
        "🎯 Model Confidence: "
        f"{confidence['status']} "
        f"({confidence['score'] * 100:.1f}%)"
    )

    lines.append(
        "📉 Weakest Team Data: "
        f"{confidence['minimum_team_confidence'] * 100:.1f}%"
    )

    lines.append(
        "🔗 Source Trust: "
        f"{confidence['average_source_trust'] * 100:.1f}%"
    )

    lines.append(
        "🌍 Opponent Elo Coverage: "
        f"{confidence['average_elo_coverage'] * 100:.1f}%"
    )

    lines.append(
        "🌍 Own Elo Coverage: "
        f"{confidence['own_elo_coverage'] * 100:.1f}%"
    )

    if confidence[
        "reasons"
    ]:

        lines.append("")

        lines.append(
            "Confidence Notes:"
        )

        for reason in confidence[
            "reasons"
        ]:

            lines.append(
                f"• {reason}"
            )

    lines.append("")

    # =====================================================
    # SANITY
    # =====================================================

    lines.append(
        "🧪 Sanity Checks: "
        + (
            "PASS"
            if result[
                "sanity_checks"
            ][
                "all_passed"
            ]
            else "FAIL"
        )
    )

    lines.append("")

    lines.append(
        "🚫 Bookmaker odds used: NO"
    )

    lines.append(
        "✅ Own-team historical Elo used: "
        + (
            "YES"
            if result.get(
                "own_team_elo_used"
            )
            else "NO"
        )
    )

    lines.append(
        "🛡 Independent model: YES"
    )

    return "\n".join(
        lines
    )