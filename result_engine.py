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
    compact = re.sub(r"[\s_-]+", "", m)
    if compact in {"1x2", "matchresult", "fulltimeresult", "regularresult"}:
        return "1x2"
    if "doublechance" in compact and "bothteam" not in compact:
        return "double_chance"
    if compact in {"btts", "bothteamstoscore", "bothteamsscore"} or "bothteamstoscore" in compact:
        return "btts"
    if "correct" in m and "score" in m:
        return "correct_score"
    if "home" in m and "clean" in m and "sheet" in m:
        return "home_clean_sheet"
    if "away" in m and "clean" in m and "sheet" in m:
        return "away_clean_sheet"
    if "home" in m and "team" in m and "total" in m:
        return "home_team_total"
    if "away" in m and "team" in m and "total" in m:
        return "away_team_total"
    if "at least one team" in m and "score" in m:
        return "at_least_one_team_scores"
    if "total" in m and "team" not in m:
        return "total"
    return compact or "unknown"


def canonical_selection(market_name, selection):
    fam = market_family(market_name)
    s = _norm(selection).replace(" ", "")
    if fam == "double_chance":
        if s in {"x2", "2x"}:
            return "2x"
        if s in {"x1", "1x"}:
            return "1x"
        if s in {"12", "21"}:
            return "12"
    if fam == "1x2":
        aliases = {
            "1": "home", "w1": "home", "home": "home", "homewin": "home",
            "x": "draw", "draw": "draw",
            "2": "away", "w2": "away", "away": "away", "awaywin": "away",
        }
        return aliases.get(s, s)
    if fam in {"btts", "home_clean_sheet", "away_clean_sheet", "at_least_one_team_scores"}:
        if s in {"yes", "y"}: return "yes"
        if s in {"no", "n"}: return "no"
    return s


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


def settle_market(market_name, selection, home_score, away_score):
    """Settle supported regular-time football markets from a final score.

    Returns win/loss/void, or None when the market needs data beyond the final score.
    """
    # Final-score settlement is valid only for Regular Time markets. Half-market
    # tips must not contaminate learning with a full-time score. They remain
    # unresolved unless manually settled with the correct period result.
    if market_period(market_name) != "regular_time":
        return None

    try:
        h = int(home_score)
        a = int(away_score)
    except (TypeError, ValueError):
        return None

    fam = market_family(market_name)
    sel = canonical_selection(market_name, selection)
    total = h + a

    if fam == "1x2":
        outcome = "home" if h > a else ("away" if a > h else "draw")
        return "win" if sel == outcome else "loss"

    if fam == "double_chance":
        if sel == "1x": return "win" if h >= a else "loss"
        if sel == "12": return "win" if h != a else "loss"
        if sel == "2x": return "win" if a >= h else "loss"
        return None

    if fam == "btts":
        happened = h > 0 and a > 0
        if sel == "yes": return "win" if happened else "loss"
        if sel == "no": return "loss" if happened else "win"
        return None

    if fam == "total":
        line = _parse_line(selection)
        if "over" in _norm(selection): return _over_under_result(total, line, True)
        if "under" in _norm(selection): return _over_under_result(total, line, False)
        return None

    if fam == "home_team_total":
        line = _parse_line(selection)
        if "over" in _norm(selection): return _over_under_result(h, line, True)
        if "under" in _norm(selection): return _over_under_result(h, line, False)
        return None

    if fam == "away_team_total":
        line = _parse_line(selection)
        if "over" in _norm(selection): return _over_under_result(a, line, True)
        if "under" in _norm(selection): return _over_under_result(a, line, False)
        return None

    if fam == "home_clean_sheet":
        happened = a == 0
        if sel == "yes": return "win" if happened else "loss"
        if sel == "no": return "loss" if happened else "win"
        return None

    if fam == "away_clean_sheet":
        happened = h == 0
        if sel == "yes": return "win" if happened else "loss"
        if sel == "no": return "loss" if happened else "win"
        return None

    if fam == "at_least_one_team_scores":
        happened = total > 0
        if sel == "yes": return "win" if happened else "loss"
        if sel == "no": return "loss" if happened else "win"
        return None

    if fam == "correct_score":
        match = re.search(r"(\d+)\D+(\d+)", str(selection or ""))
        if not match:
            return None
        ph, pa = int(match.group(1)), int(match.group(2))
        return "win" if (h, a) == (ph, pa) else "loss"

    return None
