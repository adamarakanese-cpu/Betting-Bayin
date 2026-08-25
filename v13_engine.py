import math
from deepseek_verifier import verify_model_context

V13_VERSION = "V15.0 FINAL PRE-BET"


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _norm(s):
    return str(s or "").strip().lower().replace("−", "-")


def _canonical_market(market_name):
    """Canonical market families used only for matching/deduplication."""
    m = _norm(market_name)
    compact = m.replace(" ", "").replace("-", "")
    if compact in {"1x2", "matchresult", "fulltimeresult"}:
        return "1x2"
    if "doublechance" in compact and "bothteam" not in compact:
        return "double chance"
    if compact in {"btts", "bothteamstoscore", "bothteamscore"} or "bothteamstoscore" in compact:
        return "btts"
    if "total" in m and "team" not in m:
        return "total"
    if "home" in m and "team" in m and "total" in m:
        return "home team total"
    if "away" in m and "team" in m and "total" in m:
        return "away team total"
    if "home" in m and "clean" in m and "sheet" in m:
        return "home clean sheet"
    if "away" in m and "clean" in m and "sheet" in m:
        return "away clean sheet"
    return m


def _canonical_selection(market_name, selection):
    """Normalize bookmaker aliases so visible prices always beat estimates."""
    m = _norm(market_name)
    s = _norm(selection).replace(" ", "")
    if "doublechance" in m.replace(" ", ""):
        if s in {"x2", "2x"}:
            return "2x"
        if s in {"1x", "x1"}:
            return "1x"
        if s in {"12", "21"}:
            return "12"
    if m == "1x2":
        aliases = {"1": "w1", "home": "w1", "homewin": "w1",
                   "x": "draw", "2": "w2", "away": "w2", "awaywin": "w2"}
        return aliases.get(s, s)
    return s


def _market_key(market_name, selection):
    # Canonical key is for matching only. Customer display follows 1X / 12 / 2X.
    return (_canonical_market(market_name), _canonical_selection(market_name, selection))


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


def _market_risk(market_name, selection, odds):
    m = _norm(market_name)
    if "double chance" in m:
        risk = -0.05
    elif "total" in m or "both teams to score" in m or m == "btts":
        risk = 0.00
    elif m == "1x2":
        risk = 0.07
    else:
        risk = 0.10
    if odds >= 4.0: risk += 0.16
    elif odds >= 3.0: risk += 0.10
    elif odds >= 2.25: risk += 0.04
    elif odds < 1.15: risk += 0.05
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


def rank_visible_markets(extracted, calibration, reliability, deepseek_audit=None):
    """Rank only screenshot-visible markets supported by the probability model.

    V13.4 uses market anchoring when evidence is sparse. This prevents a weak-data
    model from creating huge artificial edges while still allowing lower leagues
    and friendlies to produce a cautious best-available tip.
    """
    candidates = []
    evidence = _evidence_confidence(reliability, deepseek_audit or {})
    comp_penalty = _competition_penalty(extracted)

    # Weak evidence => lean more on no-vig market consensus; strong evidence => model gets more weight.
    model_weight = _clamp(0.22 + evidence * 0.68, 0.22, 0.90)

    for market in extracted.get("markets", []) or []:
        name = str(market.get("market_name") or "Unknown")
        selections = market.get("selections", []) or []
        fair_map = _no_vig(selections)
        for item in selections:
            odds = _f(item.get("odds"))
            if not odds or odds <= 1.0:
                continue
            raw_model_p = _model_probability(name, item.get("selection"), calibration)
            market_p = _clamp(fair_map.get(id(item), 1.0 / odds), 0.005, 0.995)
            # V13.5 ALWAYS-TIP fallback: if our statistical model does not natively
            # support this visible market, use the de-vigged market consensus as
            # a conservative baseline instead of discarding the selection.
            model_supported = raw_model_p is not None
            if raw_model_p is None:
                raw_model_p = market_p
            raw_model_p = _clamp(raw_model_p, 0.005, 0.995)
            robust_p = _clamp(raw_model_p * model_weight + market_p * (1.0 - model_weight), 0.005, 0.995)
            edge = robust_p - market_p
            ev = robust_p * odds - 1.0
            risk = _market_risk(name, item.get("selection"), odds) + comp_penalty

            # Probability and evidence dominate; EV is capped to avoid long-shot traps.
            score = (
                robust_p * 0.52
                + evidence * 0.20
                + max(-0.08, min(0.12, ev)) * 0.18
                + max(-0.05, min(0.10, edge)) * 0.10
                - risk * 0.22
            )
            candidates.append({
                "market_name": name,
                "selection": _display_selection(name, item.get("selection")),
                "odds": odds,
                "raw_model_probability": raw_model_p,
                "model_probability": robust_p,
                "market_probability": market_p,
                "edge": edge,
                "expected_value": ev,
                "risk_penalty": risk,
                "ranking_score": score,
                "evidence_confidence": evidence,
                "market_anchor_weight": 1.0 - model_weight,
                "model_supported": model_supported,
            })
    return sorted(candidates, key=lambda x: x["ranking_score"], reverse=True)



def _estimated_bookmaker_odds(probability, margin=0.045):
    """Central estimate derived from probability; never presented as a live quote."""
    p = _clamp(probability, 0.01, 0.99)
    offered = 1.0 / min(0.995, p * (1.0 + margin))
    return max(1.01, round(offered, 3))


def _estimated_odds_range(probability, evidence, extracted, margin=0.045):
    """Return a probability-consistent bookmaker range for hidden markets."""
    center = _estimated_bookmaker_odds(probability, margin)
    # Sparse competitions get a wider band. This is explicitly an estimate.
    comp = _competition_penalty(extracted)
    width = 0.06 + (1.0 - _clamp(evidence)) * 0.10 + comp * 0.55
    low = max(1.01, center * (1.0 - width))
    high = max(low + 0.02, center * (1.0 + width))
    return round(low, 2), round(high, 2), center


def _hidden_model_candidates(extracted, probability, calibration, reliability, deepseek_audit=None):
    """Create model-derived candidates even when a market is not visible in SS."""
    evidence = _evidence_confidence(reliability, deepseek_audit or {})
    comp_penalty = _competition_penalty(extracted)
    out = []

    one = (calibration.get("one_x_two", {}) or {}).get("calibrated", {}) or {}
    binary = calibration.get("binary_markets", {}) or {}
    totals = binary.get("totals", {}) or {}
    btts = binary.get("btts", {}) or {}

    specs = []
    h, d, a = one.get("home_win"), one.get("draw"), one.get("away_win")
    if None not in (h, d, a):
        specs += [
            ("1X2", "W1", h, 0.07),
            ("1X2", "Draw", d, 0.10),
            ("1X2", "W2", a, 0.07),
            ("Double Chance", "1X", h + d, -0.05),
            ("Double Chance", "12", h + a, -0.03),
            ("Double Chance", "2X", d + a, -0.05),
        ]

    for line in (1.5, 2.5, 3.5):
        key = str(line).replace('.', '_')
        op = totals.get(f"over_{key}")
        un = totals.get(f"under_{key}")
        if op is not None:
            specs.append(("Total", f"Over ({line})", op, 0.00))
        if un is not None:
            specs.append(("Total", f"Under ({line})", un, 0.00))

    if btts.get("yes") is not None:
        specs.append(("Both Teams To Score", "Yes", btts.get("yes"), 0.00))
    if btts.get("no") is not None:
        specs.append(("Both Teams To Score", "No", btts.get("no"), 0.00))

    # Extra model-derived goal markets from the Poisson expected-goals layer.
    # These are model picks only when the bookmaker quote is not visible.
    expected = (probability or {}).get("expected_goals", {}) or {}
    hx = _f(expected.get("home_xg"))
    ax = _f(expected.get("away_xg"))
    if hx is not None and ax is not None:
        lam = max(0.01, hx + ax)
        p0 = math.exp(-lam)
        p_le4 = sum(math.exp(-lam) * (lam ** k) / math.factorial(k) for k in range(5))
        specs += [
            ("Total", "Over (0.5)", 1.0 - p0, -0.02),
            ("Total", "Under (0.5)", p0, 0.12),
            ("Total", "Over (4.5)", 1.0 - p_le4, 0.08),
            ("Total", "Under (4.5)", p_le4, -0.01),
            ("At Least One Team To Score", "Yes", 1.0 - p0, -0.02),
        ]

    # Correct-score candidates come from the model's score distribution. They
    # carry a deliberately high risk penalty and will almost never outrank a
    # safer supported market; this prevents long-shot score traps.
    for score_item in ((probability or {}).get("most_likely_scores", []) or [])[:3]:
        score = str(score_item.get("score") or "").strip()
        sp = _f(score_item.get("probability"))
        if score and sp is not None:
            specs.append(("Correct Score", score, sp, 0.28))

    # Team-to-score / clean-sheet markets are available from the Poisson model,
    # though the calibration engine does not expose calibrated versions yet.
    scoring = (probability or {}).get("team_scoring", {}) or {}
    # Shrink raw model-only binary markets toward 50% according to reliability.
    shrink_w = _clamp(0.25 + evidence * 0.65, 0.25, 0.90)
    for market, sel, key in [
        ("Home Team Total", "Over (0.5)", "home_to_score"),
        ("Away Team Total", "Over (0.5)", "away_to_score"),
        ("Home Team Total", "Under (0.5)", "away_clean_sheet"),
        ("Away Team Total", "Under (0.5)", "home_clean_sheet"),
        ("Home Clean Sheet", "Yes", "home_clean_sheet"),
        ("Away Clean Sheet", "Yes", "away_clean_sheet"),
    ]:
        raw = _f(scoring.get(key))
        if raw is not None:
            robust = _clamp(raw * shrink_w + 0.50 * (1.0 - shrink_w), 0.01, 0.99)
            specs.append((market, sel, robust, 0.01))

    # Deduplicate against screenshot-visible exact market/selection pairs so an
    # actual quoted price always wins over an estimate for the same selection.
    visible_pairs = set()
    for market in extracted.get("markets", []) or []:
        mn = _norm(market.get("market_name"))
        for item in market.get("selections", []) or []:
            visible_pairs.add(_market_key(market.get("market_name"), item.get("selection")))

    for market_name, selection, p_raw, base_risk in specs:
        p = _uncertainty_shrink(p_raw, evidence, extracted)
        if _market_key(market_name, selection) in visible_pairs:
            continue
        margin = 0.12 if market_name == "Correct Score" else (0.05 if market_name == "1X2" else 0.04)
        est_low, est_high, est_odds = _estimated_odds_range(p, evidence, extracted, margin)
        risk = base_risk + comp_penalty + 0.025  # hidden-market uncertainty penalty
        if est_odds >= 4.0: risk += 0.14
        elif est_odds >= 3.0: risk += 0.08
        elif est_odds >= 2.25: risk += 0.03

        # Hidden-market ranking is safety first: probability dominates. Because
        # the odds are estimated, no fake edge/EV is credited to the score.
        score = p * 0.68 + evidence * 0.18 - risk * 0.20
        # Mild preference for usable prices; avoid selecting 1.02 unless nothing
        # else is remotely close in win probability.
        if 1.15 <= est_odds <= 2.20:
            score += 0.035
        elif est_odds < 1.10:
            score -= 0.035

        out.append({
            "market_name": market_name,
            "selection": selection,
            "odds": est_odds,
            "estimated_odds_low": est_low,
            "estimated_odds_high": est_high,
            "odds_estimated": True,
            "raw_model_probability": p,
            "model_probability": p,
            "market_probability": None,
            "edge": 0.0,
            "expected_value": 0.0,
            "risk_penalty": risk,
            "ranking_score": score,
            "evidence_confidence": evidence,
            "market_anchor_weight": 0.0,
            "model_supported": True,
            "source": "model_estimate",
        })
    return out


def rank_all_markets(extracted, probability, calibration, reliability, deepseek_audit=None):
    visible = rank_visible_markets(extracted, calibration, reliability, deepseek_audit)
    visible_by_key = {}
    for c in visible:
        c["odds_estimated"] = False
        c["source"] = "screenshot"
        visible_by_key[_market_key(c.get("market_name"), c.get("selection"))] = c

    hidden = _hidden_model_candidates(
        extracted, probability, calibration, reliability, deepseek_audit
    )

    # Absolute rule: if the screenshot contains the same market/selection under
    # an alias (e.g. 2X vs X2), never allow a synthetic candidate or estimated
    # price to represent it. The screenshot quote is the source of truth.
    hidden = [
        c for c in hidden
        if _market_key(c.get("market_name"), c.get("selection")) not in visible_by_key
    ]
    return sorted(visible + hidden, key=lambda x: x["ranking_score"], reverse=True)

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
    if not ranked:
        return {
            "version": V13_VERSION, "status": "NO_SUPPORTED_VISIBLE_MARKET", "tip": None,
            "ranked_candidates": [], "deepseek_audit": audit, "reliability": reliability,
            "gate_reasons": ["Model ကတွက်နိုင်တဲ့ market မရှိသေးပါ။"],
        }

    # V13.6 universal market selector. Actual screenshot prices and model-only
    # markets compete in one pool. Probability/safety dominates; positive EV is
    # a bonus only when we have a real screenshot price.
    pool = [c for c in ranked if c.get("model_supported")] or ranked

    # Prefer a genuinely likely outcome. If at least one candidate is >=55%,
    # do not select a 30-40% longshot merely because its displayed odds are high.
    safer = [c for c in pool if c["model_probability"] >= 0.55]
    if safer:
        pool = safer

    practical = [c for c in pool if 1.08 <= c["odds"] <= 3.50]
    if practical:
        pool = practical

    # Reward real positive-EV screenshot markets without letting EV overpower
    # win probability. Estimated-odds markets receive no EV bonus.
    def final_score(c):
        # A real screenshot quote is stronger evidence than a model-only market.
        bonus = 0.018 if not c.get("odds_estimated") else 0.0
        if not c.get("odds_estimated") and c.get("expected_value", 0) > 0:
            bonus += min(0.035, c["expected_value"] * 0.10)
        return c["ranking_score"] + bonus

    best = max(pool, key=final_score)
    grade = _tip_grade(best)
    mode = _tip_mode(best, audit)

    warnings = []
    if best["evidence_confidence"] < 0.45:
        warnings.append("Sparse/low-quality evidence — market consensus weighting increased")
    if _competition_penalty(extracted) > 0:
        warnings.append("Friendly/lower-data competition — uncertainty penalty applied")
    if best["expected_value"] <= 0:
        warnings.append("No robust positive-EV option found — safest supported visible market selected")
    if audit.get("contradiction"):
        warnings.append("DeepSeek found an evidence contradiction — confidence reduced")

    return {
        "version": V13_VERSION,
        "status": "TIP_READY" if grade in {"A", "B+", "B"} else "CAUTION_TIP",
        "tip": {**best, "grade": grade, "tip_mode": mode},
        "ranked_candidates": ranked[:10],
        "deepseek_audit": audit,
        "reliability": reliability,
        "gate_reasons": [],
        "warnings": warnings,
    }


def format_v13_tip(result):
    """Customer-facing report: match data + one actionable tip only."""
    match = result.get("match", {}) or {}
    extracted = result.get("extracted_data", {}) or {}
    v13 = result.get("v13", {}) or {}
    tip = v13.get("tip")

    home = match.get("home_team") or (extracted.get("match") or {}).get("home_team") or "Home"
    away = match.get("away_team") or (extracted.get("match") or {}).get("away_team") or "Away"
    league = match.get("competition") or extracted.get("competition") or "N/A"
    live = extracted.get("live", {}) or {}
    bet_type = "Live Bet" if live.get("is_live") else "Pre Bet"

    if not tip:
        return (
            f"👑 BETTING BAYIN {V13_VERSION}\n\n"
            f"⚽ {home} vs {away}\n"
            f"🏆 {league}\n\n"
            "📸 Market နဲ့ Odds မြင်ရအောင် screenshot ပြန်ပို့ပါ။"
        )

    market = str(tip.get("market_name") or "Market").strip()
    selection = _display_selection(market, tip.get("selection"))
    market_text = f"{market} — {selection}" if selection else market
    odds = float(tip.get("odds") or 0.0)
    probability = float(tip.get("model_probability") or 0.0) * 100.0
    if tip.get("odds_estimated"):
        odds_label = "Estimated Odds Range"
        low = _f(tip.get("estimated_odds_low"))
        high = _f(tip.get("estimated_odds_high"))
        if low is not None and high is not None:
            odds_text = f"{low:.2f}–{high:.2f}"
        else:
            odds_text = f"~{odds:.2f}"
    else:
        odds_label = "Odds"
        odds_text = f"{odds:.3f}"

    return (
        f"👑 BETTING BAYIN {V13_VERSION}\n\n"
        f"⚽ {home} vs {away}\n"
        f"🏆 {league}\n"
        f"🎫 {bet_type}\n\n"
        f"🎯 TIP: {market_text}\n"
        f"💰 {odds_label}: {odds_text}\n"
        f"📊 Win Chance: {probability:.0f}%"
    )
