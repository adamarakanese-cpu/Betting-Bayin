import os
import tempfile

# Force isolated SQLite for offline regression tests.
os.environ.pop("DATABASE_URL", None)
tmp = tempfile.NamedTemporaryFile(prefix="betting_bayin_v16_", suffix=".db", delete=False)
tmp.close()
os.environ["SQLITE_DB_PATH"] = tmp.name

from result_engine import settle_market, calibration_key
from database import (
    save_tip,
    get_pending_predictions,
    settle_prediction_score,
    get_performance_summary,
    get_performance_calibration_map,
)
from performance_engine import invalidate_feedback_cache, apply_performance_feedback

# Pure settlement regression coverage.
assert settle_market("1X2", "W1", 2, 1) == "win"
assert settle_market("1X2", "Draw", 1, 1) == "win"
assert settle_market("Double Chance", "2X", 1, 2) == "win"
assert settle_market("Both Teams To Score", "Yes", 1, 1) == "win"
assert settle_market("Total", "Over (2.5)", 2, 1) == "win"
assert settle_market("Total", "Under (3)", 2, 1) == "void"
assert settle_market("Home Team Total", "Over (0.5)", 1, 0) == "win"
assert settle_market("Away Clean Sheet", "Yes", 0, 2) == "win"
assert settle_market("Correct Score", "2-1", 2, 1) == "win"

# 20 unique settled predictions in the same calibration bucket.
for i in range(20):
    result = {
        "match": {"home_team": f"Home{i}", "away_team": f"Away{i}", "competition": "Test League"},
        "extracted_data": {
            "competition": "Test League",
            "start_date": f"{(i % 9) + 1:02d}.08.2026",
            "start_time": "15:00",
            "match": {"home_team": f"Home{i}", "away_team": f"Away{i}"},
        },
        "v13": {"tip": {
            "market_name": "Total",
            "selection": "Over (1.5)",
            "odds": 1.50,
            "odds_estimated": False,
            "model_probability": 0.60,
            "evidence_confidence": 0.70,
            "ranking_score": 0.65,
        }},
    }
    assert save_tip(999, result)

rows = get_pending_predictions(limit=30, min_age_hours=0, recheck_after_hours=0)
assert len(rows) == 20, len(rows)
for idx, row in enumerate(rows):
    # 15 wins, 5 losses for Over 1.5.
    score = (2, 0) if idx < 15 else (1, 0)
    settled = settle_prediction_score(row["id"], *score, source="test", confidence=1.0)
    assert settled["result_status"] in {"win", "loss"}

summary = get_performance_summary()
assert summary["wins"] == 15, summary
assert summary["losses"] == 5, summary
assert abs(summary["hit_rate"] - 0.75) < 1e-9, summary

cal = get_performance_calibration_map(min_key_samples=18, min_family_samples=30)
key = calibration_key("Total", "Over (1.5)")
assert key in cal["keys"], cal
assert cal["keys"][key]["adjustment"] > 0, cal

invalidate_feedback_cache()
c = [{
    "market_name": "Total", "selection": "Over (2.5)", "model_probability": 0.60,
    "market_probability": 0.58, "odds": 1.75, "odds_estimated": False,
    "expected_value": 0.05, "edge": 0.02, "ranking_score": 0.60,
}]
adj = apply_performance_feedback(c)[0]
assert adj["model_probability"] > 0.60, adj
assert adj["performance_sample"] >= 18, adj

os.unlink(tmp.name)
print("PASS: V16 result tracking, settlement, performance calibration, and feedback")
