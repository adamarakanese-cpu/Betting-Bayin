from intelligence_engine import no_bet_gate

weak = {
    "model_probability": 0.40,
    "evidence_confidence": 0.05,
    "odds": 1.01,
    "expected_value": -0.25,
}
assert no_bet_gate(weak, {}, {"context_profile": {"quality": 0.01}}, {"contradiction": True}) == []
assert no_bet_gate(None, {}, {}, {})
print("PASS: V19.1 mandatory best-available-tip policy")
