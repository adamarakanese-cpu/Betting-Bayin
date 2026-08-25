import re
from difflib import SequenceMatcher


def norm_team(value):
    text = str(value or '').lower().replace('&', ' and ')
    text = re.sub(r'\b(fc|cf|afc|sc|club|football|soccer)\b', ' ', text)
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def similarity(a, b):
    a, b = norm_team(a), norm_team(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _quality(x):
    m = x.get('match') or {}
    score = 0
    score += 3 if m.get('home_team') else 0
    score += 3 if m.get('away_team') else 0
    score += 2 if x.get('competition') else 0
    score += 1 if x.get('start_date') else 0
    score += min(4, len(x.get('markets') or []))
    return score


def reconcile_album_extractions(extractions):
    """Treat one Telegram album as one fixture and repair OCR/vision name drift.

    The highest-quality page is the anchor. Other pages keep their markets but
    inherit the anchor identity unless they strongly and consistently identify a
    completely different fixture. Telegram albums are intentionally one-match by
    product policy, so a single OCR mistake can never create a second customer tip.
    """
    rows = [dict(x) for x in (extractions or []) if isinstance(x, dict)]
    if not rows:
        return [], {'anchor': None, 'identity_conflicts': []}
    anchor = max(rows, key=_quality)
    am = anchor.get('match') or {}
    ah, aa = am.get('home_team'), am.get('away_team')
    conflicts = []
    repaired = []
    for idx, row in enumerate(rows, 1):
        row = dict(row)
        rm = dict(row.get('match') or {})
        rh, ra = rm.get('home_team'), rm.get('away_team')
        direct = (similarity(ah, rh) + similarity(aa, ra)) / 2 if ah and aa and rh and ra else 0
        swapped = (similarity(ah, ra) + similarity(aa, rh)) / 2 if ah and aa and rh and ra else 0
        if rh and ra and max(direct, swapped) < 0.55:
            conflicts.append({'page': idx, 'read_home': rh, 'read_away': ra, 'similarity': round(max(direct, swapped), 3)})
        rm['home_team'] = ah or rh
        rm['away_team'] = aa or ra
        row['match'] = rm
        if anchor.get('competition'):
            row['competition'] = anchor.get('competition')
        if anchor.get('start_date'):
            row['start_date'] = anchor.get('start_date')
        if anchor.get('start_time'):
            row['start_time'] = anchor.get('start_time')
        repaired.append(row)
    return repaired, {'anchor': {'home_team': ah, 'away_team': aa}, 'identity_conflicts': conflicts}
