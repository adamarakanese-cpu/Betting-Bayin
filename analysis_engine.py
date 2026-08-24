import math


# =========================================================
# BETTING BAYIN - MARKET MATH ENGINE V2
# =========================================================


def safe_float(value):
    try:
        number = float(value)

        if (
            math.isfinite(number)
            and number > 1.0
        ):
            return number

    except (TypeError, ValueError):
        pass

    return None


def normalize_text(value):
    return str(value or "").strip().lower()


# =========================================================
# MARKET CLASSIFICATION
# =========================================================

def classify_market(market_name):
    """
    exclusive:
        Outcomes form one complete mutually-exclusive market.
        We can calculate overround and no-vig probabilities.

    overlapping:
        Selections overlap.
        Example: Double Chance.
        Do NOT sum implied probabilities.

    special:
        Promotional / special settlement market.
        Do NOT treat as normal 1X2.

    unknown:
        Structure not yet safely recognized.
    """

    name = normalize_text(market_name)

    # Standard 1X2 only
    if name == "1x2":
        return "exclusive"

    # BTTS Yes / No
    if (
        "both teams to score" in name
        or name == "btts"
    ):
        return "exclusive"

    # Double Chance overlaps
    if "double chance" in name:
        return "overlapping"

    # 2UP is special settlement
    if "2up" in name:
        return "special"

    # Common Yes / No style markets
    if (
        "will score" in name
        or "at least one team" in name
    ):
        return "exclusive"

    return "unknown"


# =========================================================
# RAW IMPLIED PROBABILITY
# =========================================================

def implied_probability(odds):
    odds = safe_float(odds)

    if not odds:
        return None

    return 1.0 / odds


# =========================================================
# EXCLUSIVE MARKET CALCULATION
# =========================================================

def calculate_exclusive_market(market):
    selections = market.get(
        "selections",
        []
    )

    valid = []

    for selection in selections:

        odds = safe_float(
            selection.get("odds")
        )

        if not odds:
            continue

        raw_probability = (
            implied_probability(odds)
        )

        valid.append({
            "selection": str(
                selection.get(
                    "selection",
                    "Unknown"
                )
            ),
            "odds": odds,
            "raw_probability": raw_probability,
        })

    if len(valid) < 2:
        return None

    total_probability = sum(
        item["raw_probability"]
        for item in valid
    )

    if total_probability <= 0:
        return None

    overround = (
        total_probability - 1.0
    )

    margin_percent = (
        overround * 100
    )

    for item in valid:

        fair_probability = (
            item["raw_probability"]
            / total_probability
        )

        item[
            "fair_probability"
        ] = fair_probability

        item[
            "fair_odds"
        ] = (
            1.0 / fair_probability
        )

    return {
        "market_name": market.get(
            "market_name",
            "Unknown"
        ),
        "market_type": "exclusive",
        "overround": overround,
        "bookmaker_margin_percent": (
            margin_percent
        ),
        "selections": valid,
    }


# =========================================================
# NON-EXCLUSIVE MARKET
# =========================================================

def calculate_nonexclusive_market(
    market,
    market_type
):
    selections = market.get(
        "selections",
        []
    )

    valid = []

    for selection in selections:

        odds = safe_float(
            selection.get("odds")
        )

        if not odds:
            continue

        valid.append({
            "selection": str(
                selection.get(
                    "selection",
                    "Unknown"
                )
            ),
            "odds": odds,
            "raw_probability": (
                implied_probability(odds)
            ),
            "fair_probability": None,
            "fair_odds": None,
        })

    if not valid:
        return None

    return {
        "market_name": market.get(
            "market_name",
            "Unknown"
        ),
        "market_type": market_type,

        # IMPORTANT:
        # Margin is intentionally not calculated.
        "overround": None,
        "bookmaker_margin_percent": None,

        "selections": valid,
    }


# =========================================================
# RELIABILITY FOR MARKET STRUCTURE
# =========================================================

def structural_reliability(
    market_name,
    market_type
):
    name = normalize_text(
        market_name
    )

    if market_type == "special":
        return 0.35

    if market_type == "overlapping":
        return 0.45

    if market_type == "unknown":
        return 0.30

    if name == "1x2":
        return 0.95

    if (
        "both teams to score" in name
        or name == "btts"
    ):
        return 0.90

    return 0.75


# =========================================================
# SCREENING SCORE
# =========================================================

def calculate_screening_score(
    fair_probability,
    odds,
    margin_percent,
    reliability,
):
    """
    IMPORTANT:

    This is NOT true match probability.
    This is NOT predicted win probability.

    This score only ranks screenshot markets
    before independent football research.
    """

    probability_score = (
        fair_probability * 60
    )

    reliability_score = (
        reliability * 30
    )

    margin_penalty = 0

    if margin_percent is not None:

        if margin_percent > 10:
            margin_penalty += 12

        elif margin_percent > 7:
            margin_penalty += 8

        elif margin_percent > 5:
            margin_penalty += 5

        elif margin_percent > 3:
            margin_penalty += 2

    odds_penalty = 0

    if odds >= 6:
        odds_penalty = 15

    elif odds >= 4:
        odds_penalty = 10

    elif odds >= 3:
        odds_penalty = 7

    elif odds >= 2:
        odds_penalty = 3

    score = (
        probability_score
        + reliability_score
        - margin_penalty
        - odds_penalty
    )

    return max(
        0,
        min(100, score)
    )


# =========================================================
# MAIN ANALYSIS
# =========================================================

def analyze_betting_data(data):

    raw_markets = data.get(
        "markets",
        []
    )

    analyzed_markets = []
    candidates = []

    for market in raw_markets:

        market_name = market.get(
            "market_name",
            "Unknown"
        )

        market_type = classify_market(
            market_name
        )

        if market_type == "exclusive":

            analyzed = (
                calculate_exclusive_market(
                    market
                )
            )

        else:

            analyzed = (
                calculate_nonexclusive_market(
                    market,
                    market_type
                )
            )

        if not analyzed:
            continue

        reliability = (
            structural_reliability(
                market_name,
                market_type
            )
        )

        analyzed[
            "structural_reliability"
        ] = reliability

        analyzed_markets.append(
            analyzed
        )

        # -------------------------------------------------
        # ONLY exclusive markets can become V2 candidates
        # -------------------------------------------------

        if market_type != "exclusive":
            continue

        margin = analyzed.get(
            "bookmaker_margin_percent"
        )

        # Abnormal market
        if (
            margin is None
            or margin < -2
            or margin > 15
        ):
            continue

        for selection in analyzed[
            "selections"
        ]:

            fair_probability = (
                selection.get(
                    "fair_probability"
                )
            )

            if fair_probability is None:
                continue

            score = (
                calculate_screening_score(
                    fair_probability=(
                        fair_probability
                    ),
                    odds=selection["odds"],
                    margin_percent=margin,
                    reliability=reliability,
                )
            )

            candidates.append({
                "market": market_name,
                "selection": (
                    selection[
                        "selection"
                    ]
                ),
                "odds": (
                    selection["odds"]
                ),
                "market_implied_probability": (
                    fair_probability
                ),
                "fair_odds": (
                    selection["fair_odds"]
                ),
                "margin_percent": margin,
                "screening_score": score,
            })

    candidates.sort(
        key=lambda item: (
            item[
                "screening_score"
            ]
        ),
        reverse=True
    )

    best_candidate = (
        candidates[0]
        if candidates
        else None
    )

    # =====================================================
    # DECISION
    # =====================================================

    if not best_candidate:

        decision = "PASS"

        reason = (
            "No mathematically usable "
            "exclusive market was found."
        )

    elif (
        best_candidate[
            "market_implied_probability"
        ] < 0.55
    ):

        decision = "PASS"

        reason = (
            "Market probability is too weak "
            "for pre-research consideration."
        )

    else:

        decision = "RESEARCH_REQUIRED"

        reason = (
            "A market candidate exists, "
            "but bookmaker odds alone cannot "
            "justify a betting tip. "
            "Independent football research "
            "is required."
        )

    return {
        "decision": decision,
        "reason": reason,
        "best_candidate": (
            best_candidate
        ),
        "top_candidates": (
            candidates[:5]
        ),
        "markets": analyzed_markets,
    }


# =========================================================
# TELEGRAM / TERMINAL FORMATTER
# =========================================================

def format_analysis(result):

    decision = result[
        "decision"
    ]

    best = result[
        "best_candidate"
    ]

    if (
        decision == "PASS"
        or not best
    ):

        return (
            "🛑 BETTING BAYIN — PASS\n\n"
            f"Reason: "
            f"{result['reason']}\n\n"
            "Bookmaker odds တစ်ခုတည်းနဲ့ "
            "bet မရွေးပါ."
        )

    probability = (
        best[
            "market_implied_probability"
        ]
        * 100
    )

    return (
        "👑 BETTING BAYIN\n\n"
        "🔎 PRE-RESEARCH CANDIDATE\n\n"
        f"📊 Market: "
        f"{best['market']}\n"
        f"🎯 Selection: "
        f"{best['selection']}\n"
        f"💰 Odds: "
        f"{best['odds']:.3f}\n\n"
        f"📈 No-Vig Market Probability: "
        f"{probability:.1f}%\n"
        f"🏦 Bookmaker Margin: "
        f"{best['margin_percent']:.2f}%\n"
        f"🧮 Market Screening Score: "
        f"{best['screening_score']:.1f}/100\n\n"
        "🟡 STATUS: RESEARCH REQUIRED\n\n"
        "ဒီ selection ကို Final Tip "
        "မသတ်မှတ်သေးပါ။\n\n"
        "နောက်အဆင့်မှာ:\n"
        "• Team form\n"
        "• Home / Away form\n"
        "• Players\n"
        "• Injuries\n"
        "• Suspensions\n"
        "• Expected lineup\n"
        "• League statistics\n"
        "• Recent results\n"
        "• Tactical matchup\n"
        "• Schedule / rest\n"
        "• Independent evidence\n\n"
        "တွေစစ်ပြီးမှ BET / PASS "
        "ဆုံးဖြတ်ပါမယ်."
    )