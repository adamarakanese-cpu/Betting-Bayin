import math
from deepseek_verifier import verify_model_context

V13_VERSION = "V13.5"


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _norm(s):
    return str(s or "").strip().lower().replace("−", "-")


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
    if "friendly" in c: return 0.08
    if any(x in c for x in ("reserve", "u19", "u20", "u21", "youth")): return 0.06
    return 0.0


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
                "selection": str(item.get("selection") or ""),
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

    ranked = rank_visible_markets(extracted, calibration, reliability, audit)
    if not ranked:
        return {
            "version": V13_VERSION, "status": "NO_SUPPORTED_VISIBLE_MARKET", "tip": None,
            "ranked_candidates": [], "deepseek_audit": audit, "reliability": reliability,
            "gate_reasons": ["Screenshot ထဲမှာ model ကတွက်နိုင်တဲ့ visible market မရှိသေးပါ။"],
        }

    # V13.4: positive EV is preferred, but weak/sparse leagues are not automatically blocked.
    positive = [c for c in ranked if c["expected_value"] > 0 and c["edge"] > 0]
    pool = positive if positive else ranked

    # Prefer markets backed by the internal probability model, while keeping
    # every readable visible market eligible as an always-tip fallback.
    supported = [c for c in pool if c.get("model_supported")]
    if supported:
        pool = supported

    # Avoid choosing a wild longshot just because its EV is noisy.
    practical = [c for c in pool if 1.10 <= c["odds"] <= 3.25]
    if practical:
        pool = practical

    best = max(pool, key=lambda c: c["ranking_score"])
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
    """Customer-facing V13.5 report: match data + one actionable tip only."""
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
            "👑 BETTING BAYIN V13.5\n\n"
            f"⚽ {home} vs {away}\n"
            f"🏆 {league}\n\n"
            "📸 Market နဲ့ Odds မြင်ရအောင် screenshot ပြန်ပို့ပါ။"
        )

    market = str(tip.get("market_name") or "Market").strip()
    selection = str(tip.get("selection") or "").strip()
    market_text = f"{market} — {selection}" if selection else market
    odds = float(tip.get("odds") or 0.0)
    probability = float(tip.get("model_probability") or 0.0) * 100.0

    return (
        "👑 BETTING BAYIN V13.5\n\n"
        f"⚽ {home} vs {away}\n"
        f"🏆 {league}\n"
        f"🎫 {bet_type}\n\n"
        f"🎯 TIP: {market_text}\n"
        f"💰 Odds: {odds:.3f}\n"
        f"📊 Win Chance: {probability:.0f}%"
    )
