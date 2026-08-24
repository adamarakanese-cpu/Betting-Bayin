import copy
from datetime import datetime

from research_engine import (
    research_recent_matches,
    research_team_news,
    research_match_context,
    clean_match_records,
    calculate_form,
    calculate_research_quality,
    call_research,
    source_domain,
    is_good_source,
)

from verification_engine import (
    verify_research,
)

from data_engine import (
    save_research_cache,
)


# =========================================================
# BETTING BAYIN V11.3
# EVIDENCE REPLACEMENT + TRUSTED-FIRST RECOVERY ENGINE
# =========================================================
#
# FLOW
#
# Existing verified evidence
#       ↓
# Detect weak / below-target side
#       ↓
# Round 1:
# Normal recovery if minimum quality is weak
#       ↓
# Round 2:
# Trusted-source targeted recovery
#       ↓
# Same match:
# Trusted evidence replaces weak evidence
#       ↓
# Trusted-first match selection
#       ↓
# Re-verify everything
#       ↓
# Save only if evidence improves
#
# IMPORTANT:
#
# - No bookmaker odds are used here.
# - No betting decision is made here.
# - Recovery cannot overwrite a better cache
#   with worse evidence.
# =========================================================


# =========================================================
# SETTINGS
# =========================================================

MIN_TRUSTED_RATIO = 0.40

TARGET_TRUSTED_RATIO = 0.60

MIN_TEAM_MATCHES = 3

TARGET_MATCHES = 5

MIN_IMPROVEMENT = 0.03

MAX_RECOVERY_ROUNDS = 2

MAX_MERGED_MATCHES = 8

MAX_TARGETED_RESULTS = 8


# =========================================================
# STRONG SOURCE TIERS
# =========================================================

PRIMARY_DOMAINS = {
    "fifa.com",
    "inside.fifa.com",
    "uefa.com",
}

STRONG_DOMAINS = {
    "espn.com",
    "bbc.com",
    "bbc.co.uk",
    "skysports.com",
    "fotmob.com",
    "soccerway.com",
    "worldfootball.net",
    "reuters.com",
    "transfermarkt.com",
    "theanalyst.com",
}


# =========================================================
# BASIC HELPERS
# =========================================================

def safe_float(
    value,
    default=0.0
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


def normalize_text(
    value
):
    return (
        str(
            value
            or ""
        )
        .strip()
        .lower()
    )


# =========================================================
# DATE PARSER
# =========================================================

def parse_match_date(
    value
):
    if isinstance(
        value,
        datetime
    ):
        return value

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

        except Exception:
            continue

    return datetime.min


# =========================================================
# TRUSTED RATIO
# =========================================================

def trusted_ratio(
    matches
):
    if not matches:
        return 0.0

    trusted_count = sum(
        1
        for match in matches
        if match.get(
            "trusted_source"
        ) is True
    )

    return (
        trusted_count
        /
        len(matches)
    )


# =========================================================
# TEAM QUALITY
# =========================================================

def team_quality(
    research,
    side
):
    key = (
        "home_recent_matches"
        if side == "home"
        else "away_recent_matches"
    )

    matches = (
        research.get(
            key,
            []
        )
        or []
    )

    trusted_count = sum(
        1
        for match in matches
        if match.get(
            "trusted_source"
        ) is True
    )

    trust = (
        trusted_ratio(
            matches
        )
    )

    count_score = min(
        len(matches)
        /
        TARGET_MATCHES,
        1.0
    )

    # Trust matters more than quantity.
    quality = (
        trust * 0.65
        +
        count_score * 0.35
    )

    return {
        "matches":
            len(matches),

        "trusted_matches":
            trusted_count,

        "trusted_ratio":
            round(
                trust,
                3
            ),

        "quality_score":
            round(
                quality,
                3
            ),
    }


# =========================================================
# MINIMUM QUALITY DETECTOR
# =========================================================

def detect_weak_sides(
    research
):
    home = (
        team_quality(
            research,
            "home"
        )
    )

    away = (
        team_quality(
            research,
            "away"
        )
    )

    weak_sides = []

    if (
        home[
            "matches"
        ]
        <
        MIN_TEAM_MATCHES
        or
        home[
            "trusted_ratio"
        ]
        <
        MIN_TRUSTED_RATIO
    ):
        weak_sides.append(
            "home"
        )

    if (
        away[
            "matches"
        ]
        <
        MIN_TEAM_MATCHES
        or
        away[
            "trusted_ratio"
        ]
        <
        MIN_TRUSTED_RATIO
    ):
        weak_sides.append(
            "away"
        )

    return {
        "home":
            home,

        "away":
            away,

        "weak_sides":
            weak_sides,
    }


# =========================================================
# TARGET QUALITY DETECTOR
# =========================================================

def detect_below_target_sides(
    research
):
    home = (
        team_quality(
            research,
            "home"
        )
    )

    away = (
        team_quality(
            research,
            "away"
        )
    )

    below_target = []

    if (
        home[
            "matches"
        ]
        <
        TARGET_MATCHES
        or
        home[
            "trusted_ratio"
        ]
        <
        TARGET_TRUSTED_RATIO
    ):
        below_target.append(
            "home"
        )

    if (
        away[
            "matches"
        ]
        <
        TARGET_MATCHES
        or
        away[
            "trusted_ratio"
        ]
        <
        TARGET_TRUSTED_RATIO
    ):
        below_target.append(
            "away"
        )

    return {
        "home":
            home,

        "away":
            away,

        "below_target_sides":
            below_target,
    }


# =========================================================
# MATCH IDENTITY
# =========================================================

def match_key(
    match
):
    return (
        str(
            match.get(
                "date",
                ""
            )
        ),

        normalize_text(
            match.get(
                "opponent"
            )
        ),
    )


# =========================================================
# SOURCE QUALITY
# =========================================================

def get_source_tier(
    match
):
    url = str(
        match.get(
            "source_url",
            ""
        )
    )

    domain = (
        source_domain(
            url
        )
    )

    if domain in PRIMARY_DOMAINS:
        return 4

    if domain in STRONG_DOMAINS:
        return 3

    if is_good_source(
        url
    ):
        return 2

    if match.get(
        "trusted_source"
    ) is True:
        return 2

    return 0


def evidence_priority(
    match
):
    trusted = (
        1
        if match.get(
            "trusted_source"
        ) is True
        else 0
    )

    source_tier = (
        get_source_tier(
            match
        )
    )

    date_score = (
        parse_match_date(
            match.get(
                "date"
            )
        )
    )

    return (
        trusted,
        source_tier,
        date_score,
    )


# =========================================================
# MATCH RECORD COMPLETENESS
# =========================================================

def match_completeness_score(
    match
):
    fields = [
        "date",
        "opponent",
        "venue",
        "goals_for",
        "goals_against",
        "result",
        "competition",
        "source_url",
    ]

    score = 0

    for field in fields:

        value = match.get(
            field
        )

        if value is not None:

            if isinstance(
                value,
                str
            ):

                if value.strip():
                    score += 1

            else:
                score += 1

    return score


# =========================================================
# WHICH DUPLICATE IS BETTER?
# =========================================================

def choose_better_match(
    old_match,
    new_match
):
    old_priority = (
        evidence_priority(
            old_match
        )
    )

    new_priority = (
        evidence_priority(
            new_match
        )
    )

    if (
        new_priority
        >
        old_priority
    ):
        return copy.deepcopy(
            new_match
        )

    if (
        new_priority
        <
        old_priority
    ):
        return copy.deepcopy(
            old_match
        )

    old_complete = (
        match_completeness_score(
            old_match
        )
    )

    new_complete = (
        match_completeness_score(
            new_match
        )
    )

    if (
        new_complete
        >
        old_complete
    ):
        return copy.deepcopy(
            new_match
        )

    return copy.deepcopy(
        old_match
    )


# =========================================================
# TRUSTED-FIRST FINAL SELECTION
# =========================================================

def select_best_matches(
    matches,
    limit=MAX_MERGED_MATCHES
):
    if not matches:
        return []

    unique = {}

    for match in matches:

        key = (
            match_key(
                match
            )
        )

        if key not in unique:

            unique[key] = (
                copy.deepcopy(
                    match
                )
            )

        else:

            unique[key] = (
                choose_better_match(
                    unique[
                        key
                    ],
                    match
                )
            )

    all_matches = list(
        unique.values()
    )

    trusted = [
        match
        for match in all_matches
        if match.get(
            "trusted_source"
        ) is True
    ]

    untrusted = [
        match
        for match in all_matches
        if match.get(
            "trusted_source"
        ) is not True
    ]

    trusted.sort(
        key=lambda item:
            parse_match_date(
                item.get(
                    "date"
                )
            ),
        reverse=True
    )

    untrusted.sort(
        key=lambda item:
            parse_match_date(
                item.get(
                    "date"
                )
            ),
        reverse=True
    )

    # =====================================================
    # CRITICAL V11.3 CHANGE
    #
    # Old V11.2:
    # Sort everything by date, then take first 8.
    #
    # Problem:
    # Older but verified FIFA/UEFA evidence could be
    # removed by newer weak/Wikipedia records.
    #
    # New:
    # Keep trusted evidence first.
    # Fill remaining slots with newest untrusted data.
    # =====================================================

    selected = []

    for match in trusted:

        if (
            len(selected)
            >=
            limit
        ):
            break

        selected.append(
            match
        )

    for match in untrusted:

        if (
            len(selected)
            >=
            limit
        ):
            break

        selected.append(
            match
        )

    # Final display / model order remains chronological.
    selected.sort(
        key=lambda item:
            parse_match_date(
                item.get(
                    "date"
                )
            ),
        reverse=True
    )

    return selected


# =========================================================
# MERGE MATCH RECORDS
# =========================================================

def merge_match_records(
    old_matches,
    new_matches,
    limit=MAX_MERGED_MATCHES
):
    pool = {}

    # ---------------------------------------------
    # Existing cache
    # ---------------------------------------------

    for match in (
        old_matches
        or []
    ):

        key = (
            match_key(
                match
            )
        )

        pool[
            key
        ] = copy.deepcopy(
            match
        )

    # ---------------------------------------------
    # Fresh evidence
    # ---------------------------------------------

    for match in (
        new_matches
        or []
    ):

        key = (
            match_key(
                match
            )
        )

        existing = (
            pool.get(
                key
            )
        )

        if existing is None:

            pool[
                key
            ] = copy.deepcopy(
                match
            )

        else:

            chosen = (
                choose_better_match(
                    existing,
                    match
                )
            )

            old_trusted = bool(
                existing.get(
                    "trusted_source"
                )
            )

            new_trusted = bool(
                match.get(
                    "trusted_source"
                )
            )

            chosen_trusted = bool(
                chosen.get(
                    "trusted_source"
                )
            )

            if (
                new_trusted
                and
                not old_trusted
                and
                chosen_trusted
            ):

                print(
                    "♻️ Replaced weak evidence:"
                )

                print(
                    f"   {match.get('date')} "
                    f"vs {match.get('opponent')}"
                )

                print(
                    f"   "
                    f"{existing.get('source_domain', 'unknown')}"
                    f" → "
                    f"{match.get('source_domain', 'trusted')}"
                )

            pool[
                key
            ] = chosen

    return (
        select_best_matches(
            list(
                pool.values()
            ),
            limit=limit
        )
    )


# =========================================================
# NORMALIZE RESEARCH RECORDS
# =========================================================

def normalize_targeted_matches(
    records
):
    cleaned = (
        clean_match_records(
            records
        )
    )

    output = []

    for match in cleaned:

        item = (
            copy.deepcopy(
                match
            )
        )

        url = str(
            item.get(
                "source_url",
                ""
            )
        )

        domain = (
            source_domain(
                url
            )
        )

        item[
            "source_domain"
        ] = domain

        item[
            "trusted_source"
        ] = bool(
            is_good_source(
                url
            )
        )

        output.append(
            item
        )

    return output


# =========================================================
# ROUND 1
# NORMAL RECOVERY
# =========================================================

def normal_recovery_search(
    team,
    competition,
    match_date
):
    print(
        f"🔎 Normal recovery search: "
        f"{team}"
    )

    try:

        result = (
            research_recent_matches(
                team,
                competition,
                match_date
            )
            or {}
        )

    except Exception as error:

        print(
            f"⚠️ Normal recovery failed: "
            f"{error}"
        )

        return []

    matches = (
        normalize_targeted_matches(
            result.get(
                "matches",
                []
            )
        )
    )

    print(
        f"📚 Normal records found: "
        f"{len(matches)}"
    )

    return matches


# =========================================================
# ROUND 2
# TARGETED TRUSTED RECOVERY
# =========================================================

def targeted_trusted_search(
    team,
    competition,
    match_date
):
    print(
        f"🎯 Trusted-source recovery: "
        f"{team}"
    )

    prompt = f"""
You are performing strict football DATA VERIFICATION.

Team:
{team}

Competition context:
{competition}

Target match date:
{match_date}

Find up to {MAX_TARGETED_RESULTS} of the most recent
COMPLETED matches for {team} before the target date.

IMPORTANT:

This is not betting advice.

Do not predict anything.

Do not invent:

- opponents
- dates
- scores
- competitions
- venues
- source URLs

SOURCE PRIORITY:

Use these sources whenever possible:

1. FIFA / inside.fifa.com
2. UEFA
3. ESPN
4. BBC Sport
5. Sky Sports
6. FotMob
7. Soccerway
8. WorldFootball
9. Reuters

Avoid Wikipedia if a stronger source exists.

Do not use:

- betting sites
- prediction sites
- tipster sites
- blogs
- forums
- social media posts

CRITICAL REPLACEMENT TASK:

Existing weak records may already exist.

Try to find strong-source verification for the
same historical matches so weak evidence can be replaced.

Return only completed matches whose opponent and score
are supported by the supplied source URL.

For every match return:

- date: YYYY-MM-DD
- opponent
- venue:
  home / away / neutral / unknown
- goals_for
- goals_against
- result:
  W / D / L
- competition
- source_url

JSON only.

Return exactly:

{{
  "matches": [
    {{
      "date": "YYYY-MM-DD",
      "opponent": "Opponent",
      "venue": "away",
      "goals_for": 0,
      "goals_against": 0,
      "result": "W",
      "competition": "Competition",
      "source_url": "https://..."
    }}
  ]
}}
"""

    try:

        result = (
            call_research(
                prompt
            )
            or {}
        )

    except Exception as error:

        print(
            f"⚠️ Trusted recovery failed: "
            f"{error}"
        )

        return []

    matches = (
        normalize_targeted_matches(
            result.get(
                "matches",
                []
            )
        )
    )

    trusted_only = [
        item
        for item in matches
        if item.get(
            "trusted_source"
        ) is True
    ]

    print(
        f"✅ Trusted records found: "
        f"{len(trusted_only)}"
    )

    return trusted_only


# =========================================================
# TEAM NEWS RECOVERY
# =========================================================

def recover_team_news(
    home_team,
    away_team,
    match_date
):
    print(
        "🩹 Recovering team availability..."
    )

    try:

        return (
            research_team_news(
                home_team,
                away_team,
                match_date
            )
            or {}
        )

    except Exception as error:

        print(
            f"⚠️ Team-news recovery failed: "
            f"{error}"
        )

        return {}


# =========================================================
# CONTEXT RECOVERY
# =========================================================

def recover_context(
    home_team,
    away_team,
    competition,
    match_date
):
    print(
        "🏆 Recovering match context..."
    )

    try:

        return (
            research_match_context(
                home_team,
                away_team,
                competition,
                match_date
            )
            or {}
        )

    except Exception as error:

        print(
            f"⚠️ Context recovery failed: "
            f"{error}"
        )

        return {}


# =========================================================
# REBUILD FORM + QUALITY + VERIFY
# =========================================================

def rebuild_and_verify(
    candidate
):
    home_matches = (
        candidate.get(
            "home_recent_matches",
            []
        )
        or []
    )

    away_matches = (
        candidate.get(
            "away_recent_matches",
            []
        )
        or []
    )

    # Ensure trusted-first selection before verification.

    candidate[
        "home_recent_matches"
    ] = select_best_matches(
        home_matches,
        limit=MAX_MERGED_MATCHES
    )

    candidate[
        "away_recent_matches"
    ] = select_best_matches(
        away_matches,
        limit=MAX_MERGED_MATCHES
    )

    home_matches = (
        candidate[
            "home_recent_matches"
        ]
    )

    away_matches = (
        candidate[
            "away_recent_matches"
        ]
    )

    # ---------------------------------------------
    # Form
    # ---------------------------------------------

    candidate[
        "calculated_form"
    ] = {

        "home":
            calculate_form(
                home_matches
            ),

        "away":
            calculate_form(
                away_matches
            ),
    }

    # ---------------------------------------------
    # Team news
    # ---------------------------------------------

    team_news_payload = {

        "injuries":
            candidate.get(
                "injuries",
                {}
            ),

        "suspensions":
            candidate.get(
                "suspensions",
                {}
            ),

        "lineups":
            candidate.get(
                "lineups",
                {}
            ),

        "key_players":
            candidate.get(
                "key_players",
                {}
            ),
    }

    # ---------------------------------------------
    # Context
    # ---------------------------------------------

    context_payload = {

        "league_context":
            candidate.get(
                "league_context"
            ),

        "match_importance":
            candidate.get(
                "match_importance"
            ),

        "rest_and_schedule":
            candidate.get(
                "rest_and_schedule",
                {}
            ),

        "head_to_head_matches":
            candidate.get(
                "head_to_head_matches",
                []
            ),
    }

    # ---------------------------------------------
    # Research quality
    # ---------------------------------------------

    candidate[
        "research_quality"
    ] = (
        calculate_research_quality(
            home_matches,
            away_matches,
            team_news_payload,
            context_payload,
        )
    )

    # ---------------------------------------------
    # Full verification
    # ---------------------------------------------

    verified = (
        verify_research(
            candidate
        )
    )

    # Verification may modify records.
    # Reapply trusted-first selection.

    verified[
        "home_recent_matches"
    ] = select_best_matches(
        verified.get(
            "home_recent_matches",
            []
        ),
        limit=MAX_MERGED_MATCHES
    )

    verified[
        "away_recent_matches"
    ] = select_best_matches(
        verified.get(
            "away_recent_matches",
            []
        ),
        limit=MAX_MERGED_MATCHES
    )

    verified[
        "calculated_form"
    ] = {

        "home":
            calculate_form(
                verified[
                    "home_recent_matches"
                ]
            ),

        "away":
            calculate_form(
                verified[
                    "away_recent_matches"
                ]
            ),
    }

    return verified


# =========================================================
# COMBINED QUALITY
# =========================================================

def combined_quality(
    research
):
    status = (
        detect_weak_sides(
            research
        )
    )

    return (
        status[
            "home"
        ][
            "quality_score"
        ]
        +
        status[
            "away"
        ][
            "quality_score"
        ]
    ) / 2.0


# =========================================================
# TOTAL TRUSTED COUNT
# =========================================================

def total_trusted_matches(
    research
):
    home = (
        team_quality(
            research,
            "home"
        )
    )

    away = (
        team_quality(
            research,
            "away"
        )
    )

    return (
        home[
            "trusted_matches"
        ]
        +
        away[
            "trusted_matches"
        ]
    )


# =========================================================
# ONE RECOVERY ROUND
# =========================================================

def recovery_round(
    research,
    round_number
):
    candidate = (
        copy.deepcopy(
            research
        )
    )

    # =====================================================
    # CHOOSE TARGET SIDES
    # =====================================================

    if round_number == 1:

        minimum_status = (
            detect_weak_sides(
                candidate
            )
        )

        target_sides = (
            minimum_status[
                "weak_sides"
            ]
        )

    else:

        target_status = (
            detect_below_target_sides(
                candidate
            )
        )

        target_sides = (
            target_status[
                "below_target_sides"
            ]
        )

    home_team = (
        candidate.get(
            "home_team"
        )
    )

    away_team = (
        candidate.get(
            "away_team"
        )
    )

    competition = (
        candidate.get(
            "competition"
        )
    )

    match_date = (
        candidate.get(
            "match_date"
        )
    )

    print()
    print(
        f"🔄 RECOVERY ROUND "
        f"{round_number}"
    )

    print(
        f"Target sides: "
        f"{target_sides}"
    )

    if not target_sides:
        return candidate

    # =====================================================
    # RECOVER MATCHES
    # =====================================================

    for side in target_sides:

        if side == "home":

            team = (
                home_team
            )

            key = (
                "home_recent_matches"
            )

        else:

            team = (
                away_team
            )

            key = (
                "away_recent_matches"
            )

        old_matches = (
            candidate.get(
                key,
                []
            )
            or []
        )

        if round_number == 1:

            fresh_matches = (
                normal_recovery_search(
                    team,
                    competition,
                    match_date
                )
            )

        else:

            fresh_matches = (
                targeted_trusted_search(
                    team,
                    competition,
                    match_date
                )
            )

        candidate[
            key
        ] = (
            merge_match_records(
                old_matches,
                fresh_matches,
                limit=MAX_MERGED_MATCHES
            )
        )

        current_quality = (
            trusted_ratio(
                candidate[
                    key
                ]
            )
        )

        trusted_count = sum(
            1
            for item in candidate[
                key
            ]
            if item.get(
                "trusted_source"
            ) is True
        )

        print(
            f"📊 {team} merged evidence:"
        )

        print(
            f"   Matches: "
            f"{len(candidate[key])}"
        )

        print(
            f"   Trusted: "
            f"{trusted_count}"
        )

        print(
            f"   Trusted Ratio: "
            f"{current_quality * 100:.1f}%"
        )

    # =====================================================
    # OPTIONAL RECOVERY
    # =====================================================

    raw_errors = (
        candidate.get(
            "raw_research_errors",
            {}
        )
        or {}
    )

    if (
        round_number == 1
        and raw_errors.get(
            "team_news"
        )
    ):

        news = (
            recover_team_news(
                home_team,
                away_team,
                match_date
            )
        )

        for key in (
            "injuries",
            "suspensions",
            "lineups",
            "key_players",
        ):

            if key in news:

                candidate[
                    key
                ] = news[
                    key
                ]

        if news:

            raw_errors[
                "team_news"
            ] = None

    if (
        round_number == 1
        and raw_errors.get(
            "context"
        )
    ):

        context = (
            recover_context(
                home_team,
                away_team,
                competition,
                match_date
            )
        )

        for key in (
            "league_context",
            "match_importance",
            "rest_and_schedule",
            "head_to_head_matches",
        ):

            if key in context:

                candidate[
                    key
                ] = context[
                    key
                ]

        if context:

            raw_errors[
                "context"
            ] = None

    candidate[
        "raw_research_errors"
    ] = raw_errors

    print(
        "🛡 Re-verifying recovery round..."
    )

    return (
        rebuild_and_verify(
            candidate
        )
    )


# =========================================================
# MAIN AUTO RECOVERY
# =========================================================

def recover_evidence(
    research,
    force=False
):
    if not research:

        raise ValueError(
            "research is required"
        )

    original = (
        copy.deepcopy(
            research
        )
    )

    current = (
        copy.deepcopy(
            research
        )
    )

    home_team = (
        current.get(
            "home_team"
        )
    )

    away_team = (
        current.get(
            "away_team"
        )
    )

    competition = (
        current.get(
            "competition"
        )
    )

    match_date = (
        current.get(
            "match_date"
        )
    )

    # =====================================================
    # BEFORE STATE
    # =====================================================

    before = (
        detect_weak_sides(
            original
        )
    )

    before_target = (
        detect_below_target_sides(
            original
        )
    )

    before_score = (
        combined_quality(
            original
        )
    )

    before_trusted = (
        total_trusted_matches(
            original
        )
    )

    print()
    print(
        "━━━━━━━━━━━━━━━━━━"
    )

    print(
        "👑 BETTING BAYIN V11.3"
    )

    print(
        "♻️ EVIDENCE REPLACEMENT RECOVERY"
    )

    print(
        "━━━━━━━━━━━━━━━━━━"
    )

    print()

    print(
        f"🏠 BEFORE Home: "
        f"{before['home']}"
    )

    print(
        f"✈️ BEFORE Away: "
        f"{before['away']}"
    )

    print(
        f"🎯 Below target: "
        f"{before_target['below_target_sides']}"
    )

    # =====================================================
    # ALREADY GOOD
    # =====================================================

    if (
        not before_target[
            "below_target_sides"
        ]
        and
        not force
    ):

        print()
        print(
            "✅ Evidence already meets "
            "target quality."
        )

        return {

            "recovered":
                False,

            "improved":
                False,

            "research":
                original,

            "before":
                before,

            "before_target":
                before_target,

            "after":
                before,

            "after_target":
                before_target,

            "rounds":
                0,

            "still_weak":
                False,

            "below_target":
                False,

            "reason":
                (
                    "Evidence already meets "
                    "target thresholds."
                ),
        }

    # =====================================================
    # RECOVERY LOOP
    # =====================================================

    rounds_completed = 0

    for round_number in range(
        1,
        MAX_RECOVERY_ROUNDS + 1
    ):

        rounds_completed = (
            round_number
        )

        current = (
            recovery_round(
                current,
                round_number
            )
        )

        minimum_status = (
            detect_weak_sides(
                current
            )
        )

        target_status = (
            detect_below_target_sides(
                current
            )
        )

        print()

        print(
            f"🏠 Round {round_number} Home: "
            f"{minimum_status['home']}"
        )

        print(
            f"✈️ Round {round_number} Away: "
            f"{minimum_status['away']}"
        )

        print(
            f"🎯 Below target: "
            f"{target_status['below_target_sides']}"
        )

        if not target_status[
            "below_target_sides"
        ]:

            print(
                "✅ Target evidence quality reached."
            )

            break

        if (
            round_number
            <
            MAX_RECOVERY_ROUNDS
        ):

            print(
                "🎯 Target quality not reached."
            )

            print(
                "🔄 Continuing to trusted-source "
                "replacement recovery..."
            )

    # =====================================================
    # AFTER STATE
    # =====================================================

    after = (
        detect_weak_sides(
            current
        )
    )

    after_target = (
        detect_below_target_sides(
            current
        )
    )

    after_score = (
        combined_quality(
            current
        )
    )

    after_trusted = (
        total_trusted_matches(
            current
        )
    )

    improvement = (
        after_score
        -
        before_score
    )

    trusted_gain = (
        after_trusted
        -
        before_trusted
    )

    # =====================================================
    # ACCEPTANCE RULE
    # =====================================================
    #
    # Accept if:
    #
    # 1. Quality score improves >= 0.03
    #
    # OR
    #
    # 2. Trusted evidence count increases
    #    and quality does not regress.
    #
    # OR
    #
    # 3. Target quality is achieved from a
    #    previously below-target state.
    #
    # =====================================================

    target_reached = (
        bool(
            before_target[
                "below_target_sides"
            ]
        )
        and
        not bool(
            after_target[
                "below_target_sides"
            ]
        )
    )

    improved = (
        improvement
        >=
        MIN_IMPROVEMENT
        or
        (
            trusted_gain > 0
            and
            after_score
            >=
            before_score
        )
        or
        target_reached
    )

    print()

    print(
        f"📊 Evidence quality: "
        f"{before_score:.3f} "
        f"→ {after_score:.3f}"
    )

    print(
        f"📈 Quality improvement: "
        f"{improvement:+.3f}"
    )

    print(
        f"🛡 Trusted evidence: "
        f"{before_trusted} "
        f"→ {after_trusted}"
    )

    print(
        f"📈 Trusted gain: "
        f"{trusted_gain:+d}"
    )

    print(
        f"🛡 Minimum weak sides: "
        f"{after['weak_sides']}"
    )

    print(
        f"🎯 Still below target: "
        f"{after_target['below_target_sides']}"
    )

    # =====================================================
    # CACHE
    # =====================================================

    if improved:

        save_research_cache(
            home_team=
                home_team,

            away_team=
                away_team,

            competition=
                competition,

            match_date=
                match_date,

            payload=
                current,
        )

        final_research = (
            current
        )

        print(
            "💾 Improved verified evidence saved."
        )

    else:

        final_research = (
            original
        )

        print(
            "🛡 No verified evidence improvement."
        )

        print(
            "💾 Previous verified cache preserved."
        )

    # =====================================================
    # RETURN
    # =====================================================

    return {

        "recovered":
            True,

        "improved":
            improved,

        "improvement":
            round(
                improvement,
                3
            ),

        "trusted_gain":
            trusted_gain,

        "rounds":
            rounds_completed,

        "research":
            final_research,

        "before":
            before,

        "before_target":
            before_target,

        "after":
            after,

        "after_target":
            after_target,

        "still_weak":
            bool(
                after[
                    "weak_sides"
                ]
            ),

        "below_target":
            bool(
                after_target[
                    "below_target_sides"
                ]
            ),

        "target_reached":
            target_reached,

        "reason":
            (
                "Evidence improved."
                if improved
                else
                "Recovery did not improve "
                "verified evidence."
            ),
    }