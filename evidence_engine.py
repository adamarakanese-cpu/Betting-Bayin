# =========================================================
# BETTING BAYIN
# EVIDENCE ENGINE V4
#
# Critical vs Optional Research Failure
# =========================================================


def safe_float(
    value,
    default=0.0
):
    try:
        return float(value)

    except (
        TypeError,
        ValueError
    ):
        return default


# =========================================================
# RESEARCH QUALITY
# =========================================================

def get_research_quality(
    research
):

    quality = research.get(
        "research_quality",
        {}
    )

    score = safe_float(
        quality.get(
            "score",
            0
        )
    )

    return max(
        0.0,
        min(
            1.0,
            score
        )
    )


# =========================================================
# FORM QUALITY
# =========================================================

def get_form_quality(
    research
):

    form = research.get(
        "calculated_form",
        {}
    )

    home = form.get(
        "home",
        {}
    )

    away = form.get(
        "away",
        {}
    )

    home_matches = (
        home.get(
            "matches",
            0
        )
        or 0
    )

    away_matches = (
        away.get(
            "matches",
            0
        )
        or 0
    )

    minimum = min(
        home_matches,
        away_matches
    )

    if minimum >= 5:
        return 1.0

    if minimum == 4:
        return 0.8

    if minimum == 3:
        return 0.6

    if minimum == 2:
        return 0.4

    if minimum == 1:
        return 0.2

    return 0.0


# =========================================================
# TRUSTED SOURCE STRENGTH
# =========================================================

def source_strength(
    research
):

    all_matches = (
        research.get(
            "home_recent_matches",
            []
        )
        +
        research.get(
            "away_recent_matches",
            []
        )
    )

    if not all_matches:
        return 0.0

    trusted = sum(
        1
        for item in all_matches
        if item.get(
            "trusted_source"
        )
    )

    return (
        trusted
        / len(all_matches)
    )


# =========================================================
# VERIFIED SECTION COUNT
# =========================================================

def count_verified_sections(
    research
):

    score = 0

    form = research.get(
        "calculated_form",
        {}
    )

    home_form = form.get(
        "home",
        {}
    )

    away_form = form.get(
        "away",
        {}
    )

    if (
        home_form.get(
            "matches",
            0
        )
        >= 3
    ):
        score += 1

    if (
        away_form.get(
            "matches",
            0
        )
        >= 3
    ):
        score += 1

    injuries = research.get(
        "injuries",
        {}
    )

    if (
        injuries.get("home")
        or injuries.get("away")
    ):
        score += 1

    suspensions = research.get(
        "suspensions",
        {}
    )

    if (
        suspensions.get("home")
        or suspensions.get("away")
    ):
        score += 1

    lineups = research.get(
        "lineups",
        {}
    )

    if (
        lineups.get("home")
        or lineups.get("away")
    ):
        score += 1

    if research.get(
        "head_to_head_matches"
    ):
        score += 1

    if research.get(
        "league_context"
    ):
        score += 1

    rest = research.get(
        "rest_and_schedule",
        {}
    )

    if (
        isinstance(rest, dict)
        and (
            rest.get("home")
            or rest.get("away")
        )
    ):
        score += 1

    if research.get(
        "match_importance"
    ):
        score += 1

    if research.get(
        "tactical_notes"
    ):
        score += 1

    return score


# =========================================================
# RESEARCH ERROR CLASSIFICATION
# =========================================================

def classify_research_errors(
    research
):

    raw_errors = research.get(
        "raw_research_errors",
        {}
    )

    home_error = raw_errors.get(
        "home"
    )

    away_error = raw_errors.get(
        "away"
    )

    team_news_error = (
        raw_errors.get(
            "team_news"
        )
    )

    context_error = (
        raw_errors.get(
            "context"
        )
    )

    critical_errors = []

    optional_errors = []

    # Recent result data is critical.
    if home_error:
        critical_errors.append(
            "home_results"
        )

    if away_error:
        critical_errors.append(
            "away_results"
        )

    # Team news and context improve confidence,
    # but should not automatically kill analysis.
    if team_news_error:
        optional_errors.append(
            "team_news"
        )

    if context_error:
        optional_errors.append(
            "match_context"
        )

    return {
        "critical": critical_errors,
        "optional": optional_errors
    }


# =========================================================
# TEAM NEWS STATUS
# =========================================================

def team_news_verified(
    research
):

    raw_errors = research.get(
        "raw_research_errors",
        {}
    )

    if raw_errors.get(
        "team_news"
    ):
        return False

    return True


# =========================================================
# FINAL EVIDENCE SCORE
# =========================================================

def calculate_evidence_score(
    market_analysis,
    research
):

    best = market_analysis.get(
        "best_candidate"
    )

    if not best:

        return {
            "decision": "PASS",
            "reason": (
                "No usable market candidate."
            ),
            "final_score": 0,
            "candidate": None
        }

    # -----------------------------------------------------
    # BASIC SCORES
    # -----------------------------------------------------

    market_score = safe_float(
        best.get(
            "screening_score",
            0
        )
    )

    research_quality = (
        get_research_quality(
            research
        )
    )

    form_quality = (
        get_form_quality(
            research
        )
    )

    trusted_source_ratio = (
        source_strength(
            research
        )
    )

    verified_sections = (
        count_verified_sections(
            research
        )
    )

    completeness = min(
        verified_sections / 10,
        1.0
    )

    # -----------------------------------------------------
    # FORM COUNTS
    # -----------------------------------------------------

    form = research.get(
        "calculated_form",
        {}
    )

    home_matches = (
        form.get(
            "home",
            {}
        ).get(
            "matches",
            0
        )
        or 0
    )

    away_matches = (
        form.get(
            "away",
            {}
        ).get(
            "matches",
            0
        )
        or 0
    )

    # -----------------------------------------------------
    # RESEARCH ERRORS
    # -----------------------------------------------------

    error_info = (
        classify_research_errors(
            research
        )
    )

    critical_errors = (
        error_info[
            "critical"
        ]
    )

    optional_errors = (
        error_info[
            "optional"
        ]
    )

    news_verified = (
        team_news_verified(
            research
        )
    )

    # -----------------------------------------------------
    # CORE WEIGHTED SCORE
    # -----------------------------------------------------

    final_score = (

        market_score
        * 0.30

        + research_quality
        * 100
        * 0.25

        + form_quality
        * 100
        * 0.20

        + trusted_source_ratio
        * 100
        * 0.15

        + completeness
        * 100
        * 0.10
    )

    # -----------------------------------------------------
    # OPTIONAL RESEARCH FAILURE PENALTIES
    # -----------------------------------------------------

    optional_penalty = 0

    if "team_news" in optional_errors:
        optional_penalty += 5

    if "match_context" in optional_errors:
        optional_penalty += 3

    final_score -= optional_penalty

    final_score = max(
        0,
        min(
            100,
            final_score
        )
    )

    # -----------------------------------------------------
    # DECISION RULES
    # -----------------------------------------------------

    if critical_errors:

        decision = "PASS"

        reason = (
            "Critical recent-results "
            "research failed."
        )

    elif home_matches < 3:

        decision = "PASS"

        reason = (
            "Not enough verified "
            "home-team recent matches."
        )

    elif away_matches < 3:

        decision = "PASS"

        reason = (
            "Not enough verified "
            "away-team recent matches."
        )

    elif research_quality < 0.55:

        decision = "PASS"

        reason = (
            "Research quality below "
            "minimum threshold."
        )

    elif trusted_source_ratio < 0.50:

        decision = "PASS"

        reason = (
            "Trusted-source coverage "
            "is too weak."
        )

    # -----------------------------------------------------
    # HIGH CONFIDENCE CANDIDATE
    #
    # Requires team-news pass too.
    # -----------------------------------------------------

    elif (
        final_score >= 82
        and research_quality >= 0.75
        and form_quality >= 0.80
        and trusted_source_ratio >= 0.65
        and news_verified
        and not optional_errors
    ):

        decision = "BET_CANDIDATE"

        reason = (
            "Market structure, recent form, "
            "research quality and source "
            "verification passed the current "
            "high-confidence thresholds."
        )

    # -----------------------------------------------------
    # CAUTION
    # -----------------------------------------------------

    elif final_score >= 65:

        decision = "CAUTION"

        if not news_verified:

            reason = (
                "Core match evidence is usable, "
                "but player/injury/team-news "
                "research is incomplete."
            )

        elif optional_errors:

            reason = (
                "Core evidence is usable, "
                "but some optional research "
                "sections are incomplete."
            )

        else:

            reason = (
                "Evidence is usable but "
                "not strong enough for "
                "a high-confidence bet."
            )

    else:

        decision = "PASS"

        reason = (
            "Combined evidence score "
            "is below threshold."
        )

    # -----------------------------------------------------
    # RETURN
    # -----------------------------------------------------

    return {

        "decision": decision,

        "reason": reason,

        "final_score": round(
            final_score,
            2
        ),

        "market_score": round(
            market_score,
            2
        ),

        "research_quality": round(
            research_quality,
            2
        ),

        "form_quality": round(
            form_quality,
            2
        ),

        "trusted_source_ratio": round(
            trusted_source_ratio,
            2
        ),

        "verified_sections": (
            verified_sections
        ),

        "home_match_samples": (
            home_matches
        ),

        "away_match_samples": (
            away_matches
        ),

        "team_news_verified": (
            news_verified
        ),

        "critical_errors": (
            critical_errors
        ),

        "optional_errors": (
            optional_errors
        ),

        "optional_penalty": (
            optional_penalty
        ),

        "candidate": best
    }


# =========================================================
# TELEGRAM / TERMINAL FORMAT
# =========================================================

def format_final_decision(
    result
):

    candidate = result.get(
        "candidate"
    )

    if not candidate:

        return (
            "🔴 BETTING BAYIN — PASS\n\n"
            f"{result['reason']}"
        )

    decision = result[
        "decision"
    ]

    if decision == "BET_CANDIDATE":

        icon = "🟢"
        title = "BET CANDIDATE"

    elif decision == "CAUTION":

        icon = "🟡"
        title = "CAUTION"

    else:

        icon = "🔴"
        title = "PASS"

    news_text = (
        "YES"
        if result.get(
            "team_news_verified"
        )
        else "NO"
    )

    optional_errors = (
        result.get(
            "optional_errors",
            []
        )
    )

    optional_text = (
        ", ".join(
            optional_errors
        )
        if optional_errors
        else "None"
    )

    return (
        "━━━━━━━━━━━━━━━━━━\n"
        "👑 BETTING BAYIN\n"
        "VERIFIED EVIDENCE CHECK\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        f"{icon} {title}\n\n"

        f"📊 Market: "
        f"{candidate['market']}\n"

        f"🎯 Selection: "
        f"{candidate['selection']}\n"

        f"💰 Odds: "
        f"{candidate['odds']}\n\n"

        f"📈 Market Score: "
        f"{result['market_score']}/100\n"

        f"🌐 Research Quality: "
        f"{result['research_quality'] * 100:.0f}%\n"

        f"⚽ Form Quality: "
        f"{result['form_quality'] * 100:.0f}%\n"

        f"🔗 Trusted Sources: "
        f"{result['trusted_source_ratio'] * 100:.0f}%\n"

        f"🏠 Home Samples: "
        f"{result['home_match_samples']}\n"

        f"✈️ Away Samples: "
        f"{result['away_match_samples']}\n"

        f"🩹 Team News Verified: "
        f"{news_text}\n"

        f"⚠️ Missing Optional Data: "
        f"{optional_text}\n"

        f"➖ Data Penalty: "
        f"{result['optional_penalty']} points\n"

        f"🧠 Combined Score: "
        f"{result['final_score']}/100\n\n"

        f"Reason:\n"
        f"{result['reason']}"
    )