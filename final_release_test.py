from v13_engine import rank_all_markets, format_v13_tip


def calibration(reliability=.45):
    return {
        'one_x_two': {'calibrated': {'home_win': .44, 'draw': .27, 'away_win': .29}, 'reliability_factor': reliability},
        'binary_markets': {
            'btts': {'yes': .54, 'no': .46},
            'totals': {
                'over_1_5': .78, 'under_1_5': .22,
                'over_2_5': .59, 'under_2_5': .41,
                'over_3_5': .43, 'under_3_5': .57,
            },
        },
    }


def test_visible_total_price_is_absolute_source_of_truth():
    extracted = {
        'competition': 'Cambodia Cup',
        'match': {'home_team': 'Preah Sihanouk', 'away_team': 'Kampot'},
        'live': {'is_live': False},
        'markets': [{'market_name': 'Total', 'selections': [
            {'selection': 'Over (3.5)', 'odds': 1.85},
            {'selection': 'Under (3.5)', 'odds': 1.85},
        ]}],
    }
    ranked = rank_all_markets(extracted, {}, calibration(), .45, {'enabled': False})
    rows = [r for r in ranked if r['market_name'] == 'Total' and r['selection'] == 'Under (3.5)']
    assert len(rows) == 1, rows
    assert rows[0]['odds'] == 1.85
    assert rows[0]['odds_estimated'] is False
    assert rows[0]['source'] == 'screenshot'


def test_market_alias_deduplication():
    extracted = {
        'competition': 'League', 'match': {'home_team': 'A', 'away_team': 'B'},
        'markets': [
            {'market_name': 'BTTS', 'selections': [{'selection': 'Yes', 'odds': 1.9}, {'selection': 'No', 'odds': 1.8}]},
            {'market_name': 'Double Chance', 'selections': [{'selection': '1X', 'odds': 1.3}, {'selection': '12', 'odds': 1.5}, {'selection': '2X', 'odds': 1.7}]},
        ],
    }
    ranked = rank_all_markets(extracted, {}, calibration(), .45, {'enabled': False})
    btts_yes = [r for r in ranked if r['selection'].lower() == 'yes' and 'btts' in r['market_name'].lower()]
    assert len(btts_yes) == 1 and not btts_yes[0]['odds_estimated']
    dcs = [r for r in ranked if 'double chance' in r['market_name'].lower()]
    assert len(dcs) == 3
    assert all(not r['odds_estimated'] for r in dcs)


def test_hidden_market_output_is_range_not_fake_quote():
    result = {
        'match': {'home_team': 'A', 'away_team': 'B', 'competition': 'League'},
        'extracted_data': {'live': {'is_live': False}},
        'v13': {'tip': {
            'market_name': 'Total', 'selection': 'Under (3.5)', 'odds': 1.76,
            'estimated_odds_low': 1.61, 'estimated_odds_high': 1.91,
            'odds_estimated': True, 'model_probability': .55,
        }},
    }
    text = format_v13_tip(result)
    assert 'Estimated Odds Range: 1.61–1.91' in text
    assert 'Odds: 1.760' not in text


def test_double_chance_customer_names_only():
    for alias, expected in [('X1', '1X'), ('1X', '1X'), ('X2', '2X'), ('2X', '2X'), ('21', '12')]:
        result = {
            'match': {'home_team': 'A', 'away_team': 'B', 'competition': 'League'},
            'extracted_data': {'live': {'is_live': False}},
            'v13': {'tip': {'market_name': 'Double Chance', 'selection': alias, 'odds': 1.42,
                            'odds_estimated': False, 'model_probability': .70}},
        }
        text = format_v13_tip(result)
        assert f'Double Chance — {expected}' in text, text


if __name__ == '__main__':
    test_visible_total_price_is_absolute_source_of_truth()
    test_market_alias_deduplication()
    test_hidden_market_output_is_range_not_fake_quote()
    test_double_chance_customer_names_only()
    print('PASS: V15.0 FINAL pre-bet release tests')
