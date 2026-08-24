import json

from analysis_engine import (
    analyze_betting_data,
)

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
)

from value_engine import (
    calculate_market_value,
    format_value_report,
)


# =========================================================
# CURRENT TEST FIXTURE
# =========================================================

HOME = "Austria"
AWAY = "Israel"

COMPETITION = (
    "UEFA Nations League"
)

MATCH_DATE = (
    "25.09.2026"
)


# =========================================================
# SCREENSHOT MARKET TEST DATA
#
# TEST ONLY.
# Production will come from Vision extraction.
# =========================================================

market_data = {

    "sport":
        "Football",

    "competition":
        COMPETITION,

    "match": {
        "home_team":
            HOME,

        "away_team":
            AWAY,
    },

    "match_type":
        "Pre-match",

    "start_date":
        MATCH_DATE,

    "markets": [

        {
            "market_name":
                "1X2",

            "selections": [

                {
                    "selection":
                        "W1",

                    "odds":
                        1.37
                },

                {
                    "selection":
                        "X",

                    "odds":
                        5.30
                },

                {
                    "selection":
                        "W2",

                    "odds":
                        9.10
                },
            ]
        },

        {
            "market_name":
                "Both Teams To Score",

            "selections": [

                {
                    "selection":
                        "Yes",

                    "odds":
                        1.84
                },

                {
                    "selection":
                        "No",

                    "odds":
                        1.881
                },
            ]
        }
    ]
}


print()
print(
    "👑 BETTING BAYIN V10"
)

print(
    "💹 Market Value Test"
)

print()


# =========================================================
# MARKET ANALYSIS
# =========================================================

market_analysis = (
    analyze_betting_data(
        market_data
    )
)

print(
    "✅ Market analysis completed."
)


# =========================================================
# VERIFIED RESEARCH
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
        "မတွေ့ပါ။"
    )

print(
    "✅ Verified research loaded."
)


# =========================================================
# STRENGTH
# =========================================================

strength = (
    calculate_match_strength(
        research
    )
)

print(
    "✅ Strength model completed."
)


# =========================================================
# PROBABILITY
# =========================================================

probability = (
    calculate_match_probabilities(
        strength
    )
)

print(
    "✅ Probability model completed."
)


# =========================================================
# CALIBRATION
# =========================================================

calibration = (
    calibrate_probability_model(
        probability
    )
)

print(
    "✅ Calibration completed."
)


# =========================================================
# MARKET VALUE
# =========================================================

value_result = (
    calculate_market_value(
        market_analysis,
        calibration
    )
)


print()
print(
    format_value_report(
        value_result
    )
)


print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "🔧 VALUE DEBUG"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

print(
    json.dumps(
        value_result,
        indent=2,
        ensure_ascii=False,
        default=str
    )
)


print()
print(
    "✅ BETTING BAYIN V10 "
    "TEST COMPLETE"
)