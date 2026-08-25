from intelligence_engine import apply_selection_intelligence, no_bet_gate

def c(p, odds, evidence=.60, estimated=False, supported=True, risk=.05, ev=0.0, edge=0.0):
    return {
        "model_probability": p, "odds": odds, "ranking_score": .5,
        "evidence_confidence": evidence, "odds_estimated": estimated,
        "model_supported": supported, "risk_penalty": risk,
        "expected_value": ev, "edge": edge,
    }

# 45% candidate must not beat a materially safer 65% option due to noisy value.
r=apply_selection_intelligence([c(.45,1.28,ev=.20,edge=.15), c(.65,1.45,ev=-.02,edge=-.01)], {}, {}, {})
assert r[0]["model_probability"] == .65

# A safer unsupported visible market remains eligible and can beat weak supported one.
r=apply_selection_intelligence([c(.48,1.30,supported=True), c(.68,1.40,supported=False)], {}, {}, {})
assert r[0]["model_probability"] == .68

# Real screenshot quote wins a close comparison against an estimate.
r=apply_selection_intelligence([c(.70,1.55,estimated=True), c(.69,1.52,estimated=False)], {}, {}, {})
assert r[0]["odds_estimated"] is False

# Mandatory tip policy remains unchanged.
weak=c(.35,1.01,evidence=.05,supported=False)
assert no_bet_gate(weak, {}, {}, {"contradiction": True}) == []
print("PASS: V19.3 final accuracy selector")
