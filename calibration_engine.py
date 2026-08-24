# =========================================================
# BETTING BAYIN
# CALIBRATION + UNCERTAINTY ENGINE V1
# =========================================================
#
# Purpose:
# - Do NOT treat raw model probabilities as absolute truth.
# - Reduce confidence when one team has weak data.
# - Shrink extreme probabilities toward a neutral prior.
# - Produce betting suitability status.
#
# Bookmaker odds are NOT used here.
# =========================================================


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


# =========================================================
# RELIABILITY FACTOR
# =========================================================

def calculate_reliability_factor(
    probability_result
):
    confidence = probability_result.get(
        "model_confidence",
        {}
    )

    overall_score = float(
        confidence.get(
            "score",
            0.0
        )
        or 0.0
    )

    weakest_team = float(
        confidence.get(
            "minimum_team_confidence",
            0.0
        )
        or 0.0
    )

    source_trust = float(
        confidence.get(
            "average_source_trust",
            0.0
        )
        or 0.0
    )

    elo_coverage = float(
        confidence.get(
            "average_elo_coverage",
            0.0
        )
        or 0.0
    )

    # Weakest-side data matters most.
    reliability = (
        overall_score * 0.30
        +
        weakest_team * 0.40
        +
        source_trust * 0.20
        +
        elo_coverage * 0.10
    )

    return clamp(
        reliability,
        0.0,
        1.0
    )


# =========================================================
# NEUTRAL PRIOR
# =========================================================

def get_neutral_1x2_prior():
    """
    Generic football prior.

    Not bookmaker-derived.

    Home side receives a modest structural advantage.
    """

    return {
        "home_win": 0.43,
        "draw": 0.28,
        "away_win": 0.29
    }


# =========================================================
# SHRINK 1X2
# =========================================================

def calibrate_1x2(
    probability_result
):
    raw = probability_result[
        "one_x_two"
    ]

    prior = (
        get_neutral_1x2_prior()
    )

    reliability = (
        calculate_reliability_factor(
            probability_result
        )
    )

    # Low reliability = stronger shrinkage.
    #
    # Keep some model information even at low quality,
    # but do not let weak evidence dominate.

    model_weight = (
        0.20
        +
        reliability * 0.70
    )

    model_weight = clamp(
        model_weight,
        0.20,
        0.90
    )

    prior_weight = (
        1.0
        -
        model_weight
    )

    calibrated_home = (
        raw["home_win"]
        * model_weight
        +
        prior["home_win"]
        * prior_weight
    )

    calibrated_draw = (
        raw["draw"]
        * model_weight
        +
        prior["draw"]
        * prior_weight
    )

    calibrated_away = (
        raw["away_win"]
        * model_weight
        +
        prior["away_win"]
        * prior_weight
    )

    total = (
        calibrated_home
        +
        calibrated_draw
        +
        calibrated_away
    )

    calibrated_home /= total
    calibrated_draw /= total
    calibrated_away /= total

    return {
        "raw": {
            "home_win": round(
                raw["home_win"],
                6
            ),
            "draw": round(
                raw["draw"],
                6
            ),
            "away_win": round(
                raw["away_win"],
                6
            ),
        },

        "calibrated": {
            "home_win": round(
                calibrated_home,
                6
            ),
            "draw": round(
                calibrated_draw,
                6
            ),
            "away_win": round(
                calibrated_away,
                6
            ),
        },

        "neutral_prior":
            prior,

        "reliability_factor":
            round(
                reliability,
                3
            ),

        "model_weight":
            round(
                model_weight,
                3
            ),

        "prior_weight":
            round(
                prior_weight,
                3
            )
    }


# =========================================================
# MARKET-SPECIFIC SHRINKAGE
# =========================================================

def shrink_binary_probability(
    probability,
    reliability,
    neutral=0.50
):
    model_weight = (
        0.25
        +
        reliability * 0.65
    )

    model_weight = clamp(
        model_weight,
        0.25,
        0.90
    )

    prior_weight = (
        1.0
        -
        model_weight
    )

    calibrated = (
        probability
        * model_weight
        +
        neutral
        * prior_weight
    )

    return clamp(
        calibrated,
        0.01,
        0.99
    )


# =========================================================
# CALIBRATE TOTALS + BTTS
# =========================================================

def calibrate_binary_markets(
    probability_result,
    reliability
):
    totals = probability_result[
        "totals"
    ]

    btts = probability_result[
        "btts"
    ]

    calibrated = {}

    for key in [
        "over_1_5",
        "under_1_5",
        "over_2_5",
        "under_2_5",
        "over_3_5",
        "under_3_5",
    ]:

        calibrated[key] = round(
            shrink_binary_probability(
                totals[key],
                reliability
            ),
            6
        )

    calibrated_btts_yes = (
        shrink_binary_probability(
            btts["yes"],
            reliability
        )
    )

    calibrated_btts_no = (
        1.0
        -
        calibrated_btts_yes
    )

    return {
        "totals":
            calibrated,

        "btts": {
            "yes": round(
                calibrated_btts_yes,
                6
            ),

            "no": round(
                calibrated_btts_no,
                6
            )
        }
    }


# =========================================================
# SUITABILITY GATE
# =========================================================

def evaluate_betting_suitability(
    probability_result,
    calibration
):
    confidence = probability_result.get(
        "model_confidence",
        {}
    )

    reliability = calibration[
        "reliability_factor"
    ]

    weakest_team = float(
        confidence.get(
            "minimum_team_confidence",
            0.0
        )
        or 0.0
    )

    source_trust = float(
        confidence.get(
            "average_source_trust",
            0.0
        )
        or 0.0
    )

    sanity_ok = bool(
        probability_result.get(
            "sanity_checks",
            {}
        ).get(
            "all_passed",
            False
        )
    )

    reasons = []

    if not sanity_ok:
        reasons.append(
            "Probability sanity checks failed."
        )

    if weakest_team < 0.45:
        reasons.append(
            "Weakest-team data confidence is below 45%."
        )

    if source_trust < 0.55:
        reasons.append(
            "Average source trust is below 55%."
        )

    if reliability < 0.55:
        reasons.append(
            "Overall calibrated reliability is too low."
        )

    if reasons:
        status = "NO"

    elif reliability >= 0.75:
        status = "YES"

    else:
        status = "CAUTION"

    return {
        "suitable_for_betting":
            status,

        "reasons":
            reasons
    }


# =========================================================
# MAIN
# =========================================================

def calibrate_probability_model(
    probability_result
):

    one_x_two = (
        calibrate_1x2(
            probability_result
        )
    )

    reliability = (
        one_x_two[
            "reliability_factor"
        ]
    )

    binary = (
        calibrate_binary_markets(
            probability_result,
            reliability
        )
    )

    suitability = (
        evaluate_betting_suitability(
            probability_result,
            one_x_two
        )
    )

    return {
        "home_team":
            probability_result[
                "home_team"
            ],

        "away_team":
            probability_result[
                "away_team"
            ],

        "one_x_two":
            one_x_two,

        "binary_markets":
            binary,

        "betting_suitability":
            suitability,

        "bookmaker_odds_used":
            False,

        "model_stage":
            "CALIBRATION_UNCERTAINTY_V1"
    }


# =========================================================
# FORMAT
# =========================================================

def format_calibration_report(
    result
):

    home = result[
        "home_team"
    ]

    away = result[
        "away_team"
    ]

    one_x_two = result[
        "one_x_two"
    ]

    raw = one_x_two[
        "raw"
    ]

    calibrated = (
        one_x_two[
            "calibrated"
        ]
    )

    suitability = result[
        "betting_suitability"
    ]

    lines = []

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "👑 BETTING BAYIN"
    )

    lines.append(
        "CALIBRATION + UNCERTAINTY V1"
    )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append("")

    lines.append(
        f"⚽ {home} vs {away}"
    )

    lines.append("")

    lines.append(
        "📐 RAW 1X2"
    )

    lines.append(
        f"🏠 {home}: "
        f"{raw['home_win'] * 100:.1f}%"
    )

    lines.append(
        f"🤝 Draw: "
        f"{raw['draw'] * 100:.1f}%"
    )

    lines.append(
        f"✈️ {away}: "
        f"{raw['away_win'] * 100:.1f}%"
    )

    lines.append("")

    lines.append(
        "🛡 CALIBRATED 1X2"
    )

    lines.append(
        f"🏠 {home}: "
        f"{calibrated['home_win'] * 100:.1f}%"
    )

    lines.append(
        f"🤝 Draw: "
        f"{calibrated['draw'] * 100:.1f}%"
    )

    lines.append(
        f"✈️ {away}: "
        f"{calibrated['away_win'] * 100:.1f}%"
    )

    lines.append("")

    lines.append(
        "📊 Reliability Factor: "
        f"{one_x_two['reliability_factor'] * 100:.1f}%"
    )

    lines.append(
        "🧠 Model Weight: "
        f"{one_x_two['model_weight'] * 100:.1f}%"
    )

    lines.append(
        "⚖️ Prior Weight: "
        f"{one_x_two['prior_weight'] * 100:.1f}%"
    )

    lines.append("")

    lines.append(
        "🎯 Probability suitable for betting: "
        f"{suitability['suitable_for_betting']}"
    )

    if suitability[
        "reasons"
    ]:

        lines.append("")

        lines.append(
            "⚠️ Reasons:"
        )

        for reason in suitability[
            "reasons"
        ]:

            lines.append(
                f"• {reason}"
            )

    lines.append("")

    lines.append(
        "🚫 Bookmaker odds used: NO"
    )

    return "\n".join(
        lines
    )