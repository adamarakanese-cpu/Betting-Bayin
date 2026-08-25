from screenshot_merge import merge_extractions
import v13_engine as ve


def sample_pages():
    base = {
        "sport": "Football",
        "competition": "England. Development League U21",
        "round_or_group": None,
        "match": {"home_team": "Wigan Athletic U21", "away_team": "Cardiff City U21"},
        "match_type": "Pre-Match",
        "start_date": "25.08.2026",
        "start_time": "18:30",
        "live": {"is_live": False, "minute": None, "score": None},
        "unreadable_items": [],
    }
    p1 = {**base, "markets": [
        {"market_name": "1X2", "selections": [
            {"selection": "W1", "odds": 1.90}, {"selection": "X", "odds": 4.25}, {"selection": "W2", "odds": 2.94}
        ]},
        {"market_name": "Double Chance", "selections": [
            {"selection": "1X", "odds": 1.31}, {"selection": "12", "odds": 1.141}, {"selection": "2X", "odds": 1.727}
        ]},
        {"market_name": "Both Teams To Score", "selections": [
            {"selection": "Yes", "odds": 1.26}, {"selection": "No", "odds": 3.375}
        ]},
    ]}
    p2 = {**base, "markets": [
        {"market_name": "Total", "selections": [
            {"selection": "Over (0.5)", "odds": 1.01},
            {"selection": "Under (0.5)", "odds": 12.0},
            {"selection": "Over (1.5)", "odds": 1.30},
            {"selection": "Under (1.5)", "odds": 3.07},
            {"selection": "Over (2.5)", "odds": 1.65},
            {"selection": "Under (2.5)", "odds": 2.10},
        ]}
    ]}
    p3 = {**base, "markets": [
        {"market_name": "Total Goals", "selections": [
            # Latest page should overwrite duplicate visible quote.
            {"selection": "Over 1.5", "odds": 1.31},
            {"selection": "Over 3.5", "odds": 2.25},
            {"selection": "Under 3.5", "odds": 1.55},
        ]}
    ]}
    p4 = {**base, "markets": [
        {"market_name": "Handicap", "selections": [
            {"selection": "W1 (-1)", "odds": 2.50}, {"selection": "W2 (+1)", "odds": 1.50}
        ]}
    ]}
    return [p1, p2, p3, p4]


def main():
    merged = merge_extractions(sample_pages())
    assert merged.get("screenshots_merged") == 4
    assert len(merged.get("markets") or []) >= 5

    total = next(m for m in merged["markets"] if "total" in m["market_name"].lower() and "team" not in m["market_name"].lower())
    prices = {ve._canonical_selection(total["market_name"], x["selection"]): float(x["odds"]) for x in total["selections"]}
    assert prices["over1.5"] == 1.31, prices
    assert prices["over0.5"] == 1.01, prices

    calibration = {
        "one_x_two": {
            "calibrated": {"home_win": 0.52, "draw": 0.24, "away_win": 0.24},
            "reliability_factor": 0.75,
        },
        "binary_markets": {
            "totals": {
                "over_1_5": 0.76, "under_1_5": 0.24,
                "over_2_5": 0.61, "under_2_5": 0.39,
                "over_3_5": 0.46, "under_3_5": 0.54,
            },
            "btts": {"yes": 0.68, "no": 0.32},
        },
    }
    probability = {
        "expected_goals": {"home_xg": 1.55, "away_xg": 1.25},
        "team_scoring": {"home_to_score": 0.79, "away_to_score": 0.71, "home_clean_sheet": 0.29, "away_clean_sheet": 0.21},
        "most_likely_scores": [{"score": "1-1", "probability": 0.14}],
    }

    ranked = ve.rank_all_markets(merged, probability, calibration, 0.75, {})
    # Hidden Total Over 0.5 must never be synthesized anymore.
    bad_hidden = [
        c for c in ranked
        if c.get("odds_estimated")
        and ve._canonical_market(c.get("market_name")) == "total"
        and ve._canonical_selection(c.get("market_name"), c.get("selection")) == "over0.5"
    ]
    assert not bad_hidden, bad_hidden

    # The actual visible Total Over 0.5 price must remain exact and non-estimated.
    visible_05 = [
        c for c in ranked
        if not c.get("odds_estimated")
        and ve._canonical_market(c.get("market_name")) == "total"
        and ve._canonical_selection(c.get("market_name"), c.get("selection")) == "over0.5"
    ]
    assert visible_05 and abs(visible_05[0]["odds"] - 1.01) < 1e-9, visible_05

    # Final decision should prefer a practical real bookmaker quote in this
    # multi-page scenario, not fall back to a synthetic estimated market.
    ve.verify_model_context = lambda research, probability: {"enabled": False, "status": "OK", "quality_score": 0.75}
    ve.apply_performance_feedback = lambda rows: rows
    decision = ve.build_v13_decision(merged, {}, probability, calibration)
    tip = decision["tip"]
    assert tip is not None
    assert tip.get("odds_estimated") is False, tip
    assert 1.08 <= float(tip.get("odds")) <= 3.50, tip

    print("PASS: V16.1 album merge, visible-odds priority, and Over 0.5 anti-loop regression")


if __name__ == "__main__":
    main()
