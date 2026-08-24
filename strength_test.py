import json

from data_engine import (
    get_research_cache,
)

from strength_engine import (
    calculate_match_strength,
    format_strength_report,
)


# =========================================================
# BETTING BAYIN
# STRENGTH ENGINE V3 TEST
# =========================================================

HOME = "Austria"
AWAY = "Israel"

COMPETITION = (
    "UEFA Nations League"
)

MATCH_DATE = (
    "25.09.2026"
)


print()
print(
    "👑 BETTING BAYIN V8.3"
)

print(
    "🧠 Historical Elo "
    "Strength Test"
)

print()


# =========================================================
# LOAD VERIFIED DATA
# =========================================================

research = (
    get_research_cache(
        HOME,
        AWAY,
        COMPETITION,
        MATCH_DATE
    )
)


if not research:

    raise RuntimeError(
        "Verified research cache "
        "မတွေ့ပါ။ python main.py "
        "အရင် run ပါ။"
    )


print(
    "✅ Verified research "
    "loaded from cache."
)


# =========================================================
# STRENGTH MODEL V3
# =========================================================

result = (
    calculate_match_strength(
        research
    )
)


# =========================================================
# REPORT
# =========================================================

print()
print(
    format_strength_report(
        result
    )
)


# =========================================================
# DEBUG
# =========================================================

print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "🔧 STRENGTH V3 DEBUG"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

print(
    json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
        default=str
    )
)

print()
print(
    "✅ STRENGTH ENGINE V3 "
    "TEST COMPLETE"
)