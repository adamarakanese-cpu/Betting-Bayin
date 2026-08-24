import json

from elo_history_engine import (
    get_historical_ratings,
)


TESTS = [
    {
        "team": "Spain",
        "date": "2026-07-02"
    },
    {
        "team": "Argentina",
        "date": "2026-06-22"
    },
    {
        "team": "Algeria",
        "date": "2026-06-27"
    },
    {
        "team": "Jordan",
        "date": "2026-06-17"
    },
    {
        "team": "Tunisia",
        "date": "2026-06-01"
    },
    {
        "team": "Albania",
        "date": "2026-06-03"
    },
    {
        "team": "Georgia",
        "date": "2026-03-26"
    },
    {
        "team": "Norway",
        "date": "2025-10-11"
    },
    {
        "team": "Italy",
        "date": "2025-09-08"
    },
    {
        "team": "Moldova",
        "date": "2025-09-05"
    },
]


print()
print(
    "👑 BETTING BAYIN"
)

print(
    "🕰 HISTORICAL ELO TEST"
)

print()

results = (
    get_historical_ratings(
        TESTS
    )
)


for result in results:

    team = result.get(
        "team"
    )

    elo = result.get(
        "elo"
    )

    requested = result.get(
        "requested_date"
    )

    rating_date = result.get(
        "rating_date"
    )

    error = result.get(
        "error"
    )

    if error:

        print(
            f"❌ {team}: "
            f"{error}"
        )

    else:

        print(
            f"✅ {team:10} "
            f"Elo {elo} "
            f"| Match {requested} "
            f"| Rating from "
            f"{rating_date}"
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
        results,
        indent=2,
        ensure_ascii=False
    )
)

print()
print(
    "✅ HISTORICAL ELO TEST COMPLETE"
)