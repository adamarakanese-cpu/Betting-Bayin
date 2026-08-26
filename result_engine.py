import hashlib
import re


def _norm(value):
    return " ".join(str(value or "").strip().lower().replace("−", "-").split())


def market_period(market_name):
    m = _norm(market_name)
    compact = re.sub(r"[^a-z0-9]+", "", m)
    if any(x in compact for x in ("1sthalf", "firsthalf", "1half", "half1")):
        return "1st_half"
    if any(x in compact for x in ("2ndhalf", "secondhalf", "2half", "half2")):
        return "2nd_half"
    return "regular_time"


def _strip_period(market_name):
    m = _norm(market_name)
    for pattern in (
        r"\bregular\s*time\b", r"\bfull\s*time\b", r"\b90\s*min(?:ute)?s?\b",
        r"\b1st\s*half\b", r"\bfirst\s*half\b",
        r"\b2nd\s*half\b", r"\bsecond\s*half\b",
    ):
        m = re.sub(pattern, " ", m)
    return " ".join(m.split()).strip(" -—:")



def market_family(market_name):
    m = _strip_period(market_name)
    compact = re.sub(r"[^a-z0-9]+", "", m)

    if (
        ("result" in compact or "1x2" in compact or "w1" in compact or "w2" in compact)
        and ("bothteamstoscore" in compact or "eachteamtoscore" in compact or "btts" in compact)
    ):
        return "result_btts"
    if "doublechance" in compact and (
        "bothteamstoscore" in compact or "eachteamtoscore" in compact or "btts" in compact
    ):
        return "double_chance_btts"
    if "doublechance" in compact and "total" in compact:
        return "double_chance_total"
    if (
        ("result" in compact or "1x2" in compact or "w1" in compact or "w2" in compact)
        and "total" in compact
    ):
        return "result_total"

    if "wintonil" in compact or "winnil" in compact:
        if any(x in compact for x in ("team1", "home")):
            return "home_win_to_nil"
        if any(x in compact for x in ("team2", "away")):
            return "away_win_to_nil"
        return "any_team_win_to_nil"

    if "eachteamtoscore" in compact:
        return "each_team_score_n"
    if "handicap" in compact:
        return "handicap"
    if "drawnobet" in compact or compact == "dnb":
        return "draw_no_bet"

    if compact in {"1x2", "result", "matchresult", "fulltimeresult", "regularresult"}:
        return "1x2"
    if "doublechance" in compact:
        return "double_chance"
    if compact in {"btts", "bothteamstoscore", "bothteamsscore"} or "bothteamstoscore" in compact:
        return "btts"
    if "correctscore" in compact:
        return "correct_score"

    if "total" in compact and any(x in compact for x in ("team1", "hometeam", "hometotal")):
        return "home_team_total"
    if "total" in compact and any(x in compact for x in ("team2", "awayteam", "awaytotal")):
        return "away_team_total"
    if "total" in compact and "team" not in compact:
        return "total"

    if ("team1" in compact or "home" in compact) and "cleansheet" in compact:
        return "home_clean_sheet"
    if ("team2" in compact or "away" in compact) and "cleansheet" in compact:
        return "away_clean_sheet"
    if ("team1" in compact or "home" in compact) and "toscore" in compact:
        return "home_team_to_score"
    if ("team2" in compact or "away" in compact) and "toscore" in compact:
        return "away_team_to_score"
    if "atleastoneteam" in compact and "score" in compact:
        return "at_least_one_team_scores"
    if "odd" in compact and "even" in compact:
        return "total_odd_even"
    if "qualif" in compact or "nextstage" in compact:
        return "team_to_qualify"
    return compact or "unknown"


def canonical_selection(market_name, selection):
    fam = market_family(market_name)
    raw = _norm(selection)
    s = re.sub(r"[^a-z0-9.+-]+", "", raw)

    if fam == "double_chance":
        if s in {"x2", "2x"}: return "2x"
        if s in {"x1", "1x"}: return "1x"
        if s in {"12", "21"}: return "12"

    if fam in {"1x2", "draw_no_bet"}:
        aliases = {
            "1": "home", "w1": "home", "home": "home", "homewin": "home", "team1": "home",
            "x": "draw", "draw": "draw",
            "2": "away", "w2": "away", "away": "away", "awaywin": "away", "team2": "away",
        }
        return aliases.get(s, s)

    if fam in {
        "btts", "home_clean_sheet", "away_clean_sheet", "at_least_one_team_scores",
        "home_team_to_score", "away_team_to_score", "any_team_win_to_nil",
        "home_win_to_nil", "away_win_to_nil", "each_team_score_n",
    }:
        if s in {"yes", "y"}: return "yes"
        if s in {"no", "n"}: return "no"

    return raw

def calibration_key(market_name, selection):
    period = market_period(market_name)
    fam = market_family(market_name)
    sel = canonical_selection(market_name, selection)
    prefix = f"{period}:"
    if fam in {"total", "home_team_total", "away_team_total"}:
        direction = "over" if "over" in sel else ("under" if "under" in sel else "other")
        return f"{prefix}{fam}:{direction}"
    if fam in {"1x2", "double_chance", "btts", "home_clean_sheet", "away_clean_sheet", "at_least_one_team_scores"}:
        return f"{prefix}{fam}:{sel}"
    if fam == "correct_score":
        return f"{prefix}{fam}"
    return f"{prefix}{fam}"

def build_prediction_key(home_team, away_team, competition, match_date, market_name, selection):
    raw = "|".join([
        _norm(home_team), _norm(away_team), _norm(competition), _norm(match_date),
        market_period(market_name), market_family(market_name), canonical_selection(market_name, selection),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_line(selection):
    match = re.search(r"(\d+(?:\.\d+)?)", str(selection or ""))
    return float(match.group(1)) if match else None


def _over_under_result(value, line, is_over):
    if line is None:
        return None
    if abs(value - line) < 1e-9:
        return "void"
    if is_over:
        return "win" if value > line else "loss"
    return "win" if value < line else "loss"



def _extract_yes_no(text):
    tokens = re.findall(r"\b(yes|no|y|n)\b", _norm(text))
    if not tokens:
        return None
    return "yes" if tokens[-1] in {"yes", "y"} else "no"


def _extract_outcome(text):
    t = _norm(text)
    if re.search(r"\bw1\b|\bhome(?:\s*win)?\b|\bteam\s*1\b", t):
        return "home"
    if re.search(r"\bw2\b|\baway(?:\s*win)?\b|\bteam\s*2\b", t):
        return "away"
    if re.search(r"\bdraw\b|\bx\b", t):
        return "draw"
    if t.strip() == "1": return "home"
    if t.strip() == "2": return "away"
    return None


def _extract_dc(text):
    compact = re.sub(r"[^a-z0-9]+", "", _norm(text))
    if "1x" in compact or "x1" in compact: return "1x"
    if "2x" in compact or "x2" in compact: return "2x"
    if re.search(r"(^|[^0-9])12([^0-9]|$)", _norm(text)): return "12"
    return None


def _extract_ou(text):
    t = _norm(text)
    m = re.search(r"\b(over|under|o|u)\b[^0-9]*([0-9]+(?:\.[0-9]+)?)", t)
    if not m:
        m = re.search(r"(over|under|o|u)[^0-9]*([0-9]+(?:\.[0-9]+)?)", t)
    if not m:
        return None, None
    return ("over" if m.group(1) in {"over", "o"} else "under"), float(m.group(2))


def _extract_handicap(selection, market_name=""):
    text = f"{_norm(selection)} {_norm(market_name)}"
    side = None
    if re.search(r"\bw1\b|\bhome\b|\bteam\s*1\b|(?:^|\s)1\s*\(", text):
        side = "home"
    elif re.search(r"\bw2\b|\baway\b|\bteam\s*2\b|(?:^|\s)2\s*\(", text):
        side = "away"
    m = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", text)
    if not m:
        m = re.search(r"(?<![\d.])([+-]\d+(?:\.\d+)?)", text)
    if side is None or not m:
        return None, None
    return side, float(m.group(1))


def _each_team_threshold(market_name, selection):
    text = f"{_norm(market_name)} {_norm(selection)}"
    m = re.search(r"each\s*team\s*to\s*score[^0-9]*([0-9]+)", text)
    if not m:
        m = re.search(r"([0-9]+)\s*(?:or\s*more|\+)", text)
    return int(m.group(1)) if m else 2


def settle_market(market_name, selection, home_score, away_score):
    """Settle regular-time score-defined V19.5 football markets.

    Half markets remain unresolved because a final 90-minute score cannot settle
    a 1st/2nd-half bet safely. Team-to-qualify also remains unresolved because
    aggregate score, extra time or penalties may be required.
    """
    if market_period(market_name) != "regular_time":
        return None

    try:
        h = int(home_score)
        a = int(away_score)
    except (TypeError, ValueError):
        return None

    fam = market_family(market_name)
    sel = canonical_selection(market_name, selection)
    raw = str(selection or "")
    joined = f"{market_name} {raw}"
    total = h + a

    if fam == "1x2":
        outcome = "home" if h > a else ("away" if a > h else "draw")
        return "win" if sel == outcome else "loss"

    if fam == "double_chance":
        if sel == "1x": return "win" if h >= a else "loss"
        if sel == "12": return "win" if h != a else "loss"
        if sel == "2x": return "win" if a >= h else "loss"
        return None

    if fam == "draw_no_bet":
        outcome = _extract_outcome(raw)
        if outcome == "home":
            return "win" if h > a else ("void" if h == a else "loss")
        if outcome == "away":
            return "win" if a > h else ("void" if h == a else "loss")
        return None

    if fam == "btts":
        happened = h > 0 and a > 0
        if sel == "yes": return "win" if happened else "loss"
        if sel == "no": return "loss" if happened else "win"
        return None

    if fam == "each_team_score_n":
        yn = _extract_yes_no(raw)
        if yn is None: return None
        n = _each_team_threshold(market_name, selection)
        happened = h >= n and a >= n
        return "win" if happened == (yn == "yes") else "loss"

    if fam in {"total", "home_team_total", "away_team_total"}:
        line = _parse_line(selection)
        value = total if fam == "total" else (h if fam == "home_team_total" else a)
        if "over" in _norm(selection): return _over_under_result(value, line, True)
        if "under" in _norm(selection): return _over_under_result(value, line, False)
        return None

    if fam == "handicap":
        side, line = _extract_handicap(raw, market_name)
        if side is None or line is None:
            return None
        adjusted = (h + line - a) if side == "home" else (a + line - h)
        if abs(adjusted) < 1e-9: return "void"
        return "win" if adjusted > 0 else "loss"

    if fam in {"home_team_to_score", "away_team_to_score"}:
        yn = _extract_yes_no(raw)
        if yn is None: return None
        happened = h > 0 if fam.startswith("home") else a > 0
        return "win" if happened == (yn == "yes") else "loss"

    if fam == "home_clean_sheet":
        happened = a == 0
        yn = _extract_yes_no(raw)
        if yn is None: return None
        return "win" if happened == (yn == "yes") else "loss"

    if fam == "away_clean_sheet":
        happened = h == 0
        yn = _extract_yes_no(raw)
        if yn is None: return None
        return "win" if happened == (yn == "yes") else "loss"

    if fam == "at_least_one_team_scores":
        happened = total > 0
        yn = _extract_yes_no(raw)
        if yn is None: return None
        return "win" if happened == (yn == "yes") else "loss"

    if fam in {"any_team_win_to_nil", "home_win_to_nil", "away_win_to_nil"}:
        yn = _extract_yes_no(raw) or "yes"
        specific = _extract_outcome(raw)
        if fam == "home_win_to_nil" or (fam == "any_team_win_to_nil" and specific == "home"):
            happened = h > a and a == 0
        elif fam == "away_win_to_nil" or (fam == "any_team_win_to_nil" and specific == "away"):
            happened = a > h and h == 0
        else:
            happened = (h > a and a == 0) or (a > h and h == 0)
        return "win" if happened == (yn == "yes") else "loss"

    if fam == "result_btts":
        outcome = _extract_outcome(raw) or _extract_outcome(market_name)
        yn = _extract_yes_no(raw)
        if not outcome or yn is None: return None
        actual = "home" if h > a else ("away" if a > h else "draw")
        happened = (actual == outcome) and ((h > 0 and a > 0) == (yn == "yes"))
        return "win" if happened else "loss"

    if fam == "double_chance_btts":
        dc = _extract_dc(raw)
        yn = _extract_yes_no(raw)
        if not dc or yn is None: return None
        dc_ok = (h >= a if dc == "1x" else (h != a if dc == "12" else a >= h))
        happened = dc_ok and ((h > 0 and a > 0) == (yn == "yes"))
        return "win" if happened else "loss"

    if fam in {"result_total", "double_chance_total"}:
        side, line = _extract_ou(raw)
        if side is None or line is None: return None
        total_ok = total > line if side == "over" else total < line

        if fam == "result_total":
            outcome = _extract_outcome(raw) or _extract_outcome(market_name)
            if not outcome: return None
            actual = "home" if h > a else ("away" if a > h else "draw")
            result_ok = actual == outcome
        else:
            dc = _extract_dc(raw)
            if not dc: return None
            result_ok = (h >= a if dc == "1x" else (h != a if dc == "12" else a >= h))
        return "win" if result_ok and total_ok else "loss"

    if fam == "total_odd_even":
        s = _norm(raw)
        if "odd" in s: return "win" if total % 2 == 1 else "loss"
        if "even" in s: return "win" if total % 2 == 0 else "loss"
        return None

    if fam == "correct_score":
        match = re.search(r"(\d+)\D+(\d+)", raw)
        if not match: return None
        ph, pa = int(match.group(1)), int(match.group(2))
        return "win" if (h, a) == (ph, pa) else "loss"

    # Qualification/next-stage markets need aggregate/ET/penalty context.
    return None

