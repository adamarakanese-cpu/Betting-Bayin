from parlay_engine import build_best_parlay, format_parlay

rows = [
    {"home_team":"A","away_team":"B","competition":"L1","market_name":"Double Chance","selection":"1X","odds":1.40,"odds_estimated":False,"model_probability":0.72,"evidence_confidence":0.70,"ranking_score":0.70},
    {"home_team":"C","away_team":"D","competition":"L2","market_name":"Total","selection":"Over (1.5)","odds":1.35,"odds_estimated":False,"model_probability":0.69,"evidence_confidence":0.65,"ranking_score":0.66},
    {"home_team":"E","away_team":"F","competition":"L3","market_name":"Both Teams To Score","selection":"Yes","odds":1.75,"odds_estimated":True,"estimated_odds_low":1.62,"estimated_odds_high":1.88,"model_probability":0.61,"evidence_confidence":0.56,"ranking_score":0.59},
    {"home_team":"G","away_team":"H","competition":"L4","market_name":"Correct Score","selection":"1-1","odds":6.50,"odds_estimated":True,"estimated_odds_low":5.8,"estimated_odds_high":7.2,"model_probability":0.18,"evidence_confidence":0.50,"ranking_score":0.20},
    {"home_team":"I","away_team":"J","competition":"L5","market_name":"Total","selection":"Under (3.5)","odds":1.65,"odds_estimated":False,"model_probability":0.64,"evidence_confidence":0.60,"ranking_score":0.62},
]

p = build_best_parlay(rows, requested_pool_size=5)
assert p is not None
assert 2 <= len(p["legs"]) <= 4
assert all(float(x["model_probability"]) >= 0.52 for x in p["legs"])
assert not any(x["market_name"] == "Correct Score" for x in p["legs"])
text = format_parlay(p)
assert "BEST ACCUMULATOR" in text
assert "Combined" in text
assert "recent 5 tips" in text
print("PASS: V15.0 FINAL single-to-parlay selection tests")
