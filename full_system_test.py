import json
import sys

from analysis_engine import analyze_betting_data
from probability_engine import calculate_match_probabilities
from calibration_engine import calibrate_probability_model
from value_engine import calculate_market_value


# =========================================================
# BETTING BAYIN V12
# OFFLINE CORE SELF-TEST
# =========================================================
#
# No API key required.
# No internet required.
# No Groq call required.
#
# This checks compatibility between:
# Analysis -> Strength V4 -> Probability V2 ->
# Calibration -> Value Engine.
# =========================================================


MARKET_DATA = {
    "sport": "Football",
    "competition": "UEFA Nations League",
    "match": {
        "home_team": "Austria",
        "away_team": "Israel",
    },
    "match_type": "Pre-match",
    "start_date": "25.09.2026",
    "markets": [
        {
            "market_name": "1X2",
            "selections": [
                {"selection": "W1", "odds": 1.37},
                {"selection": "X", "odds": 5.30},
                {"selection": "W2", "odds": 9.10},
            ],
        }
    ],
}


RESEARCH_DATA = {
    "home_team": "Austria",
    "away_team": "Israel",
    "competition": "UEFA Nations League",
    "match_date": "25.09.2026",
    "home_recent_matches": [],
    "away_recent_matches": [],
}


def fake_strength_result():
    return {
        "home": {
            "team": "Austria",
            "role": "home",
            "metrics": {
                "matches": 5,
                "effective_sample": 3.0,
                "weighted_ppm": 1.5,
                "weighted_goals_for": 1.25,
                "weighted_goals_against": 1.8,
                "trusted_ratio": 1.0,
                "opponent_elo_coverage": 1.0,
                "match_details": [],
            },
            "ratings": {
                "form": 0.50,
                "attack": 0.42,
                "defence": 0.45,
                "performance_strength": 0.46,
                "elo_strength": 0.667,
                "raw_strength": 0.55,
                "data_confidence": 0.95,
                "adjusted_strength": 0.55,
            },
            "own_elo": {
                "team": "Austria",
                "elo": 1821,
                "rank": 23,
                "available": True,
                "future_data_used": False,
                "strength_score": 0.667,
            },
        },
        "away": {
            "team": "Israel",
            "role": "away",
            "metrics": {
                "matches": 8,
                "effective_sample": 1.0,
                "weighted_ppm": 1.4,
                "weighted_goals_for": 1.6,
                "weighted_goals_against": 1.8,
                "trusted_ratio": 0.5,
                "opponent_elo_coverage": 1.0,
                "match_details": [],
            },
            "ratings": {
                "form": 0.49,
                "attack": 0.55,
                "defence": 0.47,
                "performance_strength": 0.50,
                "elo_strength": 0.424,
                "raw_strength": 0.47,
                "data_confidence": 0.63,
                "adjusted_strength": 0.48,
            },
            "own_elo": {
                "team": "Israel",
                "elo": 1647,
                "rank": 56,
                "available": True,
                "future_data_used": False,
                "strength_score": 0.424,
            },
        },
        "strength_difference": 0.07,
        "elo_difference": 174,
        "raw_lean": "Austria",
        "reliable_lean": "Austria",
        "reliability": {
            "status": "MEDIUM",
            "minimum_confidence": 0.63,
            "reasons": [],
        },
        "bookmaker_odds_used": False,
        "own_team_elo_used": True,
        "opponent_strength_used": True,
        "future_elo_leakage_allowed": False,
        "model_stage": "INDEPENDENT_TEAM_STRENGTH_V4",
    }


def main():
    print("👑 BETTING BAYIN V12")
    print("🧪 Offline Core Self-Test")
    print()

    market = analyze_betting_data(MARKET_DATA)
    strength = fake_strength_result()
    probability = calculate_match_probabilities(strength)
    calibration = calibrate_probability_model(probability)
    value = calculate_market_value(market, calibration)

    checks = {
        "probability_v2": probability.get("model_stage") == "INDEPENDENT_PROBABILITY_V2",
        "strength_v4_compatible": probability.get("own_team_elo_used") is True,
        "sanity": probability.get("sanity_checks", {}).get("all_passed") is True,
        "calibration": calibration.get("model_stage") == "CALIBRATION_UNCERTAINTY_V1",
        "value": value.get("model_stage") == "MARKET_VALUE_V1",
        "decision_present": bool(value.get("decision")),
    }

    all_passed = all(checks.values())

    for name, passed in checks.items():
        print(f"{'✅' if passed else '❌'} {name}")

    print()
    print("Final Decision:", value.get("decision"))
    print("Sanity:", probability.get("sanity_checks", {}).get("all_passed"))
    print("Model Stage:", probability.get("model_stage"))

    if not all_passed:
        print("\n❌ SELF-TEST FAILED")
        sys.exit(1)

    print("\n✅ ALL CORE TESTS PASSED")


if __name__ == "__main__":
    main()
