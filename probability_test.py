import json

from data_engine import (
    get_research_cache,
)

from strength_engine import (
    calculate_match_strength,
)

from probability_engine import (
    calculate_match_probabilities,
    format_probability_report,
)


# =========================================================
# BETTING BAYIN
# PROBABILITY ENGINE V1 TEST
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
    "👑 BETTING BAYIN V9"
)

print(
    "🎲 Independent Probability Test"
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

print()
print(
    "🧠 Running Independent "
    "Strength Model V3..."
)

strength = (
    calculate_match_strength(
        research
    )
)

print(
    "✅ Strength model completed."
)


# =========================================================
# PROBABILITY MODEL V1
# =========================================================

print()
print(
    "🎲 Running Independent "
    "Probability Model V1..."
)

probability = (
    calculate_match_probabilities(
        strength
    )
)

print(
    "✅ Probability model completed."
)


# =========================================================
# REPORT
# =========================================================

print()

print(
    format_probability_report(
        probability
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
    "🔧 PROBABILITY V1 DEBUG"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

print(
    json.dumps(
        probability,
        indent=2,
        ensure_ascii=False,
        default=str
    )
)


print()
print(
    "✅ BETTING BAYIN V9 "
    "TEST COMPLETE"
)