from screenshot_merge import merge_extractions
from context_profile import build_match_context_profile
from probability_engine import calculate_expected_goals
from result_engine import settle_market, calibration_key
from v13_engine import format_v13_tip


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_period_merge():
    base = {
        "sport": "football",
        "competition": "Test League",
        "match": {"home_team": "A", "away_team": "B"},
        "match_type": "pre-match",
        "live": {"is_live": False},
        "unreadable_items": [],
    }
    a = dict(base)
    a["markets"] = [{
        "market_name": "Total",
        "period": "regular_time",
        "selections": [{"selection": "Over (1.5)", "odds": 1.30}],
    }]
    b = dict(base)
    b["markets"] = [{
        "market_name": "Total",
        "period": "1st_half",
        "selections": [{"selection": "Over (0.5)", "odds": 1.55}],
    }]
    merged = merge_extractions([a, b])
    periods = {(m["period"], m["market_name"]) for m in merged["markets"]}
    _assert(("regular_time", "Total") in periods, "regular-time total lost")
    _assert(("1st_half", "Total") in periods, "first-half total lost")
    _assert(len(merged["markets"]) == 2, "period markets were incorrectly merged")


def test_customer_format():
    hidden = {
        "match": {"home_team": "A", "away_team": "B", "competition": "L"},
        "extracted_data": {"match": {"home_team": "A", "away_team": "B"}, "competition": "L"},
        "v13": {"tip": {
            "market_name": "Regular Time Total",
            "base_market_name": "Total",
            "period": "regular_time",
            "selection": "Over (2.5)",
            "odds": 1.70,
            "odds_estimated": True,
            "model_probability": 0.61,
        }},
    }
    text = format_v13_tip(hidden)
    _assert(text.startswith("👑 BETTING BAYIN PRE-BET"), "version leaked into title")
    _assert("Regular Time — Over (2.5)" in text, "regular-time label missing")
    _assert("Estimated" not in text and "💰 Odds" not in text, "estimated odds leaked to customer")

    actual = {
        **hidden,
        "v13": {"tip": {
            "market_name": "1st Half Total",
            "base_market_name": "Total",
            "period": "1st_half",
            "selection": "Over (0.5)",
            "odds": 1.80,
            "odds_estimated": False,
            "model_probability": 0.64,
        }},
    }
    text2 = format_v13_tip(actual)
    _assert("1st Half — Over (0.5)" in text2, "first-half label missing")
    _assert("💰 Odds: 1.800" in text2, "real screenshot odds should remain visible")


def _neutral_team(team):
    return {
        "team": team,
        "ratings": {
            "form": 0.5,
            "attack": 0.5,
            "defence": 0.5,
            "performance_strength": 0.5,
            "elo_strength": 0.5,
            "adjusted_strength": 0.5,
            "data_confidence": 0.8,
        },
        "metrics": {"trusted_ratio": 0.8, "opponent_elo_coverage": 0.8},
        "own_elo": {"available": True, "strength_score": 0.5},
    }


def test_context_profile_and_xg():
    research = {
        "home_team": "A", "away_team": "B", "competition": "Open League",
        "home_recent_matches": [
            {"goals_for": 3, "goals_against": 2},
            {"goals_for": 2, "goals_against": 2},
            {"goals_for": 4, "goals_against": 1},
            {"goals_for": 2, "goals_against": 1},
            {"goals_for": 3, "goals_against": 1},
        ],
        "away_recent_matches": [
            {"goals_for": 2, "goals_against": 2},
            {"goals_for": 3, "goals_against": 2},
            {"goals_for": 1, "goals_against": 3},
            {"goals_for": 2, "goals_against": 2},
            {"goals_for": 3, "goals_against": 1},
        ],
        "league_profile": {
            "sample_size": 100,
            "avg_total_goals": 3.35,
            "over_2_5_rate": 0.62,
            "btts_rate": 0.59,
            "style_tags": ["high-scoring"],
            "source_urls": ["https://example.com/league-stats"],
        },
        "home_team_profile": {},
        "away_team_profile": {},
    }
    ctx = build_match_context_profile(research)
    _assert(ctx["target_total_goals"] > 2.55, "high-scoring verified context did not raise goal environment")
    _assert(ctx["quality"] > 0.4, "context quality unexpectedly weak")

    neutral = {"home": _neutral_team("A"), "away": _neutral_team("B")}
    no_ctx = calculate_expected_goals(dict(neutral))
    with_ctx_input = dict(neutral)
    with_ctx_input["context_profile"] = ctx
    with_ctx = calculate_expected_goals(with_ctx_input)
    _assert(with_ctx["total_xg"] > no_ctx["total_xg"], "context did not influence expected goals")
    _assert(with_ctx["total_xg"] - no_ctx["total_xg"] < 0.6, "context adjustment is too aggressive")


def test_period_result_safety():
    _assert(settle_market("Regular Time Total", "Over (0.5)", 2, 0) == "win", "regular-time settlement broken")
    _assert(settle_market("1st Half Total", "Over (0.5)", 2, 0) is None, "half market incorrectly settled from FT score")
    _assert(calibration_key("1st Half Total", "Over (0.5)").startswith("1st_half:"), "period missing from calibration key")


if __name__ == "__main__":
    test_period_merge()
    test_customer_format()
    test_context_profile_and_xg()
    test_period_result_safety()
    print("PASS: V16.2 period labels, hidden-odds privacy, dynamic context, and settlement safety")
