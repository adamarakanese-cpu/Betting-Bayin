from copy import deepcopy
from datetime import datetime


# =========================================================
# BETTING BAYIN
# SOURCE + DATA VERIFICATION ENGINE V1
# =========================================================


MAX_RECENT_MATCH_AGE_DAYS = 450


# =========================================================
# DATE HELPERS
# =========================================================

def parse_target_date(value):
    if not value:
        return None

    formats = [
        "%d.%m.%Y",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(
                value,
                fmt
            )
        except ValueError:
            continue

    return None


def parse_event_date(value):
    if not value:
        return None

    formats = [
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(
                value,
                fmt
            )
        except ValueError:
            continue

    return None


# =========================================================
# RESULT CONSISTENCY
# =========================================================

def expected_result(
    goals_for,
    goals_against
):
    try:
        gf = int(goals_for)
        ga = int(goals_against)
    except (
        TypeError,
        ValueError
    ):
        return None

    if gf > ga:
        return "W"

    if gf == ga:
        return "D"

    return "L"


# =========================================================
# SINGLE MATCH VERIFICATION
# =========================================================

def verify_match_record(
    match,
    target_date
):
    reasons = []

    if not isinstance(
        match,
        dict
    ):
        return False, [
            "Invalid match object."
        ]

    opponent = match.get(
        "opponent"
    )

    if not opponent:
        reasons.append(
            "Opponent missing."
        )

    source_url = match.get(
        "source_url"
    )

    if not source_url:
        reasons.append(
            "Source URL missing."
        )

    match_date = parse_event_date(
        match.get("date")
    )

    if match_date is None:
        reasons.append(
            "Match date invalid."
        )

    if (
        target_date is not None
        and match_date is not None
    ):
        if match_date >= target_date:
            reasons.append(
                "Match occurred on or after "
                "target fixture date."
            )

        age_days = (
            target_date
            - match_date
        ).days

        if age_days > (
            MAX_RECENT_MATCH_AGE_DAYS
        ):
            reasons.append(
                "Match is too old for "
                "recent-form analysis."
            )

    stated_result = str(
        match.get(
            "result",
            ""
        )
    ).upper()

    calculated_result = (
        expected_result(
            match.get(
                "goals_for"
            ),
            match.get(
                "goals_against"
            )
        )
    )

    if stated_result not in {
        "W",
        "D",
        "L"
    }:
        reasons.append(
            "Invalid W/D/L result."
        )

    if (
        calculated_result is not None
        and stated_result
        != calculated_result
    ):
        reasons.append(
            "Score and W/D/L result "
            "do not match."
        )

    verified = (
        len(reasons) == 0
    )

    return (
        verified,
        reasons
    )


# =========================================================
# MATCH COLLECTION VERIFICATION
# =========================================================

def verify_matches(
    matches,
    target_date
):
    verified = []
    rejected = []

    if not isinstance(
        matches,
        list
    ):
        matches = []

    seen = set()

    for match in matches:
        is_valid, reasons = (
            verify_match_record(
                match,
                target_date
            )
        )

        key = (
            str(
                match.get("date")
            ),
            str(
                match.get("opponent")
            ),
            str(
                match.get(
                    "goals_for"
                )
            ),
            str(
                match.get(
                    "goals_against"
                )
            )
        )

        if key in seen:
            is_valid = False

            reasons.append(
                "Duplicate match."
            )

        seen.add(key)

        if is_valid:
            verified.append(
                deepcopy(match)
            )
        else:
            rejected.append({
                "match": deepcopy(
                    match
                ),
                "reasons": reasons
            })

    return (
        verified,
        rejected
    )


# =========================================================
# SOURCE / PLAYER EVIDENCE
# =========================================================

def verify_player_evidence(
    items,
    expected_team
):
    """
    Very conservative.

    Player availability data is only accepted
    when research explicitly provides:

    player
    status
    source_url
    player_team

    and player_team matches expected_team.

    If player_team is missing, the claim is NOT
    allowed into the final statistical model.
    """

    verified = []
    rejected = []

    if not isinstance(
        items,
        list
    ):
        items = []

    for item in items:

        if not isinstance(
            item,
            dict
        ):
            continue

        reasons = []

        player = item.get(
            "player"
        )

        status = item.get(
            "status"
        )

        source_url = item.get(
            "source_url"
        )

        player_team = item.get(
            "player_team"
        )

        if not player:
            reasons.append(
                "Player name missing."
            )

        if not status:
            reasons.append(
                "Status missing."
            )

        if not source_url:
            reasons.append(
                "Evidence source missing."
            )

        if not player_team:
            reasons.append(
                "Player-team affiliation "
                "not independently supplied."
            )

        elif (
            str(player_team)
            .strip()
            .lower()
            !=
            str(expected_team)
            .strip()
            .lower()
        ):
            reasons.append(
                "Player-team affiliation "
                "does not match fixture team."
            )

        if reasons:
            rejected.append({
                "item": deepcopy(item),
                "reasons": reasons
            })
        else:
            verified.append(
                deepcopy(item)
            )

    return (
        verified,
        rejected
    )


# =========================================================
# FORM CALCULATOR
# =========================================================

def calculate_verified_form(
    matches
):
    wins = 0
    draws = 0
    losses = 0

    goals_for = 0
    goals_against = 0

    goal_samples = 0

    home_samples = 0
    away_samples = 0

    for match in matches:

        result = match.get(
            "result"
        )

        if result == "W":
            wins += 1

        elif result == "D":
            draws += 1

        elif result == "L":
            losses += 1

        venue = match.get(
            "venue"
        )

        if venue == "home":
            home_samples += 1

        elif venue == "away":
            away_samples += 1

        try:
            gf = int(
                match.get(
                    "goals_for"
                )
            )

            ga = int(
                match.get(
                    "goals_against"
                )
            )

            goals_for += gf
            goals_against += ga

            goal_samples += 1

        except (
            TypeError,
            ValueError
        ):
            pass

    total = (
        wins
        + draws
        + losses
    )

    if total == 0:
        return {
            "matches": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "points_per_match": None,
            "avg_goals_for": None,
            "avg_goals_against": None,
            "home_samples": 0,
            "away_samples": 0
        }

    points = (
        wins * 3
        + draws
    )

    ppm = (
        points / total
    )

    avg_gf = (
        goals_for
        / goal_samples
        if goal_samples
        else None
    )

    avg_ga = (
        goals_against
        / goal_samples
        if goal_samples
        else None
    )

    return {
        "matches": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,

        "points_per_match": round(
            ppm,
            2
        ),

        "avg_goals_for": (
            round(
                avg_gf,
                2
            )
            if avg_gf is not None
            else None
        ),

        "avg_goals_against": (
            round(
                avg_ga,
                2
            )
            if avg_ga is not None
            else None
        ),

        "home_samples": (
            home_samples
        ),

        "away_samples": (
            away_samples
        )
    }


# =========================================================
# PYTHON VERIFICATION QUALITY
# =========================================================

def calculate_verification_quality(
    home_matches,
    away_matches,
    rejected_home,
    rejected_away
):
    score = 0.0

    if len(
        home_matches
    ) >= 5:
        score += 0.35

    elif len(
        home_matches
    ) >= 3:
        score += 0.22

    elif len(
        home_matches
    ) >= 1:
        score += 0.10

    if len(
        away_matches
    ) >= 5:
        score += 0.35

    elif len(
        away_matches
    ) >= 3:
        score += 0.22

    elif len(
        away_matches
    ) >= 1:
        score += 0.10

    all_verified = (
        home_matches
        + away_matches
    )

    if all_verified:

        trusted = sum(
            1
            for item in all_verified
            if item.get(
                "trusted_source"
            )
        )

        trusted_ratio = (
            trusted
            / len(all_verified)
        )

        score += (
            trusted_ratio
            * 0.30
        )

    else:
        trusted_ratio = 0.0

    total_rejected = (
        len(rejected_home)
        + len(rejected_away)
    )

    score = max(
        0.0,
        min(
            1.0,
            score
        )
    )

    return {
        "score": round(
            score,
            2
        ),
        "trusted_source_ratio": (
            round(
                trusted_ratio,
                2
            )
        ),
        "rejected_match_count": (
            total_rejected
        )
    }


# =========================================================
# MAIN VERIFIER
# =========================================================

def verify_research(
    research
):
    verified = deepcopy(
        research
    )

    target_date = (
        parse_target_date(
            research.get(
                "match_date"
            )
        )
    )

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

    (
        verified_home_matches,
        rejected_home_matches
    ) = verify_matches(
        research.get(
            "home_recent_matches",
            []
        ),
        target_date
    )

    (
        verified_away_matches,
        rejected_away_matches
    ) = verify_matches(
        research.get(
            "away_recent_matches",
            []
        ),
        target_date
    )

    injuries = research.get(
        "injuries",
        {}
    )

    suspensions = research.get(
        "suspensions",
        {}
    )

    (
        verified_home_injuries,
        rejected_home_injuries
    ) = verify_player_evidence(
        injuries.get(
            "home",
            []
        ),
        home_team
    )

    (
        verified_away_injuries,
        rejected_away_injuries
    ) = verify_player_evidence(
        injuries.get(
            "away",
            []
        ),
        away_team
    )

    (
        verified_home_suspensions,
        rejected_home_suspensions
    ) = verify_player_evidence(
        suspensions.get(
            "home",
            []
        ),
        home_team
    )

    (
        verified_away_suspensions,
        rejected_away_suspensions
    ) = verify_player_evidence(
        suspensions.get(
            "away",
            []
        ),
        away_team
    )

    verified[
        "home_recent_matches"
    ] = verified_home_matches

    verified[
        "away_recent_matches"
    ] = verified_away_matches

    verified[
        "calculated_form"
    ] = {
        "home": (
            calculate_verified_form(
                verified_home_matches
            )
        ),
        "away": (
            calculate_verified_form(
                verified_away_matches
            )
        )
    }

    verified[
        "injuries"
    ] = {
        "home": (
            verified_home_injuries
        ),
        "away": (
            verified_away_injuries
        )
    }

    verified[
        "suspensions"
    ] = {
        "home": (
            verified_home_suspensions
        ),
        "away": (
            verified_away_suspensions
        )
    }

    verification_quality = (
        calculate_verification_quality(
            verified_home_matches,
            verified_away_matches,
            rejected_home_matches,
            rejected_away_matches
        )
    )

    verified[
        "verification_quality"
    ] = verification_quality

    verified[
        "verification_report"
    ] = {

        "rejected_home_matches": (
            rejected_home_matches
        ),

        "rejected_away_matches": (
            rejected_away_matches
        ),

        "rejected_player_evidence": {

            "home_injuries": (
                rejected_home_injuries
            ),

            "away_injuries": (
                rejected_away_injuries
            ),

            "home_suspensions": (
                rejected_home_suspensions
            ),

            "away_suspensions": (
                rejected_away_suspensions
            )
        }
    }

    # Evidence engine should use the stricter score.
    verified[
        "research_quality"
    ] = {
        "score": (
            verification_quality[
                "score"
            ]
        ),
        "notes": [
            "Calculated by Betting Bayin "
            "Python verification engine."
        ]
    }

    return verified