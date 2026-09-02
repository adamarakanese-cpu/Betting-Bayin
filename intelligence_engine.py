"""V20.4 PRICE REALITY intelligence layer.

Adds bounded, sample-gated league/team outcome memory and a mandatory best-available-tip policy.
It does not add network calls and therefore does not alter the V18 speed path.
"""
from functools import lru_cache
import re
from database import get_performance_rows


def _norm(v):
    return " ".join(str(v or "").strip().lower().split())


def _clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))


def _stat(rows):
    decisive = [r for r in rows if r.get("result_status") in {"win", "loss"}]
    if not decisive:
        return None
    n = len(decisive)
    wins = sum(1 for r in decisive if r.get("result_status") == "win")
    avg_p = sum(float(r.get("model_probability") or 0.5) for r in decisive) / n
    hit = wins / n
    # Heavy shrinkage: historical outcomes are feedback, never a guarantee.
    shrink = n / (n + 60.0)
    return {"sample": n, "hit_rate": hit, "avg_probability": avg_p,
            "adjustment": _clamp((hit - avg_p) * shrink, -0.025, 0.025)}


@lru_cache(maxsize=1)
def _memory():
    rows = get_performance_rows(limit=10000)
    leagues, teams = {}, {}
    for r in rows:
        if r.get("result_status") not in {"win", "loss"}:
            continue
        league = _norm(r.get("competition"))
        home, away = _norm(r.get("home_team")), _norm(r.get("away_team"))
        if league:
            leagues.setdefault(league, []).append(r)
        for team in {home, away}:
            if team:
                teams.setdefault(team, []).append(r)
    return {
        "leagues": {k: _stat(v) for k, v in leagues.items() if len(v) >= 20},
        "teams": {k: _stat(v) for k, v in teams.items() if len(v) >= 12},
    }


def apply_contextual_learning(candidates, extracted, research):
    """Small league/team correction only after enough verified settled tips exist."""
    mem = _memory()
    match = extracted.get("match", {}) or {}
    league = _norm(extracted.get("competition") or research.get("competition"))
    home = _norm(match.get("home_team") or research.get("home_team"))
    away = _norm(match.get("away_team") or research.get("away_team"))
    stats = []
    if mem["leagues"].get(league): stats.append(mem["leagues"][league])
    if mem["teams"].get(home): stats.append(mem["teams"][home])
    if mem["teams"].get(away): stats.append(mem["teams"][away])
    web = extracted.get("web_context") or {}
    web_conf = _clamp(web.get("data_confidence", 0.0), 0.0, 1.0) if web else 0.0
    if not stats and web_conf <= 0.15:
        return list(candidates or [])
    hist_adjustment = _clamp(sum(s["adjustment"] for s in stats) / len(stats), -0.025, 0.025) if stats else 0.0
    adjustment = hist_adjustment
    if web_conf > 0.15:
        hs=float(web.get("home_strength",.5)); aas=float(web.get("away_strength",.5))
        hf=float(web.get("home_recent_form",.5)); af=float(web.get("away_recent_form",.5))
        contextual_edge=((hs+hf)-(aas+af))/4.0
        adjustment += _clamp(contextual_edge * 0.05 * web_conf, -0.03, 0.03)
    adjustment = _clamp(adjustment, -0.04, 0.04)
    sample = sum(s["sample"] for s in stats)
    out = []
    for original in candidates or []:
        c = dict(original)
        old = float(c.get("model_probability") or 0.5)
        joined=(str(c.get("market") or "")+" "+str(c.get("selection") or "")).lower()
        local_adj=adjustment
        if web_conf > 0.15:
            away_side = bool(re.search(r"\b(team\s*2|away|w2|2x)\b", joined)) and not bool(re.search(r"\b1x2\b", joined))
            home_side = bool(re.search(r"\b(team\s*1|home|w1|1x)\b", joined))
            if away_side and not home_side:
                local_adj=-adjustment
            if "total" in joined or "score" in joined or "btts" in joined:
                goal=((float(web.get("home_scoring_rate",.5))+float(web.get("away_scoring_rate",.5))+float(web.get("league_goal_rate",.5)))/3)-.5
                sign=-1 if "under" in joined or " no" in joined else 1
                local_adj=_clamp(sign*goal*0.05*web_conf,-.035,.035)
        new = _clamp(old + local_adj, 0.01, 0.99)
        c["context_learning_adjustment"] = local_adj
        c["context_learning_sample"] = sample
        c["model_probability"] = new
        if c.get("market_probability") is not None:
            c["edge"] = new - float(c["market_probability"])
        if not c.get("odds_estimated") and c.get("odds"):
            c["expected_value"] = new * float(c["odds"]) - 1.0
        c["ranking_score"] = float(c.get("ranking_score") or 0) + (new-old)*0.35
        out.append(c)
    return sorted(out, key=lambda x: float(x.get("ranking_score") or 0), reverse=True)


def no_bet_gate(best, extracted, research, audit=None):
    """Mandatory-tip policy for valid analyzable pre-bet matches.

    V20 never rejects a ranked candidate merely because evidence is sparse,
    probability is modest, the price is short, EV is negative, or sources conflict.
    Those factors remain inside ranking/confidence, so the engine still chooses the
    best available candidate rather than fabricating certainty.

    Returning a reason is reserved for the true no-candidate/input-failure case;
    callers already ask the user for a clearer screenshot when no tip exists.
    """
    if not best:
        return ["No supported market could be extracted"]
    return []



def _candidate_thesis(candidate):
    """Group different bookmaker markets by the football idea they express."""
    market = _norm(candidate.get("market_name"))
    selection = _norm(candidate.get("selection"))
    joined = f"{market} {selection}"
    family = _norm(candidate.get("market_family"))

    # Goal environment.
    if (
        ("under" in selection and "total" in market)
        or ("both teams to score" in market and re.search(r"\bno\b", selection))
        or ("btts" in market and re.search(r"\bno\b", selection))
        or ("each team to score" in joined and re.search(r"\bno\b", selection))
        or ("win to nil" in market and not re.search(r"\bno\b", selection))
    ):
        return "lower_scoring"

    if (
        ("over" in selection and "total" in market)
        or ("both teams to score" in market and re.search(r"\byes\b", selection))
        or ("btts" in market and re.search(r"\byes\b", selection))
        or ("each team to score" in joined and re.search(r"\byes\b", selection))
    ):
        return "higher_scoring"

    # Team-strength ideas also cover handicaps, team totals and result combos.
    if (
        selection in {"w1", "1", "home", "home win", "1x", "x1"}
        or re.search(r"\bw1\b|\bteam\s*1\b|\bhome\b", joined)
    ):
        if "under" not in selection:
            return "home_strength"

    if (
        selection in {"w2", "2", "away", "away win", "2x", "x2"}
        or re.search(r"\bw2\b|\bteam\s*2\b|\baway\b", joined)
    ):
        if "under" not in selection:
            return "away_strength"

    return family or None

def _price_quality_adjustment(odds):
    """V20 SAFE BIG ODD price shaping.

    Final selection has a hard 1.50 floor. Price itself is never allowed to dominate
    football probability: the preferred zone is 1.50-2.80, while very large prices
    are progressively penalized because they normally imply lower hit probability.
    """
    if not odds or odds <= 1.0:
        return -1.000
    if odds < 1.50:
        return -0.850
    if odds <= 2.05:
        return 0.090
    if odds <= 2.40:
        return 0.078
    if odds <= 2.80:
        return 0.060
    if odds <= 3.20:
        return 0.030
    if odds < 4.00:
        return -0.020
    if odds < 5.00:
        return -0.080
    return -0.150




def _bookie_trap_metrics(candidate):
    """Estimate whether a bookmaker price is unattractive for OUR model.

    This does not claim intentional manipulation.  It compares the independent
    football-model probability with the quoted break-even probability and the
    de-vigged market probability.  The result is used as a strong price-risk
    penalty, never as a reason to skip the match.
    """
    odds = float(candidate.get("odds") or 0.0)
    push = _clamp(candidate.get("push_probability") or 0.0, 0.0, 0.90)
    supported = bool(candidate.get("model_supported"))

    independent_p = candidate.get("raw_model_probability")
    if independent_p is None:
        independent_p = candidate.get("model_probability")
    independent_p = _clamp(independent_p or 0.5, 0.005, 0.995)

    market_p = candidate.get("market_probability")
    market_p = None if market_p is None else _clamp(market_p, 0.005, 0.995)
    evidence = _clamp(candidate.get("evidence_confidence") or 0.0, 0.0, 1.0)
    base_risk = max(0.0, float(candidate.get("risk_penalty") or 0.0))

    # Model-derived/outside markets do not have a real bookmaker quote yet. Their
    # "odds" field is the minimum take threshold, so do NOT call it a bookmaker
    # trap. Score price-threshold safety from probability/evidence/risk instead.
    if candidate.get("odds_estimated"):
        if odds <= 1.0:
            odds = float(candidate.get("minimum_acceptable_odds") or 1.50)
        break_even = _clamp((1.0 - push) / odds, 0.005, 0.995)
        threshold_ev = independent_p * odds + push - 1.0
        fair_odds = max(1.01, (1.0 - push) / max(independent_p, 0.005))
        uncertainty = (1.0 - evidence) * 0.24 + min(0.22, base_risk * 0.42)
        availability = str(candidate.get("price_availability") or "CHECK_PRICE")
        actionable = bool(candidate.get("price_actionable"))
        reality = _clamp(candidate.get("price_reality_score") or 0.0, 0.0, 1.0)
        if not actionable:
            uncertainty += 0.18
        elif availability == "POSSIBLE":
            uncertainty += 0.035
        uncertainty += (1.0 - reality) * 0.10
        if independent_p < 0.46:
            uncertainty += 0.10
        elif independent_p < 0.50:
            uncertainty += 0.05
        trap = _clamp(uncertainty, 0.0, 1.0)
        level = "LOW" if trap <= 0.18 else ("MEDIUM" if trap <= 0.36 else ("HIGH" if trap <= 0.58 else "VERY_HIGH"))
        return {
            "independent_model_probability": independent_p,
            "bookmaker_break_even_probability": break_even,
            # No real quote exists yet. A positive EV at the Take Odds threshold is
            # circular and must not reward ranking. Keep it separately for audit.
            "independent_expected_value": 0.0,
            "threshold_expected_value": threshold_ev,
            "model_market_gap": None,
            "model_fair_odds": fair_odds,
            "bookie_trap_risk": trap,
            "bookie_trap_level": level,
            "price_threshold_only": True,
        }

    if odds <= 1.0:
        return {
            "independent_model_probability": independent_p,
            "bookmaker_break_even_probability": 0.995,
            "independent_expected_value": -1.0,
            "model_market_gap": None,
            "model_fair_odds": None,
            "bookie_trap_risk": 1.0,
            "bookie_trap_level": "HIGH",
        }

    break_even = _clamp((1.0 - push) / odds, 0.005, 0.995)
    independent_ev = independent_p * odds + push - 1.0
    fair_odds = max(1.01, (1.0 - push) / max(independent_p, 0.005))
    gap = None if market_p is None else independent_p - market_p
    overpriced_gap = max(0.0, break_even - independent_p)

    # Strongest signal: our independent probability cannot cover the offered price.
    trap = 0.0
    if independent_ev < 0.0:
        trap += min(0.42, -independent_ev * 1.55)
    if independent_ev < -0.08:
        trap += min(0.18, (-independent_ev - 0.08) * 0.85)
    trap += min(0.28, overpriced_gap * 2.20)

    # A de-vigged bookmaker consensus materially above our model can mean the
    # attractive-looking side is actually too expensive for our view of the game.
    if gap is not None and gap < -0.035:
        trap += min(0.20, (-gap - 0.035) * 1.45)

    # Huge model/market disagreement in sparse evidence is dangerous in either
    # direction: it may be value, but it may also be model misspecification.
    if gap is not None and abs(gap) > 0.14 and evidence < 0.60:
        trap += min(0.12, (abs(gap) - 0.14) * 0.70)

    if not supported:
        trap += 0.16
    if evidence < 0.35:
        trap += 0.08
    elif evidence < 0.50:
        trap += 0.035

    # Existing family/competition/longshot risk still matters.
    trap += min(0.16, base_risk * 0.42)
    if odds >= 5.0:
        trap += 0.10
    elif odds >= 4.0:
        trap += 0.06
    elif odds >= 3.2:
        trap += 0.025

    trap = _clamp(trap, 0.0, 1.0)
    if trap <= 0.18 and independent_ev >= -0.02:
        level = "LOW"
    elif trap <= 0.36 and independent_ev >= -0.08:
        level = "MEDIUM"
    elif trap <= 0.58:
        level = "HIGH"
    else:
        level = "VERY_HIGH"

    return {
        "independent_model_probability": independent_p,
        "bookmaker_break_even_probability": break_even,
        "independent_expected_value": independent_ev,
        "model_market_gap": gap,
        "model_fair_odds": fair_odds,
        "bookie_trap_risk": trap,
        "bookie_trap_level": level,
    }

def apply_selection_intelligence(candidates, extracted=None, research=None, audit=None):
    """V20.3 open-market selector with independent-model price protection.

    Screenshot quotes and outside/model-derived markets compete on one safety scale.
    A real quote must clear 1.50; an outside market carries a calculated minimum
    take threshold and may win even when real 1.50+ screenshot quotes exist.
    """
    audit = audit or {}
    out = []

    for original in candidates or []:
        c = dict(original)
        p = _clamp(c.get("model_probability") or 0.5, 0.01, 0.99)
        evidence = _clamp(c.get("evidence_confidence") or 0.0, 0.0, 1.0)
        odds = float(c.get("odds") or 0.0)
        ev = float(c.get("expected_value") or 0.0)
        edge = float(c.get("edge") or 0.0)
        risk = max(0.0, float(c.get("risk_penalty") or 0.0))
        supported = bool(c.get("model_supported"))

        trap_metrics = _bookie_trap_metrics(c)
        c.update(trap_metrics)
        independent_p = float(c.get("independent_model_probability") or p)
        independent_ev = float(c.get("independent_expected_value") or 0.0)
        trap_risk = float(c.get("bookie_trap_risk") or 0.0)

        # Accuracy remains first. The price floor is a constraint, not a reason to
        # chase the highest odd. This deliberately favors the safest 1.50+ option.
        score = p * 0.620 + evidence * 0.150
        score += max(-0.045, min(0.050, ev * 0.20))
        score += max(-0.018, min(0.018, edge * 0.09))
        score -= min(0.115, risk * 0.16)

        if not c.get("odds_estimated") and odds > 1.0:
            # Only a REAL bookmaker quote may earn a price/value bonus. A derived
            # Take Odds threshold is not a price and must never behave like one.
            win_profit_mass = p * (odds - 1.0)
            score += min(0.035, win_profit_mass * 0.10)
            score += _price_quality_adjustment(odds)
        elif c.get("odds_estimated"):
            reality = _clamp(c.get("price_reality_score") or 0.0, 0.0, 1.0)
            score += (reality - 0.50) * 0.08
            if not c.get("price_actionable"):
                score -= 0.20

        # V20.2 BOOKIE TRAP GUARD.  The independent football model, not the
        # bookmaker-anchored probability, decides whether a price is suspicious.
        # A negative independent EV or a large break-even gap is heavily demoted.
        score += max(-0.085, min(0.060, independent_ev * 0.34))
        score += max(-0.030, min(0.030, (independent_p - p) * 0.15))
        score -= trap_risk * 0.34

        # V20.4 keeps the open market universe, but an outside market must have
        # a realistic path to its required Take Odds. No synthetic-price bonus.
        if not c.get("odds_estimated"):
            score += 0.012 if independent_ev >= -0.02 else -0.010
        else:
            availability = str(c.get("price_availability") or "CHECK_PRICE")
            if availability == "LIKELY":
                score += 0.014
            elif availability == "POSSIBLE":
                score += 0.004
            else:
                score -= 0.080

        # V19.5 broad score-model support gets the same trust treatment as familiar
        # families; bookmaker-anchor-only markets stay eligible but carry uncertainty.
        if supported:
            score += 0.028
            if c.get("model_source") == "score_model":
                score += 0.006
        else:
            score -= 0.040

        if p < 0.45:
            score -= 0.135
        elif p < 0.50:
            score -= 0.090
        elif p < 0.55:
            score -= 0.052
        elif p >= 0.72:
            score += 0.020
        elif p >= 0.64:
            score += 0.010

        if audit.get("contradiction"):
            score -= 0.025 + (1.0 - evidence) * 0.030

        # Hard product floor. For outside markets `odds` is a model TAKE threshold,
        # not a fabricated quote. For real screenshot markets it is the actual quote.
        if odds < 1.50:
            c["single_bet_ineligible"] = True
            c["single_bet_ineligible_reason"] = "ODDS_BELOW_1_50"
            score -= 1.0
        else:
            c["single_bet_ineligible"] = False
            c["single_bet_ineligible_reason"] = None
        c["safe_big_odd_eligible"] = bool(odds >= 1.50)

        c["market_thesis"] = _candidate_thesis(c)
        c["price_quality_adjustment"] = 0.0 if c.get("odds_estimated") else _price_quality_adjustment(odds)
        c["selection_intelligence_score"] = score
        c["selection_intelligence_version"] = "V20.4"
        out.append(c)

    if not out:
        return []

    def safety_score(c):
        return (
            float(c.get("independent_model_probability") or c.get("model_probability") or 0.0) * 0.60
            + float(c.get("model_probability") or 0.0) * 0.16
            + float(c.get("evidence_confidence") or 0.0) * 0.15
            + max(-0.05, min(0.05, float(c.get("independent_expected_value") or 0.0) * 0.16))
            - max(0.0, float(c.get("risk_penalty") or 0.0)) * 0.07
            - float(c.get("bookie_trap_risk") or 0.0) * 0.24
            + (0.025 if c.get("model_supported") else -0.020)
        )

    leader = max(out, key=safety_score)
    leader_odds = float(leader.get("odds") or 0.0)
    leader_p = float(leader.get("model_probability") or 0.0)
    leader_ev = float(leader.get("expected_value") or 0.0)
    thesis = leader.get("market_thesis")

    if leader_odds and leader_odds < 1.50 and not leader.get("odds_estimated"):
        # The safest raw thesis may be a short-priced market. Upgrade to a nearby
        # expression of the same idea that clears 1.50 without sacrificing too much
        # model probability.
        min_related_p = max(0.46, leader_p - 0.20)
        for c in out:
            if c is leader:
                continue
            odds = float(c.get("odds") or 0.0)
            p = float(c.get("model_probability") or 0.0)
            evidence = float(c.get("evidence_confidence") or 0.0)
            if not (1.50 <= odds <= 3.20 and p >= min_related_p):
                continue
            if evidence + 0.20 < float(leader.get("evidence_confidence") or 0.0):
                continue

            same_thesis = thesis is not None and c.get("market_thesis") == thesis
            materially_better_value = float(c.get("expected_value") or 0.0) >= leader_ev + 0.030

            if same_thesis and c.get("model_supported"):
                c["selection_intelligence_score"] += 0.135
                c["nearby_market_upgrade"] = True
                c["nearby_market_from"] = {
                    "market_name": leader.get("market_name"),
                    "selection": leader.get("selection"),
                    "odds": leader_odds,
                }
            elif c.get("model_supported") and materially_better_value and p >= max(0.50, leader_p - 0.15):
                c["selection_intelligence_score"] += 0.060
                c["value_upgrade"] = True

    return sorted(
        out,
        key=lambda x: float(x.get("selection_intelligence_score") or -999),
        reverse=True,
    )

