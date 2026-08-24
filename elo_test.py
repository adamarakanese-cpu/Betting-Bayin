import json

from elo_engine import (
    get_team_ratings,
)


TEAMS = [
    "Austria",
    "Israel",
    "Spain",
    "Argentina",
    "Algeria",
    "Jordan",
    "Tunisia",
    "Albania",
    "Georgia",
    "Norway",
    "Italy",
    "Moldova",
]


print()
print(
    "👑 BETTING BAYIN"
)

print(
    "🌍 WORLD FOOTBALL "
    "ELO TEST V2"
)

print()

ratings = (
    get_team_ratings(
        TEAMS,
        force_refresh=True
    )
)

for team, info in (
    ratings.items()
):

    if info:

        print(
            f"{team:12} "
            f"Rank #{info['rank']:3} "
            f"Elo {info['elo']}"
        )

    else:

        print(
            f"{team:12} "
            f"NOT FOUND"
        )


print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "🔧 FULL DEBUG"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

print(
    json.dumps(
        ratings,
        indent=2,
        ensure_ascii=False
    )
)

print()

print(
    "✅ ELO TEST V2 COMPLETE"
)