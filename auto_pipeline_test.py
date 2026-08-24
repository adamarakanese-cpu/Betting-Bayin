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

from recovery_engine import (
    recover_evidence,
)


# =========================================================
# BETTING BAYIN V11.1
# AUTOMATIC CONFLICT RECOVERY PIPELINE TEST
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
# TEST MARKET
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
        }
    ]
}


# =========================================================
# FULL MODEL RUN
# =========================================================

def run_model(
    market_analysis,
    research
):
    strength = (
        calculate_match_strength(
            research
        )
    )

    probability = (
        calculate_match_probabilities(
            strength
        )
    )

    calibration = (
        calibrate_probability_model(
            probability
        )
    )

    value = (
        calculate_market_value(
            market_analysis,
            calibration
        )
    )

    return {
        "strength":
            strength,

        "probability":
            probability,

        "calibration":
            calibration,

        "value":
            value,
    }


# =========================================================
# START
# =========================================================

print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "👑 BETTING BAYIN V11.1"
)

print(
    "🤖 AUTO RECOVERY PIPELINE"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()


# =========================================================
# MARKET
# =========================================================

market_analysis = (
    analyze_betting_data(
        market_data
    )
)

print(
    "✅ Market analysis ready."
)


# =========================================================
# CACHE
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
        "Research cache not found. "
        "Run python main.py first."
    )

print(
    "✅ Verified research loaded."
)


# =========================================================
# FIRST MODEL RUN
# =========================================================

print()
print(
    "🧠 FIRST MODEL RUN"
)

first = run_model(
    market_analysis,
    research
)

first_value = (
    first["value"]
)

print()

print(
    format_value_report(
        first_value
    )
)


# =========================================================
# SHOULD RECOVER?
# =========================================================

first_decision = (
    first_value.get(
        "decision"
    )
)

first_suitability = (
    first_value.get(
        "betting_suitability",
        {}
    ).get(
        "suitable_for_betting"
    )
)


needs_recovery = (
    first_decision
    ==
    "DATA_CONFLICT"
    or
    first_suitability
    ==
    "NO"
)


# =========================================================
# NO RECOVERY REQUIRED
# =========================================================

if not needs_recovery:

    print()
    print(
        "✅ No automatic recovery required."
    )

    final_result = first

    recovery_result = None


# =========================================================
# AUTO RECOVERY
# =========================================================

else:

    print()
    print(
        "🚨 Weak/conflicting evidence detected."
    )

    print(
        "🔄 Starting automatic recovery..."
    )

    recovery_result = (
        recover_evidence(
            research
        )
    )

    recovered_research = (
        recovery_result[
            "research"
        ]
    )

    print()
    print(
        "🧠 SECOND MODEL RUN"
    )

    final_result = run_model(
        market_analysis,
        recovered_research
    )


# =========================================================
# FINAL
# =========================================================

print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "👑 FINAL MODEL RESULT"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

print(
    format_value_report(
        final_result[
            "value"
        ]
    )
)


# =========================================================
# COMPARISON
# =========================================================

print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "📊 BEFORE / AFTER"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

print(
    "Before Decision:",
    first[
        "value"
    ].get(
        "decision"
    )
)

print(
    "Before Reliability:",
    first[
        "calibration"
    ][
        "one_x_two"
    ][
        "reliability_factor"
    ]
)

print(
    "Before Suitability:",
    first[
        "calibration"
    ][
        "betting_suitability"
    ][
        "suitable_for_betting"
    ]
)


print()

print(
    "After Decision:",
    final_result[
        "value"
    ].get(
        "decision"
    )
)

print(
    "After Reliability:",
    final_result[
        "calibration"
    ][
        "one_x_two"
    ][
        "reliability_factor"
    ]
)

print(
    "After Suitability:",
    final_result[
        "calibration"
    ][
        "betting_suitability"
    ][
        "suitable_for_betting"
    ]
)


# =========================================================
# FULL DEBUG
# =========================================================

print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "🔧 AUTO PIPELINE DEBUG"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

debug = {
    "first_value":
        first["value"],

    "recovery":
        recovery_result,

    "final_value":
        final_result[
            "value"
        ],

    "final_calibration":
        final_result[
            "calibration"
        ],

    "final_probability":
        final_result[
            "probability"
        ],
}


print(
    json.dumps(
        debug,
        indent=2,
        ensure_ascii=False,
        default=str,
    )
)


print()
print(
    "✅ V11.1 AUTO PIPELINE COMPLETE"
)