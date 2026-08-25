from intelligence_engine import no_bet_gate

def test_no_bet_low_quality():
    b={"model_probability":.52,"evidence_confidence":.2,"odds":1.8,"expected_value":-.06}
    assert no_bet_gate(b, {}, {"context_profile":{"quality":.1}}, {})

def test_good_tip_passes():
    b={"model_probability":.68,"evidence_confidence":.65,"odds":1.7,"expected_value":.08}
    assert no_bet_gate(b, {}, {"context_profile":{"quality":.6}}, {}) == []

if __name__ == '__main__':
    test_no_bet_low_quality(); test_good_tip_passes(); print('V19 accuracy tests PASS')
