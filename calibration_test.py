import json

from data_engine import (
    get_research_cache,
)

from strength_engine import (
    calculate_match_strength,
)

from probability_engine import (
    calculate_match_probabilities,
)

from calibration_engine import (
    calibrate_probability_model,
    format_calibration_report,
)


HOME = "Austria"
AWAY = "Israel"
COMPETITION = "UEFA Nations League"
MATCH_DATE = "25.09.2026"


print()
print(
    "👑 BETTING BAYIN V9.1"
)

print(
    "🛡 Calibration + Uncertainty Test"
)

print()


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
        "မတွေ့ပါ။ python main.py အရင် run ပါ။"
    )


print(
    "✅ Verified research loaded."
)


print()
print(
    "🧠 Running Strength Model V3..."
)

strength = (
    calculate_match_strength(
        research
    )
)


print()
print(
    "🎲 Running Probability Model V1..."
)

probability = (
    calculate_match_probabilities(
        strength
    )
)


print()
print(
    "🛡 Running Calibration Engine..."
)

calibrated = (
    calibrate_probability_model(
        probability
    )
)


print()

print(
    format_calibration_report(
        calibrated
    )
)


print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "🔧 CALIBRATION DEBUG"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

print(
    json.dumps(
        calibrated,
        indent=2,
        ensure_ascii=False
    )
)

print()

print(
    "✅ CALIBRATION TEST COMPLETE"
)