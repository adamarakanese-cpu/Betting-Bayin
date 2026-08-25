from v13_engine import rank_all_markets, format_v13_tip


def base_calibration():
    return {
        'one_x_two': {'calibrated': {'home_win': .43, 'draw': .25, 'away_win': .32}, 'reliability_factor': .4},
        'binary_markets': {'btts': {'yes': .30, 'no': .70}, 'totals': {'over_1_5': .66, 'under_1_5': .34}},
    }


def test_visible_double_chance_is_authoritative():
    extracted = {
        'competition': 'Friendlies U20. National Teams',
        'match': {'home_team': 'Iran U20', 'away_team': 'Iraq U20'},
        'live': {'is_live': False},
        'markets': [
            {'market_name': 'Double Chance', 'selections': [
                {'selection': '1X', 'odds': 1.12}, {'selection': '12', 'odds': 1.53}, {'selection': '2X', 'odds': 1.42}
            ]}
        ],
    }
    ranked = rank_all_markets(extracted, {}, base_calibration(), .4, {'enabled': False})
    expected = {'1X': 1.12, '12': 1.53, '2X': 1.42}
    for selection, odds in expected.items():
        rows = [x for x in ranked if x['market_name'] == 'Double Chance' and x['selection'] == selection]
        assert len(rows) == 1, (selection, rows)
        assert rows[0]['odds'] == odds
        assert rows[0]['odds_estimated'] is False
        assert rows[0]['source'] == 'screenshot'


def test_hidden_market_can_be_estimated_but_not_duplicate_visible():
    extracted = {
        'competition': 'League', 'match': {'home_team': 'A', 'away_team': 'B'},
        'markets': [{'market_name': '1X2', 'selections': [
            {'selection': 'W1', 'odds': 2.10}, {'selection': 'Draw', 'odds': 3.20}, {'selection': 'W2', 'odds': 3.50}
        ]}]
    }
    ranked = rank_all_markets(extracted, {}, base_calibration(), .5, {'enabled': False})
    dc = [x for x in ranked if x['market_name'] == 'Double Chance']
    assert {x['selection'] for x in dc} == {'1X', '12', '2X'}
    assert all(x['odds_estimated'] for x in dc)


def test_customer_output_never_uses_x2():
    result = {
        'match': {'home_team': 'A', 'away_team': 'B', 'competition': 'League'},
        'extracted_data': {'live': {'is_live': False}},
        'v13': {'tip': {'market_name': 'Double Chance', 'selection': 'X2', 'odds': 1.42,
                        'odds_estimated': False, 'model_probability': .70}},
    }
    text = format_v13_tip(result)
    assert 'Double Chance — 2X' in text
    assert 'Double Chance — X2' not in text
    assert 'Odds: 1.420' in text


if __name__ == '__main__':
    test_visible_double_chance_is_authoritative()
    test_hidden_market_can_be_estimated_but_not_duplicate_visible()
    test_customer_output_never_uses_x2()
    print('PASS: V13.7 market/odds regression suite')
