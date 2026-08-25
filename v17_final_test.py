from match_reconcile import reconcile_album_extractions
from screenshot_merge import merge_extractions
from parlay_engine import build_best_parlay

pages=[
 {'competition':'Friendlies U20','start_date':'2026-08-25','match':{'home_team':'Uzbekistan U20','away_team':'South Korea U20'},'markets':[{'market_name':'Total','period':'regular_time','selections':[{'selection':'Over (1.5)','odds':1.31}]}]},
 {'competition':'Friendlies U20','start_date':'2026-08-25','match':{'home_team':'Completely Different Club','away_team':'South Korea'},'markets':[{'market_name':'Both Teams To Score','period':'1st_half','selections':[{'selection':'No','odds':1.14}]}]},
]
r,meta=reconcile_album_extractions(pages); m=merge_extractions(r)
assert m['match']['home_team']=='Uzbekistan U20'
assert m['match']['away_team']=='South Korea U20'
assert len(m['markets'])==2
assert meta['identity_conflicts']
rows=[
 {'home_team':'A','away_team':'B','competition':'L1','model_probability':.7,'evidence_confidence':.8,'odds':1.5,'odds_estimated':False},
 {'home_team':'C','away_team':'D','competition':'L1','model_probability':.69,'evidence_confidence':.8,'odds':1.5,'odds_estimated':False},
 {'home_team':'E','away_team':'F','competition':'L2','model_probability':.68,'evidence_confidence':.8,'odds':1.5,'odds_estimated':False},
]
assert build_best_parlay(rows)
print('PASS: V17 album lock/reconciliation and parlay risk logic')
