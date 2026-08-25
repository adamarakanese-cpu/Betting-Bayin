from intelligence_engine import apply_selection_intelligence, no_bet_gate

def c(p, odds, score=.50, evidence=.60, estimated=False, supported=True, risk=.05):
    return {
        "model_probability": p, "odds": odds, "ranking_score": score,
        "evidence_confidence": evidence, "odds_estimated": estimated,
        "model_supported": supported, "risk_penalty": risk,
        "expected_value": p*odds-1, "edge": 0.02,
    }

# A materially stronger real-price candidate should beat an ultra-short weak-value pick.
r = apply_selection_intelligence([c(.91,1.04,.52), c(.74,1.42,.55)], {}, {}, {})
assert r[0]["odds"] == 1.42

# Real screenshot quote should win a close comparison against an estimate.
r = apply_selection_intelligence([c(.70,1.55,.55,estimated=True), c(.69,1.52,.55,estimated=False)], {}, {}, {})
assert r[0]["odds_estimated"] is False

# Mandatory tip policy remains unchanged even under contradiction.
weak=c(.40,1.01,.1,evidence=.05,supported=False)
assert no_bet_gate(weak, {}, {}, {"contradiction": True}) == []
print("PASS: V19.2 selection intelligence")
