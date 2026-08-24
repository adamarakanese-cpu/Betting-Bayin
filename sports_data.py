import requests
from datetime import datetime

# =========================================================
# BETTING BAYIN
# STRUCTURED SPORTS DATA V1
# Source: TheSportsDB Free API
# =========================================================

BASE_URL = "https://www.thesportsdb.com/api/v1/json/123"

TIMEOUT = 20


def api_get(endpoint, params=None):
    url = f"{BASE_URL}/{endpoint}"

    response = requests.get(
        url,
        params=params,
        timeout=TIMEOUT
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# EVENT SEARCH
# =========================================================

def search_fixture(
    home_team,
    away_team,
    match_date=None
):
    event_name = (
        f"{home_team}_vs_{away_team}"
        .replace(" ", "_")
    )

    params = {
        "e": event_name
    }

    if match_date:
        try:
            parsed = datetime.strptime(
                match_date,
                "%d.%m.%Y"
            )

            params["d"] = parsed.strftime(
                "%Y-%m-%d"
            )

        except ValueError:
            pass

    result = api_get(
        "searchevents.php",
        params
    )

    events = (
        result.get("event")
        or []
    )

    return events


# =========================================================
# PLAYER SEARCH
# =========================================================

def search_player(player_name):
    result = api_get(
        "searchplayers.php",
        {
            "p": player_name
        }
    )

    return (
        result.get("player")
        or []
    )


# =========================================================
# TEAM SEARCH
#
# NOTE:
# Free API team string search may be limited.
# Keep this as optional/fallback only.
# =========================================================

def search_team(team_name):
    result = api_get(
        "searchteams.php",
        {
            "t": team_name
        }
    )

    return (
        result.get("teams")
        or []
    )


# =========================================================
# PREVIOUS EVENTS BY TEAM ID
# =========================================================

def previous_team_events(team_id):
    result = api_get(
        "eventslast.php",
        {
            "id": team_id
        }
    )

    return (
        result.get("results")
        or []
    )


# =========================================================
# NORMALIZE EVENT
# =========================================================

def normalize_event(event):
    return {
        "event_id": event.get("idEvent"),
        "event_name": event.get("strEvent"),
        "competition": event.get("strLeague"),
        "season": event.get("strSeason"),
        "date": event.get("dateEvent"),
        "time": event.get("strTime"),

        "home_team": event.get(
            "strHomeTeam"
        ),

        "away_team": event.get(
            "strAwayTeam"
        ),

        "home_score": event.get(
            "intHomeScore"
        ),

        "away_score": event.get(
            "intAwayScore"
        ),

        "venue": event.get(
            "strVenue"
        ),

        "status": event.get(
            "strStatus"
        ),

        "source": "TheSportsDB"
    }


# =========================================================
# TEST FUNCTION
# =========================================================

def test_match(
    home_team,
    away_team,
    match_date=None
):
    print(
        "🌍 TheSportsDB structured-data test"
    )

    print(
        f"⚽ {home_team} vs {away_team}"
    )

    print()

    try:
        events = search_fixture(
            home_team,
            away_team,
            match_date
        )

        if not events:
            print(
                "❌ Fixture not found."
            )

            return

        print(
            f"✅ Found {len(events)} event(s)"
        )

        for event in events:
            normalized = normalize_event(
                event
            )

            print()

            for key, value in (
                normalized.items()
            ):
                print(
                    f"{key}: {value}"
                )

    except Exception as error:
        print(
            "❌ SPORTS DATA ERROR:"
        )

        print(
            str(error)
        )