import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

MARKET_HEADERS = [
    '1X2', 'Double Chance', 'Team To Qualify For The Next Stage',
    'Both Teams To Score', 'Total', 'Asian Total', 'Handicap', 'Asian Handicap',
    'Team 1 Total', 'Team 2 Total', 'Individual Total 1', 'Individual Total 2',
    'Draw No Bet', 'Result + Total', 'Result + Both Teams To Score',
    'Win To Nil', 'Correct Score', 'Corners', 'Corner Total', 'Yellow Cards',
    'Red Cards', '1st Half 1X2', '2nd Half 1X2'
]

NAV_TERMS = {
    'all markets', 'popular', 'total', 'handicap', 'regular time', '1st half',
    '2nd half', 'corners', 'quick', 'favorites', 'bet slip', 'history', 'menu'
}

UI_NOISE = {
    'football', 'round', 'popular', 'all', 'markets', 'regular', 'time', 'half',
    'total', 'handicap', 'corners', 'quick', 'favorites', 'bet', 'slip', 'menu',
    'starts', 'in', 'prematch', 'pre-match', 'betting'
}


def _clean(s: Any) -> str:
    return re.sub(r'\s+', ' ', str(s or '').strip())


def _norm(s: Any) -> str:
    return re.sub(r'[^a-z0-9+]+', ' ', _clean(s).lower()).strip()


def _is_odds_token(token: str) -> bool:
    t = _clean(token).replace(',', '.')
    if '(' in t or ')' in t or '+' in t or '%' in t:
        return False
    if not re.fullmatch(r'\d+(?:\.\d{1,3})?', t):
        return False
    try:
        value = float(t)
    except Exception:
        return False
    return 1.001 <= value <= 999.0


def _odds_value(token: str):
    try:
        return float(_clean(token).replace(',', '.'))
    except Exception:
        return None


def _preprocess(path: str) -> List[np.ndarray]:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert('RGB')
        arr = np.array(im)
    # Keep the full screenshot, enlarge text and create several OCR-friendly variants.
    h, w = arr.shape[:2]
    if max(h, w) < 1800:
        scale = min(2.2, 1800.0 / max(h, w))
    else:
        scale = 1.25
    arr = cv2.resize(arr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 9)
    return [gray, otsu, adaptive]


def _words(img: np.ndarray, psm: int = 6) -> List[Dict[str, Any]]:
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=f'--oem 3 --psm {int(psm)}')
    out = []
    for i, txt in enumerate(data.get('text', [])):
        txt = _clean(txt)
        if not txt:
            continue
        try:
            conf = float(data['conf'][i])
        except Exception:
            conf = -1
        if conf < 18:
            continue
        left, top = int(data['left'][i]), int(data['top'][i])
        width, height = int(data['width'][i]), int(data['height'][i])
        out.append({
            'text': txt, 'conf': conf, 'left': left, 'top': top,
            'right': left + width, 'bottom': top + height,
            'cx': left + width / 2.0, 'cy': top + height / 2.0,
            'block': int(data['block_num'][i]), 'par': int(data['par_num'][i]),
            'line': int(data['line_num'][i]),
        })
    return out


def _lines(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets = defaultdict(list)
    for w in words:
        buckets[(w['block'], w['par'], w['line'])].append(w)
    lines = []
    for ws in buckets.values():
        ws.sort(key=lambda x: x['left'])
        lines.append({
            'text': ' '.join(x['text'] for x in ws),
            'words': ws,
            'left': min(x['left'] for x in ws),
            'right': max(x['right'] for x in ws),
            'top': min(x['top'] for x in ws),
            'bottom': max(x['bottom'] for x in ws),
            'cy': sum(x['cy'] for x in ws) / len(ws),
            'conf': sum(x['conf'] for x in ws) / len(ws),
        })
    lines.sort(key=lambda x: (x['top'], x['left']))
    return lines


def _header_name(text: str):
    n = _norm(text)
    if not n:
        return None
    exact_map = {
        '1x2': '1X2',
        'double chance': 'Double Chance',
        'both teams to score': 'Both Teams To Score',
        'team to qualify for the next stage': 'Team To Qualify For The Next Stage',
        'asian total': 'Asian Total',
        'asian handicap': 'Asian Handicap',
        'draw no bet': 'Draw No Bet',
        'win to nil': 'Win To Nil',
        'correct score': 'Correct Score',
        'result total': 'Result + Total',
        'result both teams to score': 'Result + Both Teams To Score',
        'yellow cards': 'Yellow Cards',
        'red cards': 'Red Cards',
        'corners': 'Corners',
    }
    if n in exact_map:
        return exact_map[n]
    if n in {'total', 'handicap'}:
        return n.title()
    if 'team 1 total' in n or 'individual total 1' in n:
        return 'Team 1 Total'
    if 'team 2 total' in n or 'individual total 2' in n:
        return 'Team 2 Total'
    if 'qualify' in n and 'team' in n:
        return 'Team To Qualify For The Next Stage'
    if 'both teams' in n and 'score' in n:
        return 'Both Teams To Score'
    # Conservative fuzzy match only for short header-like lines.
    if len(n) <= 48:
        best, ratio = None, 0.0
        for h in MARKET_HEADERS:
            r = SequenceMatcher(None, n, _norm(h)).ratio()
            if r > ratio:
                best, ratio = h, r
        if ratio >= 0.82:
            return best
    return None


def _detect_meta(lines: List[Dict[str, Any]], words: List[Dict[str, Any]]) -> Dict[str, Any]:
    competition = None
    pre_signal = False
    live_signal = False
    start_date = None
    start_time = None

    for ln in lines:
        txt = ln['text']
        low = txt.lower()
        if competition is None and 'football' in low:
            competition = txt
        if any(x in low for x in ['starts in', 'pre-match', 'prematch', 'pre match betting', 'pre-match betting']):
            pre_signal = True
        if any(x in low for x in ['time elapsed', 'halftime', 'half time']) or re.search(r"\b\d{1,3}\s*['’]\b", txt):
            live_signal = True
        if start_date is None:
            m = re.search(r'\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b', txt)
            if m:
                start_date = m.group(1)
                pre_signal = True
        if start_time is None:
            m = re.search(r'\b(\d{1,2}:\d{2}(?:\s*[AP]M)?)\b', txt, re.I)
            if m and 'time elapsed' not in low:
                start_time = m.group(1)

    # Find VS token and reconstruct teams from nearby left/right words.
    home = away = None
    vs_words = [w for w in words if _norm(w['text']) in {'vs', 'v'}]
    for vs in vs_words:
        y = vs['cy']
        nearby = [w for w in words if abs(w['cy'] - y) <= max(42, (w['bottom']-w['top']) * 2.5)]
        left = [w for w in nearby if w['right'] < vs['left']]
        right = [w for w in nearby if w['left'] > vs['right']]
        left.sort(key=lambda x: x['left']); right.sort(key=lambda x: x['left'])
        def clean_team(ws):
            toks = []
            for x in ws:
                tok = _clean(x['text']).strip('|-–')
                if not tok or _norm(tok) in UI_NOISE or _is_odds_token(tok):
                    continue
                toks.append(tok)
            val = _clean(' '.join(toks)).strip(' -–|')
            return val if len(val) >= 2 else None
        h, a = clean_team(left[-6:]), clean_team(right[:6])
        if h and a:
            home, away = h, a
            break

    # PSM 11 often places team names on separate rows below the VS token.
    if (not home or not away) and vs_words:
        for vs in vs_words:
            y0, x0 = vs['cy'], vs['cx']
            band = [w for w in words if y0 + 5 <= w['cy'] <= y0 + 180]
            left_words = [w for w in band if w['cx'] < x0 - 20]
            right_words = [w for w in band if w['cx'] > x0 + 20]
            def side_team(ws):
                ws = sorted(ws, key=lambda x: (x['top'], x['left']))
                toks = []
                for w in ws:
                    tok = _clean(w['text']).strip('|-–')
                    low = _norm(tok)
                    if not tok or low in UI_NOISE or _is_odds_token(tok):
                        continue
                    if re.fullmatch(r'\d{1,2}:\d{2}', tok):
                        continue
                    if re.fullmatch(r'\d+(?:[./-]\d+)+', tok):
                        continue
                    toks.append(tok)
                val = _clean(' '.join(toks[:5])).strip(' -–|')
                return val if len(val) >= 2 else None
            h, a = side_team(left_words), side_team(right_words)
            if h and a:
                home, away = h, a
                break

    # Another common PSM 6 layout puts a countdown between the two team names.
    if not home or not away:
        for ln in lines:
            m = re.match(r'^(.*?)\s+(\d{1,2}:\d{2})\s+(.*?)$', ln['text'])
            if m:
                h = _clean(m.group(1)).strip(' -–|')
                a = _clean(m.group(3)).strip(' -–|')
                if len(h) >= 2 and len(a) >= 2 and _norm(h) not in NAV_TERMS and _norm(a) not in NAV_TERMS:
                    home, away = h, a
                    pre_signal = True
                    break

    # Fallback: line containing VS.
    if not home or not away:
        for ln in lines:
            if re.search(r'\bvs\b', ln['text'], re.I):
                parts = re.split(r'\bvs\b', ln['text'], maxsplit=1, flags=re.I)
                if len(parts) == 2:
                    h = _clean(parts[0]).strip(' -–|')
                    a = _clean(parts[1]).strip(' -–|')
                    if len(h) >= 2 and len(a) >= 2:
                        home, away = h, a
                        break

    # Prefer the highly reliable mobile layout line: HOME <countdown> AWAY.
    # It preserves team word order better than sparse PSM grouping.
    for ln in lines:
        m = re.match(r'^(.*?)\s+(\d{1,2}:\d{2})\s+(.*?)$', ln['text'])
        if not m:
            continue
        h = _clean(m.group(1)).strip(' -–|')
        a = _clean(m.group(3)).strip(' -–|')
        if len(h) >= 3 and len(a) >= 3 and not _is_odds_token(h) and not _is_odds_token(a):
            home, away = h, a
            pre_signal = True
            break

    match_type = 'pre_match' if pre_signal and not live_signal else ('live' if live_signal else 'unknown')
    return {
        'competition': competition,
        'match': {'home_team': home, 'away_team': away},
        'match_type': match_type,
        'start_date': start_date,
        'start_time': start_time,
        'live': {'is_live': match_type == 'live', 'minute': None, 'score': None},
    }


def _line_odds(line: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [w for w in line['words'] if _is_odds_token(w['text'])]


def _label_groups(line: Dict[str, Any], odds_xs: List[float]) -> List[str]:
    if not odds_xs:
        return []
    ws = [w for w in line['words'] if not _is_odds_token(w['text'])]
    if not ws:
        return []
    xs = sorted(odds_xs)
    bounds = [-10**9] + [(xs[i] + xs[i+1]) / 2 for i in range(len(xs)-1)] + [10**9]
    labels = []
    for i in range(len(xs)):
        toks = []
        for w in ws:
            if bounds[i] <= w['cx'] < bounds[i+1]:
                tok = _clean(w['text'])
                if tok and _norm(tok) not in NAV_TERMS:
                    toks.append(tok)
        labels.append(_clean(' '.join(toks)).strip(' -–|'))
    return labels


def _canonical_labels(header: str, count: int) -> List[str]:
    mapping = {
        '1X2': ['W1', 'X', 'W2'],
        'Double Chance': ['1X', '12', '2X'],
        'Team To Qualify For The Next Stage': ['Team 1', 'Team 2'],
        'Both Teams To Score': ['Yes', 'No'],
    }
    labels = mapping.get(header) or []
    return labels if len(labels) == count else []


def _extract_markets(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    headers: List[Tuple[int, str]] = []
    for i, ln in enumerate(lines):
        hdr = _header_name(ln['text'])
        if hdr:
            headers.append((i, hdr))
    if not headers:
        return []

    markets = []
    for pos, (idx, hdr) in enumerate(headers):
        end = headers[pos+1][0] if pos + 1 < len(headers) else len(lines)
        section = lines[idx+1:end]
        selections = []
        for j, ln in enumerate(section):
            odds_words = _line_odds(ln)
            if not odds_words:
                continue
            odds_words.sort(key=lambda x: x['cx'])
            odds_xs = [x['cx'] for x in odds_words]
            labels = _label_groups(ln, odds_xs)
            # Common 1xBet layout: labels are one row above odds.
            if not any(labels) and j > 0:
                labels = _label_groups(section[j-1], odds_xs)
            elif j > 0:
                prev = _label_groups(section[j-1], odds_xs)
                labels = [labels[k] or (prev[k] if k < len(prev) else '') for k in range(len(odds_words))]
            # Four common markets have a fixed left-to-right order in the 1xBet UI.
            # This is only used when OCR sees the exact odds count but misses tiny labels.
            if not any(labels):
                labels = _canonical_labels(hdr, len(odds_words))
            for k, ow in enumerate(odds_words):
                label = labels[k] if k < len(labels) else ''
                if not label:
                    continue
                low = _norm(label)
                if low in NAV_TERMS or len(low) > 80:
                    continue
                selections.append({'selection': label, 'odds': _odds_value(ow['text'])})
        # de-dup
        unique, seen = [], set()
        for s in selections:
            if s['odds'] is None:
                continue
            key = (_norm(s['selection']), round(float(s['odds']), 3))
            if key in seen:
                continue
            seen.add(key)
            unique.append(s)
        if unique:
            markets.append({'market_name': hdr, 'period': 'regular_time', 'selections': unique})
    return markets


def _single_extract(path: str) -> Dict[str, Any]:
    candidates = []
    for img in _preprocess(path):
        for psm in (6, 11):
            ws = _words(img, psm=psm)
            ls = _lines(ws)
            meta = _detect_meta(ls, ws)
            markets = _extract_markets(ls)
            row_count = sum(len(m.get('selections') or []) for m in markets)
            quality = len(markets) * 4 + row_count
            if (meta.get('match') or {}).get('home_team') and (meta.get('match') or {}).get('away_team'):
                quality += 8
            if meta.get('match_type') == 'pre_match':
                quality += 6
            candidates.append(({**meta, 'markets': markets, 'ocr_lines': [x['text'] for x in ls]}, quality))
    if not candidates:
        return {'match': {}, 'live': {'is_live': False}, 'markets': [], 'match_type': 'unknown'}

    best = max(candidates, key=lambda x: x[1])[0]
    # Metadata is sometimes clearest in PSM 11 while odds are clearest in PSM 6.
    # Merge only non-contradictory metadata across OCR passes.
    for cand, _ in sorted(candidates, key=lambda x: x[1], reverse=True):
        if not best.get('competition') and cand.get('competition'):
            best['competition'] = cand['competition']
        for k in ('home_team', 'away_team'):
            if not (best.get('match') or {}).get(k) and (cand.get('match') or {}).get(k):
                best.setdefault('match', {})[k] = cand['match'][k]
        if best.get('match_type') == 'unknown' and cand.get('match_type') == 'pre_match':
            best['match_type'] = 'pre_match'
            best['live'] = {'is_live': False, 'minute': None, 'score': None}
        if not best.get('start_date') and cand.get('start_date'):
            best['start_date'] = cand['start_date']
        if not best.get('start_time') and cand.get('start_time'):
            best['start_time'] = cand['start_time']
    return best


def _merge(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = {
        'sport': 'football', 'competition': None, 'round_or_group': None,
        'match': {'home_team': None, 'away_team': None}, 'match_type': 'unknown',
        'start_date': None, 'start_time': None,
        'live': {'is_live': False, 'minute': None, 'score': None},
        'markets': [], 'unreadable_items': [], 'vision_provider': 'local_ocr',
    }
    seen = set()
    for p in parts:
        if not out['competition'] and p.get('competition'):
            out['competition'] = p['competition']
        for k in ('home_team', 'away_team'):
            if not out['match'][k] and (p.get('match') or {}).get(k):
                out['match'][k] = p['match'][k]
        if p.get('match_type') == 'pre_match':
            out['match_type'] = 'pre_match'
        elif out['match_type'] == 'unknown' and p.get('match_type') == 'live':
            out['match_type'] = 'live'
        if not out['start_date'] and p.get('start_date'):
            out['start_date'] = p['start_date']
        if not out['start_time'] and p.get('start_time'):
            out['start_time'] = p['start_time']
        for m in p.get('markets') or []:
            sig = (m.get('market_name'), tuple((s.get('selection'), s.get('odds')) for s in m.get('selections') or []))
            if sig in seen:
                continue
            seen.add(sig)
            out['markets'].append(m)
    out['live']['is_live'] = out['match_type'] == 'live'
    return out


def _confidence(ex: Dict[str, Any]) -> float:
    score = 0.0
    mt = ex.get('match') or {}
    if mt.get('home_team') and mt.get('away_team'):
        score += 0.30
    if ex.get('match_type') == 'pre_match':
        score += 0.25
    if ex.get('competition'):
        score += 0.08
    markets = ex.get('markets') or []
    if markets:
        score += 0.15
    rows = sum(len(m.get('selections') or []) for m in markets)
    score += min(0.22, rows * 0.025)
    return round(min(1.0, score), 3)


def extract_prebet_local(paths: List[str]) -> Dict[str, Any]:
    ex = _merge([_single_extract(p) for p in list(paths or [])[:8]])
    ex['screenshots_merged'] = len(list(paths or [])[:8])
    ex['ocr_confidence'] = _confidence(ex)
    return ex


def local_prebet_good_enough(ex: Dict[str, Any], threshold: float = 0.72) -> bool:
    if not isinstance(ex, dict):
        return False
    mt = ex.get('match') or {}
    if ex.get('match_type') != 'pre_match':
        return False
    if not mt.get('home_team') or not mt.get('away_team'):
        return False
    markets = ex.get('markets') or []
    rows = sum(len(m.get('selections') or []) for m in markets)
    if len(markets) < 1 or rows < 2:
        return False
    return float(ex.get('ocr_confidence') or 0.0) >= float(threshold)
