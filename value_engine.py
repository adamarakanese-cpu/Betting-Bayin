# =========================================================
# BETTING BAYIN
# MARKET VALUE + CONFLICT ENGINE V1
# =========================================================
#
# Inputs:
# - market_analysis from analysis_engine.py
# - calibrated independent probabilities
#
# Outputs:
# - bookmaker no-vig probability
# - model probability
# - edge
# - expected value
# - disagreement detection
# - BET / CAUTION / PASS / DATA_CONFLICT
#
# IMPORTANT:
# Thresholds in V1 are conservative engineering rules.
# They are NOT trained/calibrated betting thresholds yet.
# =========================================================


def clamp(value, low=0.0, high=1.0):
    return max(
        low,
        min(
            high,
            value
        )
    )


def safe_float(
    value,
    default=None
):
    try:
        return float(value)

    except (
        TypeError,
        ValueError
    ):
        return default


# =========================================================
# NORMALIZE SELECTION
# =========================================================

def normalize_selection(
    selection
):

    text = str(
        selection or ""
    ).strip().lower()

    aliases = {
        "w1": "home_win",
        "1": "home_win",
        "home": "home_win",
        "home win": "home_win",

        "x": "draw",
        "draw": "draw",

        "w2": "away_win",
        "2": "away_win",
        "away": "away_win",
        "away win": "away_win",
    }

    return aliases.get(
        text
    )


# =========================================================
# FIND MAIN 1X2 MARKET
# =========================================================

def find_main_1x2_market(
    market_analysis
):

    markets = market_analysis.get(
        "markets",
        []
    )

    for market in markets:

        name = str(
            market.get(
                "market_name",
                ""
            )
        ).strip().lower()

        market_type = str(
            market.get(
                "market_type",
                ""
            )
        ).strip().lower()

        # Only normal 1X2.
        # Do NOT use 2UP or special market.
        if name != "1x2":
            continue

        if (
            market_type
            and
            market_type != "exclusive"
        ):
            continue

        selections = (
            market.get(
                "selections",
                []
            )
        )

        parsed = {}

        for item in selections:

            key = (
                normalize_selection(
                    item.get(
                        "selection"
                    )
                )
            )

            if not key:
                continue

            odds = safe_float(
                item.get(
                    "odds"
                )
            )

            if (
                odds is None
                or odds <= 1.0
            ):
                continue

            fair_probability = (
                safe_float(
                    item.get(
                        "fair_probability"
                    )
                )
            )

            parsed[key] = {
                "odds": odds,
                "market_fair_probability":
                    fair_probability
            }

        if all(
            key in parsed
            for key in [
                "home_win",
                "draw",
                "away_win",
            ]
        ):

            return {
                "market_name":
                    market.get(
                        "market_name"
                    ),

                "bookmaker_margin_percent":
                    market.get(
                        "bookmaker_margin_percent"
                    ),

                "selections":
                    parsed
            }

    return None


# =========================================================
# FALLBACK NO-VIG CALCULATION
# =========================================================

def calculate_no_vig(
    selections
):

    raw = {}

    total = 0.0

    for key, item in (
        selections.items()
    ):

        odds = item[
            "odds"
        ]

        probability = (
            1.0 / odds
        )

        raw[key] = probability

        total += probability

    if total <= 0:

        return None

    output = {}

    for key, probability in (
        raw.items()
    ):

        output[key] = (
            probability / total
        )

    return output


# =========================================================
# EXPECTED VALUE
# =========================================================

def calculate_ev(
    model_probability,
    bookmaker_odds
):

    # Decimal odds:
    #
    # EV = p * odds - 1

    return (
        model_probability
        *
        bookmaker_odds
        -
        1.0
    )


# =========================================================
# SINGLE SELECTION ANALYSIS
# =========================================================

def analyze_selection(
    selection_name,
    bookmaker,
    model_probability
):

    odds = bookmaker[
        "odds"
    ]

    market_probability = (
        bookmaker.get(
            "market_fair_probability"
        )
    )

    edge = (
        model_probability
        -
        market_probability
    )

    ev = calculate_ev(
        model_probability,
        odds
    )

    return {
        "selection":
            selection_name,

        "odds":
            round(
                odds,
                3
            ),

        "market_probability":
            round(
                market_probability,
                6
            ),

        "model_probability":
            round(
                model_probability,
                6
            ),

        "edge":
            round(
                edge,
                6
            ),

        "edge_percent":
            round(
                edge * 100,
                2
            ),

        "expected_value":
            round(
                ev,
                6
            ),

        "expected_value_percent":
            round(
                ev * 100,
                2
            )
    }


# =========================================================
# CONFLICT DETECTOR
# =========================================================

def detect_market_conflict(
    selections,
    calibration_result
):

    suitability = (
        calibration_result
        .get(
            "betting_suitability",
            {}
        )
        .get(
            "suitable_for_betting",
            "NO"
        )
    )

    reliability = (
        calibration_result[
            "one_x_two"
        ][
            "reliability_factor"
        ]
    )

    largest_gap = max(
        abs(
            item[
                "edge"
            ]
        )
        for item in selections
    )

    reasons = []

    # ---------------------------------------------
    # Large market disagreement + weak model
    # ---------------------------------------------

    if (
        largest_gap >= 0.15
        and
        suitability != "YES"
    ):

        reasons.append(
            "Model disagrees sharply with "
            "the bookmaker while the model "
            "is not betting-suitable."
        )

    if (
        largest_gap >= 0.20
        and
        reliability < 0.70
    ):

        reasons.append(
            "Extreme market/model disagreement "
            "with insufficient reliability."
        )

    return {
        "has_conflict":
            bool(reasons),

        "largest_probability_gap":
            round(
                largest_gap,
                6
            ),

        "largest_gap_percent":
            round(
                largest_gap * 100,
                2
            ),

        "reasons":
            reasons
    }


# =========================================================
# DECISION ENGINE
# =========================================================

def decide_value(
    selections,
    calibration_result,
    conflict
):

    suitability = (
        calibration_result[
            "betting_suitability"
        ][
            "suitable_for_betting"
        ]
    )

    reliability = (
        calibration_result[
            "one_x_two"
        ][
            "reliability_factor"
        ]
    )

    # =====================================================
    # HARD SAFETY GATES
    # =====================================================

    if conflict[
        "has_conflict"
    ]:

        return {
            "decision":
                "DATA_CONFLICT",

            "reason":
                (
                    "Market and model disagree "
                    "too strongly for the current "
                    "data quality."
                ),

            "best_selection":
                None
        }

    if suitability == "NO":

        return {
            "decision":
                "PASS",

            "reason":
                (
                    "Independent probability model "
                    "is not currently suitable "
                    "for betting use."
                ),

            "best_selection":
                None
        }

    # =====================================================
    # FIND POSITIVE EDGE
    # =====================================================

    ranked = sorted(
        selections,
        key=lambda item:
            item[
                "expected_value"
            ],
        reverse=True
    )

    best = ranked[0]

    edge = best[
        "edge"
    ]

    ev = best[
        "expected_value"
    ]

    # =====================================================
    # CURRENT V1 THRESHOLDS
    #
    # These must later be learned from backtesting.
    # =====================================================

    if (
        suitability == "YES"
        and
        reliability >= 0.75
        and
        edge >= 0.05
        and
        ev >= 0.05
    ):

        return {
            "decision":
                "BET_CANDIDATE",

            "reason":
                (
                    "Positive model edge and "
                    "expected value passed the "
                    "current conservative thresholds."
                ),

            "best_selection":
                best
        }

    if (
        edge >= 0.03
        and
        ev >= 0.02
    ):

        return {
            "decision":
                "CAUTION",

            "reason":
                (
                    "Potential value exists, "
                    "but evidence is not strong "
                    "enough for a full candidate."
                ),

            "best_selection":
                best
        }

    return {
        "decision":
            "PASS",

        "reason":
            (
                "No selection has sufficient "
                "calibrated edge and expected value."
            ),

        "best_selection":
            best
    }


# =========================================================
# MAIN VALUE ENGINE
# =========================================================

def calculate_market_value(
    market_analysis,
    calibration_result
):

    market = find_main_1x2_market(
        market_analysis
    )

    if not market:

        return {
            "decision":
                "PASS",

            "reason":
                "Usable standard 1X2 market not found.",

            "model_stage":
                "MARKET_VALUE_V1"
        }

    # =====================================================
    # ENSURE NO-VIG PROBABILITIES
    # =====================================================

    selections = market[
        "selections"
    ]

    missing_fair = any(
        item[
            "market_fair_probability"
        ]
        is None
        for item in (
            selections.values()
        )
    )

    if missing_fair:

        no_vig = calculate_no_vig(
            selections
        )

        if not no_vig:

            return {
                "decision":
                    "PASS",

                "reason":
                    "Could not calculate bookmaker no-vig probabilities.",

                "model_stage":
                    "MARKET_VALUE_V1"
            }

        for key in selections:

            selections[
                key
            ][
                "market_fair_probability"
            ] = no_vig[key]

    # =====================================================
    # CALIBRATED MODEL
    # =====================================================

    calibrated = (
        calibration_result[
            "one_x_two"
        ][
            "calibrated"
        ]
    )

    comparison = []

    for selection in [
        "home_win",
        "draw",
        "away_win",
    ]:

        comparison.append(
            analyze_selection(
                selection_name=
                    selection,

                bookmaker=
                    selections[
                        selection
                    ],

                model_probability=
                    calibrated[
                        selection
                    ]
            )
        )

    # =====================================================
    # CONFLICT
    # =====================================================

    conflict = (
        detect_market_conflict(
            comparison,
            calibration_result
        )
    )

    # =====================================================
    # DECISION
    # =====================================================

    decision = (
        decide_value(
            comparison,
            calibration_result,
            conflict
        )
    )

    return {
        "home_team":
            calibration_result[
                "home_team"
            ],

        "away_team":
            calibration_result[
                "away_team"
            ],

        "market":
            market,

        "comparison":
            comparison,

        "conflict":
            conflict,

        "betting_suitability":
            calibration_result[
                "betting_suitability"
            ],

        "reliability_factor":
            calibration_result[
                "one_x_two"
            ][
                "reliability_factor"
            ],

        "decision":
            decision[
                "decision"
            ],

        "reason":
            decision[
                "reason"
            ],

        "best_selection":
            decision[
                "best_selection"
            ],

        "model_stage":
            "MARKET_VALUE_V1"
    }


# =========================================================
# FORMATTER
# =========================================================

def format_value_report(
    result
):

    if "comparison" not in result:

        return (
            "🔴 PASS\n\n"
            f"{result.get('reason')}"
        )

    home = result[
        "home_team"
    ]

    away = result[
        "away_team"
    ]

    labels = {
        "home_win":
            home,

        "draw":
            "Draw",

        "away_win":
            away,
    }

    lines = []

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "👑 BETTING BAYIN"
    )

    lines.append(
        "MARKET VALUE ENGINE V1"
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
        "📊 MODEL vs MARKET"
    )

    lines.append("")

    for item in result[
        "comparison"
    ]:

        name = labels[
            item["selection"]
        ]

        lines.append(
            f"🎯 {name}"
        )

        lines.append(
            f"Odds: "
            f"{item['odds']:.3f}"
        )

        lines.append(
            f"Market No-Vig: "
            f"{item['market_probability'] * 100:.1f}%"
        )

        lines.append(
            f"Calibrated Model: "
            f"{item['model_probability'] * 100:.1f}%"
        )

        lines.append(
            f"Edge: "
            f"{item['edge_percent']:+.2f}%"
        )

        lines.append(
            f"EV: "
            f"{item['expected_value_percent']:+.2f}%"
        )

        lines.append("")

    conflict = result[
        "conflict"
    ]

    lines.append(
        "⚠️ Largest Market Gap: "
        f"{conflict['largest_gap_percent']:.2f}%"
    )

    lines.append(
        "🛡 Reliability: "
        f"{result['reliability_factor'] * 100:.1f}%"
    )

    lines.append(
        "🎯 Betting Suitability: "
        f"{result['betting_suitability']['suitable_for_betting']}"
    )

    lines.append("")

    decision = result[
        "decision"
    ]

    if decision == "BET_CANDIDATE":
        icon = "🟢"

    elif decision == "CAUTION":
        icon = "🟡"

    elif decision == "DATA_CONFLICT":
        icon = "🚨"

    else:
        icon = "🔴"

    lines.append(
        f"{icon} FINAL: {decision}"
    )

    lines.append(
        f"Reason: "
        f"{result['reason']}"
    )

    if conflict[
        "reasons"
    ]:

        lines.append("")

        lines.append(
            "Conflict Check:"
        )

        for reason in conflict[
            "reasons"
        ]:

            lines.append(
                f"• {reason}"
            )

    return "\n".join(
        lines
    )