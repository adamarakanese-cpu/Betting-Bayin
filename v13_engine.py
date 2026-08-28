import math
import re
from deepseek_verifier import verify_model_context
from performance_engine import apply_performance_feedback
from intelligence_engine import apply_contextual_learning, apply_selection_intelligence, no_bet_gate

V13_VERSION = "V20.1"


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _norm(s):
    return str(s or "").strip().lower().replace("−", "-")


def _canonical_period(value=None, market_name=None):
    text = f"{_norm(value)} {_norm(market_name)}"
    compact = "".join(ch for ch in text if ch.isalnum())
    if any(token in compact for token in ("1sthalf", "firsthalf", "1half", "half1")):
        return "1st_half"
    if any(token in compact for token in ("2ndhalf", "secondhalf", "2half", "half2")):
        return "2nd_half"
    raw = _norm(value)
    if raw in {"1st_half", "first_half"}:
        return "1st_half"
    if raw in {"2nd_half", "second_half"}:
        return "2nd_half"
    return "regular_time"


def _period_label(period):
    period = _canonical_period(period)
    if period == "1st_half":
        return "1st Half"
    if period == "2nd_half":
        return "2nd Half"
    return "Regular Time"


def _strip_period_display(market_name):
    import re
    text = str(market_name or "").strip().replace("−", "-")
    for pattern in (
        r"\bregular\s*time\b", r"\bfull\s*time\b", r"\b90\s*min(?:ute)?s?\b",
        r"\b1st\s*half\b", r"\bfirst\s*half\b",
        r"\b2nd\s*half\b", r"\bsecond\s*half\b",
    ):
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip(" -—:")


def _strip_period(market_name):
    return _norm(_strip_period_display(market_name))


def _scoped_market_name(market_name, period):
    base = _strip_period_display(market_name) or str(market_name or "Market").strip()
    return f"{_period_label(period)} {base}".strip()



def _canonical_market(market_name):
    """Normalize a broad set of 1XBET football market families.

    V19.5 deliberately recognizes combo/handicap/team markets before generic
    totals so they are not collapsed into the familiar 1X2/Total/BTTS buckets.
    """
    m = _strip_period(market_name)
    compact = re.sub(r"[^a-z0-9]+", "", m)

    # Combination markets first.
    if (
        ("result" in compact or "1x2" in compact or "w1" in compact or "w2" in compact)
        and ("bothteamstoscore" in compact or "eachteamtoscore" in compact or "btts" in compact)
    ):
        return "result+btts"
    if "doublechance" in compact and (
        "bothteamstoscore" in compact or "eachteamtoscore" in compact or "btts" in compact
    ):
        return "double chance+btts"
    if "doublechance" in compact and "total" in compact:
        return "double chance+total"
    if (
        ("result" in compact or "1x2" in compact or "w1" in compact or "w2" in compact)
        and "total" in compact
    ):
        return "result+total"

    if "wintonil" in compact or "winnil" in compact:
        if any(x in compact for x in ("team1", "home")):
            return "home win to nil"
        if any(x in compact for x in ("team2", "away")):
            return "away win to nil"
        return "any team win to nil"

    if "eachteamtoscore" in compact:
        return "each team to score n+"

    if "handicap" in compact or "asianhandicap" in compact:
        return "handicap"
    if "drawnobet" in compact or compact == "dnb":
        return "draw no bet"

    if compact in {"1x2", "result", "matchresult", "fulltimeresult", "regularresult"}:
        return "1x2"
    if "doublechance" in compact:
        return "double chance"
    if compact in {"btts", "bothteamstoscore", "bothteamscore"} or "bothteamstoscore" in compact:
        return "btts"

    # Team aliases: 1XBET often uses Team 1 / Team 2 rather than Home / Away.
    if "total" in compact and any(x in compact for x in ("team1", "hometeam", "hometotal")):
        return "home team total"
    if "total" in compact and any(x in compact for x in ("team2", "awayteam", "awaytotal")):
        return "away team total"
    if "total" in compact and "team" not in compact:
        return "total"

    if ("team1" in compact or "home" in compact) and "cleansheet" in compact:
        return "home clean sheet"
    if ("team2" in compact or "away" in compact) and "cleansheet" in compact:
        return "away clean sheet"
    if ("team1" in compact or "home" in compact) and "toscore" in compact:
        return "home team to score"
    if ("team2" in compact or "away" in compact) and "toscore" in compact:
        return "away team to score"

    if "odd" in compact and "even" in compact:
        return "total odd/even"
    if "correctscore" in compact:
        return "correct score"
    if "qualif" in compact or "nextstage" in compact:
        return "team to qualify"
    return m


def _canonical_selection(market_name, selection):
    """Normalize common bookmaker aliases without destroying combo wording."""
    m = _strip_period(market_name)
    family = _canonical_market(market_name)
    raw = _norm(selection)
    s = re.sub(r"\s+", "", raw)

    if family in {"double chance", "double chance+btts", "double chance+total"}:
        # Keep the rest of combo text intact; exact DC token is parsed later.
        if family == "double chance":
            compact = re.sub(r"[^a-z0-9]+", "", s)
            if compact in {"x2", "2x"}: return "2x"
            if compact in {"1x", "x1"}: return "1x"
            if compact in {"12", "21"}: return "12"

    if family in {"1x2", "draw no bet"}:
        compact = re.sub(r"[^a-z0-9]+", "", s)
        aliases = {
            "1": "w1", "w1": "w1", "home": "w1", "homewin": "w1", "team1": "w1",
            "x": "draw", "draw": "draw",
            "2": "w2", "w2": "w2", "away": "w2", "awaywin": "w2", "team2": "w2",
        }
        return aliases.get(compact, compact)

    if family in {"total", "home team total", "away team total"}:
        match = re.search(r"\b(over|under|o|u)\b[^0-9]*([0-9]+(?:\.[0-9]+)?)", raw)
        if not match:
            match = re.search(r"(over|under|o|u)[^0-9]*([0-9]+(?:\.[0-9]+)?)", raw)
        if match:
            side = "over" if match.group(1) in {"over", "o"} else "under"
            return f"{side}{match.group(2)}"

    if family in {
        "btts", "home clean sheet", "away clean sheet",
        "home team to score", "away team to score",
        "any team win to nil", "home win to nil", "away win to nil",
        "each team to score n+",
    }:
        compact = re.sub(r"[^a-z0-9]+", "", raw)
        if compact in {"yes", "y"}: return "yes"
        if compact in {"no", "n"}: return "no"

    return raw

def _market_key(market_name, selection, period=None):
    # Period is part of identity: Regular Time Over 1.5 is NOT 1st Half Over 1.5.
    return (
        _canonical_period(period, market_name),
        _canonical_market(market_name),
        _canonical_selection(market_name, selection),
    )


def _display_selection(market_name, selection):
    raw = str(selection or "").strip()
    if "doublechance" in _norm(market_name).replace(" ", ""):
        canon = _canonical_selection(market_name, selection)
        if canon == "1x":
            return "1X"
        if canon == "12":
            return "12"
        if canon == "2x":
            return "2X"
    return raw


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(v)))


def _no_vig(items):
    vals = []
    for item in items:
        odds = _f(item.get("odds"))
        if odds and odds > 1:
            vals.append((item, 1.0 / odds))
    total = sum(x[1] for x in vals)
    if len(vals) < 2 or total <= 0:
        return {}
    return {id(item): raw / total for item, raw in vals}


def _model_probability(market_name, selection, calibration):
    m, s = _norm(market_name), _norm(selection)
    one = calibration.get("one_x_two", {}).get("calibrated", {})
    binary = calibration.get("binary_markets", {})

    if m == "1x2":
        if s in {"w1", "1", "home", "home win"}: return one.get("home_win")
        if s in {"x", "draw"}: return one.get("draw")
        if s in {"w2", "2", "away", "away win"}: return one.get("away_win")

    if "double chance" in m and "both teams" not in m:
        h, d, a = one.get("home_win"), one.get("draw"), one.get("away_win")
        if None not in (h, d, a):
            if s == "1x": return h + d
            if s in {"x2", "2x"}: return d + a
            if s == "12": return h + a

    if "both teams to score" in m or m == "btts":
        btts = binary.get("btts", {})
        if s in {"yes", "y"}: return btts.get("yes")
        if s in {"no", "n"}: return btts.get("no")

    if "total" in m and "team" not in m:
        totals = binary.get("totals", {})
        for line in (1.5, 2.5, 3.5):
            token = str(line)
            if token in s:
                if "over" in s or s.startswith("o"): return totals.get(f"over_{str(line).replace('.', '_')}")
                if "under" in s or s.startswith("u"): return totals.get(f"under_{str(line).replace('.', '_')}")
    return None


def _poisson_probs(lam, max_goals=9):
    lam = max(0.01, float(lam))
    vals = []
    for k in range(max_goals + 1):
        vals.append(math.exp(-lam) * (lam ** k) / math.factorial(k))
    # Tail mass is tiny for normal football lambdas; normalize defensively.
    total = sum(vals) or 1.0
    return [v / total for v in vals]


def _total_goal_distribution(probability, period="regular_time"):
    expected = (probability or {}).get("expected_goals", {}) or {}
    home_xg = _f(expected.get("home_xg"))
    away_xg = _f(expected.get("away_xg"))
    if home_xg is None or away_xg is None:
        return None
    period = _canonical_period(period)
    share = 1.0 if period == "regular_time" else (0.44 if period == "1st_half" else 0.56)
    lam = max(0.02, (home_xg + away_xg) * share)
    return _poisson_probs(lam, max_goals=10)


def _asian_total_components(probability, line, side="under", period="regular_time"):
    """Return win/push/loss for integer Asian totals such as Under (3)."""
    try:
        line = float(line)
    except (TypeError, ValueError):
        return None
    if abs(line - round(line)) > 1e-9:
        return None
    dist = _total_goal_distribution(probability, period)
    if not dist:
        return None
    target = int(round(line))
    push = dist[target] if 0 <= target < len(dist) else 0.0
    if str(side).lower().startswith("under"):
        win = sum(dist[:max(0, target)])
    else:
        win = sum(dist[target + 1:]) if target + 1 < len(dist) else 0.0
    win = _clamp(win, 0.001, 0.998)
    push = _clamp(push, 0.0, 0.95)
    loss = _clamp(1.0 - win - push, 0.0, 0.999)
    return {"win": win, "push": push, "loss": loss}



def _integer_total_push_probability(market_name, selection, period, probability):
    components = _score_market_components(market_name, selection, period, probability)
    if not components:
        return 0.0
    return float(components.get("push_probability") or 0.0)

def _score_grid(probability, period="regular_time", max_goals=10):
    """Independent-Poisson score grid used for visible specialist markets."""
    expected = (probability or {}).get("expected_goals", {}) or {}
    home_xg = _f(expected.get("home_xg"))
    away_xg = _f(expected.get("away_xg"))
    if home_xg is None or away_xg is None:
        return None

    period = _canonical_period(period)
    share = 1.0 if period == "regular_time" else (0.44 if period == "1st_half" else 0.56)
    h_probs = _poisson_probs(max(0.02, home_xg * share), max_goals=max_goals)
    a_probs = _poisson_probs(max(0.02, away_xg * share), max_goals=max_goals)
    return [(h, a, hp * ap) for h, hp in enumerate(h_probs) for a, ap in enumerate(a_probs)]


def _extract_ou(text):
    text = _norm(text)
    match = re.search(r"\b(over|under|o|u)\b[^0-9]*([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        match = re.search(r"(over|under|o|u)[^0-9]*([0-9]+(?:\.[0-9]+)?)", text)
    if not match:
        return None, None
    side = "over" if match.group(1) in {"over", "o"} else "under"
    return side, float(match.group(2))


def _extract_yes_no(text):
    tokens = re.findall(r"\b(yes|no|y|n)\b", _norm(text))
    if not tokens:
        return None
    token = tokens[-1]
    return "yes" if token in {"yes", "y"} else "no"


def _extract_outcome(text, allow_bare=True):
    t = _norm(text)
    compact = re.sub(r"[^a-z0-9]+", " ", t)

    if re.search(r"\bw1\b|\bhome(?:\s*win)?\b|\bteam\s*1\b", compact):
        return "home"
    if re.search(r"\bw2\b|\baway(?:\s*win)?\b|\bteam\s*2\b", compact):
        return "away"
    if re.search(r"\bdraw\b", compact):
        return "draw"

    if allow_bare:
        stripped = compact.strip()
        if stripped in {"1", "home"}:
            return "home"
        if stripped in {"2", "away"}:
            return "away"
        if stripped in {"x", "draw"}:
            return "draw"
        # In combo strings a standalone result token may be separated by words.
        if re.search(r"(?<![\d.])\b1\b(?![\d.])", t):
            return "home"
        if re.search(r"(?<![\d.])\b2\b(?![\d.])", t):
            return "away"
        if re.search(r"\bx\b", t):
            return "draw"
    return None


def _extract_double_chance(text):
    compact = re.sub(r"[^a-z0-9]+", "", _norm(text))
    if "1x" in compact or "x1" in compact:
        return "1x"
    if "2x" in compact or "x2" in compact:
        return "2x"
    # Avoid reading total line digits as "12".
    if re.search(r"(^|[^0-9])12([^0-9]|$)", _norm(text)):
        return "12"
    return None


def _extract_handicap(selection, market_name=""):
    """Return (side, line) for common W1(-1), Team 2 (+0.5), Home -1 forms."""
    text = f"{_norm(selection)} {_norm(market_name)}"
    side = None
    if re.search(r"\bw1\b|\bhome\b|\bteam\s*1\b|(?:^|\s)1\s*\(", text):
        side = "home"
    elif re.search(r"\bw2\b|\baway\b|\bteam\s*2\b|(?:^|\s)2\s*\(", text):
        side = "away"

    # Prefer signed number inside parentheses.
    m = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", text)
    if not m:
        m = re.search(r"(?<![\d.])([+-]\d+(?:\.\d+)?)", text)
    if not m:
        # Zero handicap/DNB is valid even when rendered as (0).
        m = re.search(r"\(\s*(0(?:\.0+)?)\s*\)", text)
    if side is None or not m:
        return None, None
    return side, float(m.group(1))


def _each_team_threshold(market_name, selection):
    text = f"{_norm(market_name)} {_norm(selection)}"
    # "Each Team To Score (2) Or More" / "Each Team To Score 2+".
    m = re.search(r"each\s*team\s*to\s*score[^0-9]*([0-9]+)", text)
    if not m:
        m = re.search(r"([0-9]+)\s*(?:or\s*more|\+)", text)
    return int(m.group(1)) if m else 2


def _score_market_components(market_name, selection, period, probability):
    """Return {'probability','push_probability'} for score-derived visible markets.

    This is the core V19.5 market-coverage layer. It models the actual event
    described by the bookmaker selection instead of falling back to whichever
    familiar family the old engine already understood.
    """
    grid = _score_grid(probability, period)
    if not grid:
        return None

    family = _canonical_market(market_name)
    raw_sel = str(selection or "")
    joined = f"{market_name} {raw_sel}"
    canon_sel = _canonical_selection(market_name, selection)

    def aggregate(status_fn):
        win = push = 0.0
        for h, a, mass in grid:
            status = status_fn(h, a)
            if status == "win":
                win += mass
            elif status == "push":
                push += mass
        return {
            "probability": _clamp(win, 0.001, 0.998),
            "push_probability": _clamp(push, 0.0, 0.95),
        }

    def result_status(h, a, outcome):
        actual = "home" if h > a else ("away" if a > h else "draw")
        return actual == outcome

    if family == "1x2":
        outcome = _extract_outcome(raw_sel)
        if not outcome:
            return None
        return aggregate(lambda h, a: "win" if result_status(h, a, outcome) else "loss")

    if family == "double chance":
        dc = _canonical_selection(market_name, selection)
        if dc == "1x":
            return aggregate(lambda h, a: "win" if h >= a else "loss")
        if dc == "12":
            return aggregate(lambda h, a: "win" if h != a else "loss")
        if dc == "2x":
            return aggregate(lambda h, a: "win" if a >= h else "loss")
        return None

    if family == "draw no bet":
        outcome = _extract_outcome(raw_sel)
        if outcome not in {"home", "away"}:
            return None
        if outcome == "home":
            return aggregate(lambda h, a: "win" if h > a else ("push" if h == a else "loss"))
        return aggregate(lambda h, a: "win" if a > h else ("push" if h == a else "loss"))

    if family in {"total", "home team total", "away team total"}:
        side, line = _extract_ou(raw_sel)
        if side is None or line is None:
            return None

        def total_status(h, a):
            value = h + a if family == "total" else (h if family == "home team total" else a)
            diff = value - line
            if abs(diff) < 1e-9:
                return "push"
            won = diff > 0 if side == "over" else diff < 0
            return "win" if won else "loss"

        return aggregate(total_status)

    if family == "btts":
        yn = _extract_yes_no(raw_sel)
        if yn is None:
            return None
        return aggregate(
            lambda h, a: "win"
            if ((h > 0 and a > 0) == (yn == "yes"))
            else "loss"
        )

    if family == "each team to score n+":
        yn = _extract_yes_no(raw_sel)
        if yn is None:
            return None
        threshold = _each_team_threshold(market_name, selection)
        return aggregate(
            lambda h, a: "win"
            if ((h >= threshold and a >= threshold) == (yn == "yes"))
            else "loss"
        )

    if family in {"home team to score", "away team to score"}:
        yn = _extract_yes_no(raw_sel)
        if yn is None:
            return None
        is_home = family.startswith("home")
        return aggregate(
            lambda h, a: "win"
            if (((h > 0) if is_home else (a > 0)) == (yn == "yes"))
            else "loss"
        )

    if family in {"home clean sheet", "away clean sheet"}:
        yn = _extract_yes_no(raw_sel)
        if yn is None:
            return None
        is_home = family.startswith("home")
        return aggregate(
            lambda h, a: "win"
            if (((a == 0) if is_home else (h == 0)) == (yn == "yes"))
            else "loss"
        )

    if family in {"any team win to nil", "home win to nil", "away win to nil"}:
        yn = _extract_yes_no(raw_sel)
        if yn is None:
            # Some books label team-specific selection itself rather than Yes/No.
            yn = "yes"

        specific = _extract_outcome(raw_sel)
        def happened(h, a):
            if family == "home win to nil" or (family == "any team win to nil" and specific == "home"):
                return h > a and a == 0
            if family == "away win to nil" or (family == "any team win to nil" and specific == "away"):
                return a > h and h == 0
            return (h > a and a == 0) or (a > h and h == 0)

        return aggregate(lambda h, a: "win" if (happened(h, a) == (yn == "yes")) else "loss")

    if family == "handicap":
        side, line = _extract_handicap(raw_sel, market_name)
        if side is None or line is None:
            return None

        def handicap_status(h, a):
            adjusted = (h + line - a) if side == "home" else (a + line - h)
            if abs(adjusted) < 1e-9:
                return "push"
            return "win" if adjusted > 0 else "loss"

        return aggregate(handicap_status)

    if family == "result+btts":
        outcome = _extract_outcome(raw_sel) or _extract_outcome(market_name)
        yn = _extract_yes_no(raw_sel)
        if not outcome or yn is None:
            return None
        return aggregate(
            lambda h, a: "win"
            if (result_status(h, a, outcome) and ((h > 0 and a > 0) == (yn == "yes")))
            else "loss"
        )

    if family == "double chance+btts":
        dc = _extract_double_chance(raw_sel)
        yn = _extract_yes_no(raw_sel)
        if not dc or yn is None:
            return None

        def dc_ok(h, a):
            if dc == "1x": return h >= a
            if dc == "12": return h != a
            if dc == "2x": return a >= h
            return False

        return aggregate(
            lambda h, a: "win"
            if (dc_ok(h, a) and ((h > 0 and a > 0) == (yn == "yes")))
            else "loss"
        )

    if family in {"result+total", "double chance+total"}:
        side, line = _extract_ou(raw_sel)
        if side is None or line is None:
            return None

        if family == "result+total":
            outcome = _extract_outcome(raw_sel) or _extract_outcome(market_name)
            if not outcome:
                return None

            def result_part(h, a):
                return result_status(h, a, outcome)
        else:
            dc = _extract_double_chance(raw_sel)
            if not dc:
                return None

            def result_part(h, a):
                if dc == "1x": return h >= a
                if dc == "12": return h != a
                if dc == "2x": return a >= h
                return False

        def combo_status(h, a):
            value = h + a
            total_ok = value > line if side == "over" else value < line
            # Combo-market settlement varies for integer lines; do not credit a
            # synthetic push here. A line equality is treated conservatively.
            return "win" if (result_part(h, a) and total_ok) else "loss"

        return aggregate(combo_status)

    if family == "total odd/even":
        s = _norm(raw_sel)
        want_odd = "odd" in s
        want_even = "even" in s
        if not (want_odd or want_even):
            return None
        return aggregate(
            lambda h, a: "win"
            if (((h + a) % 2 == 1) if want_odd else ((h + a) % 2 == 0))
            else "loss"
        )

    if family == "correct score":
        m = re.search(r"(\d+)\D+(\d+)", raw_sel)
        if not m:
            return None
        ph, pa = int(m.group(1)), int(m.group(2))
        return aggregate(lambda h, a: "win" if (h, a) == (ph, pa) else "loss")

    # Team-to-qualify and other aggregate/penalty markets cannot be inferred
    # safely from one match's 90-minute score distribution.
    return None


def _visible_model_components(market_name, selection, period, calibration, probability):
    """Prefer calibrated core probabilities, then score-derived broad markets."""
    family = _canonical_market(market_name)
    period = _canonical_period(period, market_name)

    # Core calibrated families remain the highest-quality source for regular time.
    if period == "regular_time":
        calibrated = _model_probability(market_name, selection, calibration)
        if calibrated is not None:
            push = 0.0
            score_comp = _score_market_components(market_name, selection, period, probability)
            if score_comp:
                push = float(score_comp.get("push_probability") or 0.0)
            return {
                "probability": _clamp(calibrated, 0.005, 0.995),
                "push_probability": push,
                "source": "calibrated_core",
            }

    score_comp = _score_market_components(market_name, selection, period, probability)
    if score_comp:
        return {
            "probability": _clamp(score_comp["probability"], 0.005, 0.995),
            "push_probability": float(score_comp.get("push_probability") or 0.0),
            "source": "score_model",
        }
    return None


def _period_model_probability(market_name, selection, period, calibration, probability):
    components = _visible_model_components(
        market_name, selection, period, calibration, probability
    )
    if not components:
        return None
    return components.get("probability")


def _market_risk(market_name, selection, odds):
    """Family-neutral risk: complexity matters, not whether the market is familiar."""
    family = _canonical_market(market_name)

    if family == "correct score":
        risk = 0.24
    elif family in {"result+btts", "result+total", "double chance+btts", "double chance+total"}:
        risk = 0.045
    elif family in {"any team win to nil", "home win to nil", "away win to nil"}:
        risk = 0.040
    elif family in {"1x2"}:
        risk = 0.035
    elif family in {"handicap", "draw no bet", "each team to score n+"}:
        risk = 0.025
    elif family in {
        "double chance", "btts", "total", "home team total", "away team total",
        "home clean sheet", "away clean sheet", "home team to score",
        "away team to score", "total odd/even",
    }:
        risk = 0.018
    elif family == "team to qualify":
        # Can depend on aggregate score/extra time/penalties, so 90-min model is weaker.
        risk = 0.060
    else:
        risk = 0.070

    if odds >= 5.0:
        risk += 0.18
    elif odds >= 4.0:
        risk += 0.12
    elif odds >= 3.0:
        risk += 0.075
    elif odds >= 2.25:
        risk += 0.030
    elif odds < 1.10:
        risk += 0.075
    elif odds < 1.15:
        risk += 0.050
    elif odds < 1.20:
        risk += 0.020

    return risk

def _competition_penalty(extracted):
    c = _norm(extracted.get("competition"))
    penalty = 0.0
    if "friendly" in c:
        penalty += 0.08
    if any(x in c for x in ("reserve", "u17", "u18", "u19", "u20", "u21", "u23", "youth")):
        penalty += 0.06
    if any(x in c for x in ("regional", "amateur", "development")):
        penalty += 0.04
    return min(0.12, penalty)


def _uncertainty_shrink(probability, evidence, extracted, floor_weight=0.35):
    """Shrink model-only probabilities toward 50% when evidence/competition is weak."""
    p = _clamp(probability, 0.01, 0.99)
    comp = _competition_penalty(extracted)
    weight = _clamp(floor_weight + evidence * 0.55 - comp * 1.25, 0.28, 0.90)
    return _clamp(0.50 + (p - 0.50) * weight, 0.01, 0.99)


def _evidence_confidence(reliability, audit):
    evidence = _clamp(reliability)
    audit_score = _f((audit or {}).get("quality_score"))
    if audit_score is not None:
        evidence = evidence * 0.78 + _clamp(audit_score) * 0.22
    if audit and audit.get("enabled") and audit.get("status") != "OK":
        evidence *= 0.90
    if audit and audit.get("contradiction"):
        evidence *= 0.72
    return _clamp(evidence)



def rank_visible_markets(extracted, probability, calibration, reliability, deepseek_audit=None):
    """V19.5: compare every readable screenshot market on one common scale.

    Core markets use calibrated probabilities. Team totals, handicaps, win-to-nil,
    result+BTTS, result+total, double-chance combos, half markets and other
    score-defined selections are evaluated from the match score distribution.
    Truly unsupported markets remain eligible through bookmaker consensus, but
    they receive an uncertainty penalty instead of silently dominating the model.
    """
    candidates = []
    evidence = _evidence_confidence(reliability, deepseek_audit or {})
    comp_penalty = _competition_penalty(extracted)

    for market in extracted.get("markets", []) or []:
        name = str(market.get("market_name") or "Unknown")
        period = _canonical_period(market.get("period"), name)
        selections = market.get("selections", []) or []
        family = _canonical_market(name)

        # Double Chance selections overlap and must not be normalized as if
        # mutually exclusive. Most other visible market blocks are safe to de-vig.
        fair_map = {} if family == "double chance" else _no_vig(selections)

        for item in selections:
            odds = _f(item.get("odds"))
            if not odds or odds <= 1.0:
                continue

            raw_implied = _clamp(1.0 / odds, 0.005, 0.995)
            market_p = _clamp(fair_map.get(id(item), raw_implied), 0.005, 0.995)

            components = _visible_model_components(
                name, item.get("selection"), period, calibration, probability
            )
            model_supported = components is not None

            if model_supported:
                raw_model_p = _clamp(components["probability"], 0.005, 0.995)
                push_p = float(components.get("push_probability") or 0.0)
                model_source = str(components.get("source") or "score_model")

                # Calibrated core gets full evidence weight. Score-derived specialist
                # markets are intentionally a little more anchored to the real price.
                if model_source == "calibrated_core":
                    model_weight = _clamp(0.24 + evidence * 0.68, 0.24, 0.90)
                else:
                    model_weight = _clamp(0.18 + evidence * 0.58, 0.18, 0.78)
                robust_p = _clamp(
                    raw_model_p * model_weight + market_p * (1.0 - model_weight),
                    0.005, 0.995
                )
            else:
                raw_model_p = market_p
                push_p = 0.0
                model_source = "bookmaker_anchor_only"
                model_weight = 0.0
                robust_p = market_p

            edge = robust_p - market_p
            ev = robust_p * odds + push_p - 1.0
            risk = _market_risk(name, item.get("selection"), odds) + comp_penalty
            if not model_supported:
                risk += 0.055

            # No market-family popularity bonus. A supported Team Total or combo
            # competes directly with W1/BTTS/Total using the same probability,
            # evidence, value and risk terms.
            score = (
                robust_p * 0.50
                + evidence * 0.17
                + max(-0.10, min(0.14, ev)) * 0.19
                + max(-0.06, min(0.10, edge)) * 0.08
                - risk * 0.20
            )

            # Real, model-readable specialist markets deserve to be considered,
            # not penalized simply because older versions did not know the family.
            if model_supported:
                score += 0.018
            else:
                score -= 0.020

            candidates.append({
                "market_name": _strip_period_display(name) or name,
                "base_market_name": _strip_period_display(name) or name,
                "market_family": family,
                "period": period,
                "selection": _display_selection(name, item.get("selection")),
                "odds": odds,
                "raw_model_probability": raw_model_p,
                "model_probability": robust_p,
                "market_probability": market_p,
                "edge": edge,
                "expected_value": ev,
                "push_probability": push_p,
                "risk_penalty": risk,
                "ranking_score": score,
                "evidence_confidence": evidence,
                "market_anchor_weight": 1.0 - model_weight,
                "model_supported": model_supported,
                "model_source": model_source,
            })

    return sorted(candidates, key=lambda x: x["ranking_score"], reverse=True)

def _estimated_bookmaker_odds(probability, margin=0.045, push_probability=0.0):
    """Central internal estimate; supports Asian-total push protection."""
    p = _clamp(probability, 0.01, 0.99)
    push = _clamp(push_probability, 0.0, 0.90)
    fair = max(1.01, (1.0 - push) / p)
    offered = fair / (1.0 + max(0.0, margin))
    return max(1.01, round(offered, 3))


def _estimated_odds_range(probability, evidence, extracted, margin=0.045, push_probability=0.0):
    """Return a probability-consistent bookmaker range for hidden markets."""
    center = _estimated_bookmaker_odds(probability, margin, push_probability)
    # Sparse competitions get a wider band. This is explicitly an estimate.
    comp = _competition_penalty(extracted)
    width = 0.06 + (1.0 - _clamp(evidence)) * 0.10 + comp * 0.55
    low = max(1.01, center * (1.0 - width))
    high = max(low + 0.02, center * (1.0 + width))
    return round(low, 2), round(high, 2), center


def _hidden_model_candidates(extracted, probability, calibration, reliability, deepseek_audit=None):
    """V20: generate model-derived betting markets even when not shown.

    Screenshot data anchors the fixture and any real bookmaker prices that are visible.
    The score model is free to derive other football markets from the same match model.
    Derived candidates NEVER expose a synthetic bookmaker quote to the customer; the
    internal estimated price is used only as a risk/value sanity check.
    """
    evidence = _evidence_confidence(reliability, deepseek_audit or {})
    comp_penalty = _competition_penalty(extracted)
    out = []

    # If an exact selection is visible, do not hide its known quote by re-creating
    # the same pick as a no-odds model selection. Related alternatives are allowed.
    visible_pairs = set()
    for market in extracted.get("markets", []) or []:
        for item in market.get("selections", []) or []:
            visible_pairs.add(_market_key(
                market.get("market_name"), item.get("selection"), market.get("period")
            ))

    specs = []
    seen_specs = set()

    def add(market_name, selection, period="regular_time", base_risk=0.025):
        key = _market_key(market_name, selection, period)
        if key in seen_specs or key in visible_pairs:
            return
        seen_specs.add(key)
        components = _visible_model_components(
            market_name, selection, period, calibration, probability
        )
        if not components:
            return
        raw_p = _f(components.get("probability"))
        if raw_p is None:
            return
        push_p = float(components.get("push_probability") or 0.0)
        specs.append((market_name, selection, period, raw_p, push_p, base_risk,
                      str(components.get("source") or "score_model")))

    # ---------- REGULAR TIME CORE ----------
    for sel in ("W1", "Draw", "W2"):
        add("1X2", sel, base_risk=0.070 if sel != "Draw" else 0.095)
    for sel in ("1X", "12", "2X"):
        add("Double Chance", sel, base_risk=-0.020)
    for sel in ("W1 (0)", "W2 (0)"):
        add("Draw No Bet", sel, base_risk=0.010)

    # Match totals: half-lines plus integer Asian totals with push protection.
    for line in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5):
        for side in ("Over", "Under"):
            add("Total", f"{side} ({line:g})", base_risk=0.000 if line % 1 else -0.012)

    # Team totals let the engine express one-sided scoring expectations instead of
    # forcing W1/W2 or a whole-match total.
    for market_name in ("Team 1 Total", "Team 2 Total"):
        for line in (0.5, 1.0, 1.5, 2.0, 2.5):
            for side in ("Over", "Under"):
                add(market_name, f"{side} ({line:g})", base_risk=0.010 if line % 1 else 0.000)

    # Handicaps / Asian handicaps. Positive and negative lines allow safer or more
    # rewarding expressions of the same team-strength thesis.
    for line in (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5):
        label = f"{line:+g}" if line else "0"
        add("Handicap", f"W1 ({label})", base_risk=0.018)
        add("Handicap", f"W2 ({label})", base_risk=0.018)

    # BTTS / scoring / clean-sheet / win-to-nil families.
    for yn in ("Yes", "No"):
        add("Both Teams To Score", yn, base_risk=0.010)
        add("Each Team To Score (2) Or More", yn, base_risk=0.035)
        add("Team 1 To Score", yn, base_risk=0.010)
        add("Team 2 To Score", yn, base_risk=0.010)
        add("Team 1 Clean Sheet", yn, base_risk=0.018)
        add("Team 2 Clean Sheet", yn, base_risk=0.018)
        add("Team 1 Win To Nil", yn, base_risk=0.038)
        add("Team 2 Win To Nil", yn, base_risk=0.038)
        add("Any Team To Win To Nil", yn, base_risk=0.042)

    # Result + BTTS combinations.
    for outcome in ("W1", "Draw", "W2"):
        for yn in ("Yes", "No"):
            add("Result + Both Teams To Score", f"{outcome} And Both To Score - {yn}", base_risk=0.055)

    # Result + Total: useful when plain favourite odds are too short.
    for outcome in ("W1", "W2"):
        for line in (1.5, 2.5, 3.5):
            for side in ("Over", "Under"):
                add("Result + Total", f"{outcome} And {side} ({line:g})", base_risk=0.050)

    # Double Chance combos are often the middle ground between tiny DC odds and
    # an aggressive straight result.
    for dc in ("1X", "12", "2X"):
        for line in (1.5, 2.5, 3.5):
            for side in ("Over", "Under"):
                add("Double Chance + Total", f"{dc} And {side} ({line:g})", base_risk=0.045)
        for yn in ("Yes", "No"):
            add("Double Chance + Both Teams To Score", f"{dc} And Both To Score - {yn}", base_risk=0.050)

    # ---------- 1ST / 2ND HALF ----------
    # These are derived from period-scaled expected goals. They can be recommended
    # even when the screenshot is currently on the Regular Time tab.
    for period, label in (("1st_half", "1st Half"), ("2nd_half", "2nd Half")):
        for sel in ("W1", "Draw", "W2"):
            add(f"{label} Result", sel, period=period, base_risk=0.055)
        for line in (0.5, 1.0, 1.5, 2.0, 2.5):
            for side in ("Over", "Under"):
                add(f"{label} Total", f"{side} ({line:g})", period=period,
                    base_risk=0.030 if line % 1 else 0.020)
        for market_name in (f"{label} Team 1 Total", f"{label} Team 2 Total"):
            for line in (0.5, 1.0, 1.5):
                for side in ("Over", "Under"):
                    add(market_name, f"{side} ({line:g})", period=period, base_risk=0.035)

    # A small correct-score set remains available but deliberately high risk.
    for score_item in ((probability or {}).get("most_likely_scores", []) or [])[:3]:
        score = str(score_item.get("score") or "").strip()
        if score:
            add("Correct Score", score, base_risk=0.30)

    for market_name, selection, period, raw_p, push_p, base_risk, model_source in specs:
        p = _uncertainty_shrink(raw_p, evidence, extracted)
        margin = 0.12 if _canonical_market(market_name) == "correct score" else 0.045
        est_low, est_high, est_odds = _estimated_odds_range(
            p, evidence, extracted, margin, push_p
        )

        risk = base_risk + comp_penalty + 0.025
        if est_odds >= 4.0:
            risk += 0.14
        elif est_odds >= 3.0:
            risk += 0.08
        elif est_odds >= 2.25:
            risk += 0.03

        # Model-derived markets are ranked primarily by probability/evidence/risk.
        # Estimated price is only a private sanity signal; it is never printed.
        score = p * 0.61 + evidence * 0.17 - risk * 0.18
        if 1.80 <= est_odds <= 2.20:
            score += 0.080
        elif 2.20 < est_odds <= 2.80:
            score += 0.050
        elif 2.80 < est_odds <= 3.20:
            score += 0.020
        elif est_odds < 1.80:
            score -= 0.090
        elif est_odds > 4.00:
            score -= 0.075
        if push_p > 0:
            score += min(0.030, push_p * 0.11)

        out.append({
            "market_name": _strip_period_display(market_name) or market_name,
            "base_market_name": _strip_period_display(market_name) or market_name,
            "market_family": _canonical_market(market_name),
            "period": _canonical_period(period, market_name),
            "selection": _display_selection(market_name, selection),
            "odds": est_odds,                    # internal only
            "estimated_odds_low": est_low,       # internal only
            "estimated_odds_high": est_high,     # internal only
            "odds_estimated": True,
            "raw_model_probability": raw_p,
            "model_probability": p,
            "market_probability": None,
            "edge": 0.0,
            "expected_value": 0.0,
            "push_probability": push_p,
            "risk_penalty": risk,
            "ranking_score": score,
            "evidence_confidence": evidence,
            "market_anchor_weight": 0.0,
            "model_supported": True,
            "model_source": model_source if model_source else "score_model",
            "source": "model_derived",
        })

    return out

def rank_all_markets(extracted, probability, calibration, reliability, deepseek_audit=None):
    visible = rank_visible_markets(extracted, probability, calibration, reliability, deepseek_audit)
    for c in visible:
        c["odds_estimated"] = False
        c["source"] = "screenshot"

    # V19.5: keep model-derived nearby alternatives in the comparison even when
    # screenshot prices exist. Exact visible pairs are already deduplicated inside
    # _hidden_model_candidates, and estimated odds are never shown to customers.
    hidden = _hidden_model_candidates(
        extracted, probability, calibration, reliability, deepseek_audit
    )
    combined = list(visible) + list(hidden)
    return sorted(combined, key=lambda x: x["ranking_score"], reverse=True)

def _tip_grade(candidate):
    e = candidate["evidence_confidence"]
    p = candidate["model_probability"]
    ev = candidate["expected_value"]
    if e >= 0.78 and p >= 0.70 and ev >= 0.015: return "A"
    if e >= 0.58 and p >= 0.62 and ev >= -0.01: return "B+"
    if p >= 0.58: return "B"
    return "C"


def _tip_mode(candidate, audit):
    if audit.get("contradiction") or candidate["evidence_confidence"] < 0.35:
        return "LOW-CONFIDENCE"
    if candidate["expected_value"] > 0 and candidate["edge"] > 0:
        return "VALUE"
    return "SAFETY-FIRST"


def build_v13_decision(extracted, research, probability, calibration):
    audit = verify_model_context(research, probability)
    reliability = float(calibration.get("one_x_two", {}).get("reliability_factor", 0.0) or 0.0)
    if reliability <= 0.0:
        reliability = float((probability.get("model_confidence", {}) or {}).get("score", 0.0) or 0.0)

    ranked = rank_all_markets(extracted, probability, calibration, reliability, audit)
    # V16: verified historical outcomes may apply a small sample-gated calibration
    # correction. It is bounded and does nothing until enough settled picks exist.
    ranked = apply_performance_feedback(ranked)
    ranked = apply_contextual_learning(ranked, extracted, research)
    # V20: SAFE BIG ODD Single-only mode. Mandatory-tip behavior is preserved;
    # weak candidates are demoted/graded, never converted into NO BET.
    ranked = apply_selection_intelligence(ranked, extracted, research, audit)
    if not ranked:
        return {
            "version": V13_VERSION, "status": "NEED_INPUT", "tip": None,
            "ranked_candidates": [], "deepseek_audit": audit, "reliability": reliability,
            "gate_reasons": ["Model ကတွက်နိုင်တဲ့ match/market data မလုံလောက်ပါ။"],
            "warnings": ["Input/extraction incomplete — this is not a NO BET decision"],
        }

    # V20.1 FINAL SELECTOR — REAL ODDS FIRST, SAFE BIG ODD, SINGLE BET ONLY.
    # 1) A customer-facing tip must use a REAL bookmaker quote whenever the uploaded
    #    screenshot contains at least one readable 1.80+ candidate. Model-derived
    #    markets are fallback-only and can never outrank a usable real 1.80+ quote.
    visible_big = [
        c for c in ranked
        if (not c.get("odds_estimated"))
        and float(c.get("odds") or 0.0) >= 1.80
        and not c.get("single_bet_ineligible")
    ]

    # 2) Inside the visible 1.80+ set, prefer markets the football model can actually
    #    price. If none is model-readable, mandatory-tip mode still chooses the best
    #    real bookmaker option instead of inventing a hidden market.
    visible_supported = [c for c in visible_big if c.get("model_supported")]
    if visible_big:
        pool = visible_supported or visible_big
    else:
        # 3) Only when the screenshot exposes NO real 1.80+ quote may the engine use
        #    a model-derived 1.80+ alternative. This preserves the no-skip/no-NO-BET
        #    policy without pretending an estimated price is a bookmaker price.
        derived_big = [
            c for c in ranked
            if c.get("odds_estimated")
            and float(c.get("odds") or 0.0) >= 1.80
            and not c.get("single_bet_ineligible")
        ]
        pool = derived_big

    # A valid football model should normally make the pool non-empty. If extraction
    # is too incomplete to create any 1.80+ market, report an input problem rather
    # than mislabeling the match as NO BET.
    if not pool:
        return {
            "version": V13_VERSION, "status": "NEED_INPUT", "tip": None,
            "ranked_candidates": ranked[:10], "deepseek_audit": audit,
            "reliability": reliability,
            "gate_reasons": ["1.80+ Single Tip တည်ဆောက်ဖို့ match/market data မလုံလောက်ပါ။"],
            "warnings": ["Input/extraction incomplete — this is not a NO BET decision"],
        }

    # 4) Probability is still king. When a reasonably safer 1.80+ group exists,
    #    choose inside it; otherwise mandatory mode still returns the best available
    #    1.80+ candidate with a lower grade.
    safer = [c for c in pool if float(c.get("model_probability") or 0.0) >= 0.48]
    if safer:
        pool = safer

    def final_score(c):
        score = float(c.get("selection_intelligence_score", c.get("ranking_score", 0.0)) or 0.0)
        p = float(c.get("model_probability") or 0.0)
        risk = max(0.0, float(c.get("risk_penalty") or 0.0))
        score += p * 0.035 - risk * 0.025

        if c.get("odds_estimated"):
            # Hidden-market estimate is private. We target the safest practical
            # big-odd zone rather than blindly chasing 4.00+ prices.
            est = float(c.get("odds") or 0.0)
            if est < 1.80:
                return -999.0
            if 1.80 <= est <= 2.20:
                score += 0.060
            elif est <= 2.60:
                score += 0.045
            elif est <= 3.00:
                score += 0.022
            elif est <= 4.00:
                score -= 0.020
            else:
                score -= 0.070
            score -= 0.012  # uncertainty cost for no real bookmaker quote
        else:
            actual = float(c.get("odds") or 0.0)
            if actual < 1.80:
                return -999.0
            score += 0.038  # real-price confirmation
            if 1.80 <= actual <= 2.40:
                score += 0.030
            elif actual <= 2.80:
                score += 0.018
            elif actual >= 4.00:
                score -= 0.055
            if float(c.get("expected_value") or 0.0) > 0:
                score += min(0.025, float(c["expected_value"]) * 0.08)
        return score

    best = max(pool, key=final_score)

    # 5) Safety invariant: if any real 1.80+ quote was visible, the final tip must
    #    also be real. This guards against later ranking changes accidentally allowing
    #    a synthetic/hidden market to leak into customer output.
    if visible_big and best.get("odds_estimated"):
        real_guard_pool = visible_supported or visible_big
        best = max(real_guard_pool, key=final_score)

    # Mandatory-tip policy: analyzable matches are never rejected by a quality gate.
    # no_bet_gate is retained for backwards compatibility/diagnostics only.
    gate_reasons = no_bet_gate(best, extracted, research, audit)
    if gate_reasons:
        return {
            "version": V13_VERSION, "status": "NEED_INPUT", "tip": None,
            "ranked_candidates": ranked[:10], "deepseek_audit": audit,
            "reliability": reliability, "gate_reasons": gate_reasons,
            "warnings": ["Input/extraction failure — not a NO BET quality decision"],
        }

    grade = _tip_grade(best)
    mode = _tip_mode(best, audit)

    warnings = []
    if best["evidence_confidence"] < 0.45:
        warnings.append("Sparse/low-quality evidence — market consensus weighting increased")
    if _competition_penalty(extracted) > 0:
        warnings.append("Friendly/lower-data competition — uncertainty penalty applied")
    if best["expected_value"] <= 0:
        warnings.append("Best available 1.80+ model-supported Single selected; positive EV is not guaranteed")
    if audit.get("contradiction"):
        warnings.append("DeepSeek found an evidence contradiction — confidence reduced")

    return {
        "version": V13_VERSION,
        "status": "TIP_READY" if grade in {"A", "B+", "B"} else "FORCED_TIP",
        "tip": {**best, "grade": grade, "tip_mode": mode},
        "ranked_candidates": ranked[:10],
        "deepseek_audit": audit,
        "reliability": reliability,
        "gate_reasons": [],
        "warnings": warnings,
    }


def format_v13_tip(result):
    """Customer-facing report: match data + one actionable pre-bet tip only."""
    match = result.get("match", {}) or {}
    extracted = result.get("extracted_data", {}) or {}
    v13 = result.get("v13", {}) or {}
    tip = v13.get("tip")

    home = match.get("home_team") or (extracted.get("match") or {}).get("home_team") or "Home"
    away = match.get("away_team") or (extracted.get("match") or {}).get("away_team") or "Away"
    league = match.get("competition") or extracted.get("competition") or "N/A"

    if not tip:
        return (
            "👑 SHWE OHH PRE-BET\n\n"
            f"⚽ {home} vs {away}\n"
            f"🏆 {league}\n\n"
            "📸 ပွဲအမည်/အသင်းတွေ မြင်ရအောင် Pre-Bet screenshot ပြန်ပို့ပါ။"
        )

    market = str(tip.get("market_name") or "Market").strip()
    base_market = str(tip.get("base_market_name") or _strip_period_display(market) or "Market").strip()
    period = _canonical_period(tip.get("period"), market)
    period_text = _period_label(period)
    selection = _display_selection(base_market, tip.get("selection"))
    family = _canonical_market(base_market)

    if family == "total":
        # User-facing wording: "Regular Time — Over (1.5)" / "1st Half — Over (0.5)".
        market_text = f"{period_text} — {selection}"
    elif selection:
        market_text = f"{period_text} — {base_market} — {selection}"
    else:
        market_text = f"{period_text} — {base_market}"

    probability = float(tip.get("model_probability") or 0.0) * 100.0
    odds_line = ""
    # Never show synthetic/estimated prices to customers. If the exact bookmaker
    # quote was visible in the screenshot, keep that real quote because it is useful.
    if not tip.get("odds_estimated"):
        odds = float(tip.get("odds") or 0.0)
        if odds > 1.0:
            odds_line = f"💰 Odds: {odds:.3f}\n"
    else:
        # Never fabricate a bookmaker quote. Tell the customer the acceptance floor.
        odds_line = "💰 Accept Odds: 1.80+ only (check bookmaker)\n"

    return (
        "👑 SHWE OHH PRE-BET\n\n"
        f"⚽ {home} vs {away}\n"
        f"🏆 {league}\n"
        "🎫 Pre Bet\n\n"
        f"🎯 TIP: {market_text}\n"
        f"{odds_line}"
        f"📊 Win Chance: {probability:.0f}%"
    )
