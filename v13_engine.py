import math
from deepseek_verifier import verify_model_context

V13_VERSION = "V13.0"


def _f(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _norm(s):
    return str(s or "").strip().lower().replace("−", "-")


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
    m = _norm(market_name)
    s = _norm(selection)
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
        # Accept forms: Over (2.5), Over 2.5, O2.5, Under (2.5)
        for line in (1.5, 2.5, 3.5):
            token = str(line)
            if token in s:
                if "over" in s or s.startswith("o"):
                    return totals.get(f"over_{str(line).replace('.', '_')}")
                if "under" in s or s.startswith("u"):
                    return totals.get(f"under_{str(line).replace('.', '_')}")
    return None


def _market_risk(market_name, selection, odds):
    m = _norm(market_name)
    risk = 0.0
    if m == "1x2": risk += 0.10
    elif "double chance" in m: risk -= 0.04
    elif "both teams to score" in m: risk += 0.01
    elif "total" in m: risk += 0.00
    else: risk += 0.08
    if odds >= 4.0: risk += 0.14
    elif odds >= 3.0: risk += 0.08
    elif odds >= 2.2: risk += 0.03
    elif odds < 1.20: risk += 0.05
    return risk


def rank_visible_markets(extracted, calibration, reliability, deepseek_audit=None):
    candidates = []
    audit_score = None if not deepseek_audit else deepseek_audit.get("quality_score")
    contradiction = bool(deepseek_audit and deepseek_audit.get("contradiction"))

    for market in extracted.get("markets", []) or []:
        name = str(market.get("market_name") or "Unknown")
        selections = market.get("selections", []) or []
        fair_map = _no_vig(selections)
        for item in selections:
            odds = _f(item.get("odds"))
            if not odds or odds <= 1.0:
                continue
            model_p = _model_probability(name, item.get("selection"), calibration)
            if model_p is None:
                continue
            model_p = max(0.005, min(0.995, float(model_p)))
            market_p = fair_map.get(id(item), 1.0 / odds)
            edge = model_p - market_p
            ev = model_p * odds - 1.0
            risk = _market_risk(name, item.get("selection"), odds)

            # Score rewards calibrated probability and modest positive EV, while punishing longshots.
            ev_component = max(-0.20, min(0.25, ev))
            score = (
                model_p * 0.55
                + max(0.0, edge) * 0.25
                + ev_component * 0.20
                - risk
            )
            if contradiction:
                score -= 0.08

            # Confidence is evidence reliability, not the chance the bet wins.
            evidence_conf = reliability
            if audit_score is not None:
                evidence_conf = reliability * 0.75 + float(audit_score) * 0.25
            evidence_conf = max(0.0, min(1.0, evidence_conf))

            candidates.append({
                "market_name": name,
                "selection": str(item.get("selection") or ""),
                "odds": odds,
                "model_probability": model_p,
                "market_probability": market_p,
                "edge": edge,
                "expected_value": ev,
                "risk_penalty": risk,
                "ranking_score": score,
                "evidence_confidence": evidence_conf,
            })

    return sorted(candidates, key=lambda x: x["ranking_score"], reverse=True)


def build_v13_decision(extracted, research, probability, calibration):
    audit = verify_model_context(research, probability)
    reliability = float(calibration.get("one_x_two", {}).get("reliability_factor", 0.0) or 0.0)
    ranked = rank_visible_markets(extracted, calibration, reliability, audit)

    if not ranked:
        return {
            "version": V13_VERSION,
            "status": "NO_SUPPORTED_VISIBLE_MARKET",
            "tip": None,
            "ranked_candidates": [],
            "deepseek_audit": audit,
            "reliability": reliability,
        }

    best = ranked[0]
    # Grade, not a fake certainty claim.
    if best["evidence_confidence"] >= 0.75 and best["model_probability"] >= 0.62 and best["expected_value"] >= 0.02:
        grade = "A"
    elif best["evidence_confidence"] >= 0.58 and best["model_probability"] >= 0.55:
        grade = "B"
    else:
        grade = "C"

    return {
        "version": V13_VERSION,
        "status": "TIP_READY",
        "tip": {**best, "grade": grade},
        "ranked_candidates": ranked[:8],
        "deepseek_audit": audit,
        "reliability": reliability,
    }


def format_v13_tip(result):
    match = result.get("match", {}) or {}
    extracted = result.get("extracted_data", {}) or {}
    v13 = result.get("v13", {}) or {}
    tip = v13.get("tip")
    home = match.get("home_team") or "Home"
    away = match.get("away_team") or "Away"
    league = match.get("competition") or extracted.get("competition") or "N/A"

    if not tip:
        return (
            "👑 BETTING BAYIN V13\n\n"
            f"⚽ ပွဲစဉ် (Match): {home} vs {away}\n"
            f"🏆 League: {league}\n\n"
            "⚠️ Screenshot ထဲမှာ V13 model နဲ့တွက်နိုင်တဲ့ market/odds မလုံလောက်ပါ။\n"
            "1X2, Double Chance, BTTS, Total 1.5/2.5/3.5 ပါအောင် screenshot ပြန်ပို့ပါ။"
        )

    conf = tip["evidence_confidence"] * 100
    prob = tip["model_probability"] * 100
    edge = tip["edge"] * 100
    ev = tip["expected_value"] * 100
    audit = v13.get("deepseek_audit", {}) or {}
    ai_status = "DeepSeek ✓" if audit.get("status") == "OK" else "Statistical Engine"

    return (
        "👑 BETTING BAYIN V13\n\n"
        "🎯 BEST MODEL TIP\n\n"
        f"⚽ ပွဲစဉ် (Match): {home} vs {away}\n"
        f"🏆 League: {league}\n"
        "🎫 လောင်းမည့်အမျိုးအစား (Bet Type): Pre Bet\n"
        f"📌 Market: {tip['market_name']} - {tip['selection']}\n"
        f"💰 Odds: {tip['odds']:.3f}\n"
        f"📊 Model Probability: {prob:.1f}%\n"
        f"📈 Edge: {edge:+.1f}%\n"
        f"💹 Expected Value: {ev:+.1f}%\n"
        f"🛡 Evidence Confidence: {conf:.1f}%\n"
        f"🏅 Grade: {tip['grade']}\n"
        f"🤖 Verification: {ai_status}\n\n"
        "ℹ️ Probability = model estimate; Confidence = data/evidence quality. "
        "99% accuracy is not guaranteed."
    )
