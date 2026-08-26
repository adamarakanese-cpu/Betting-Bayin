"""V19 accuracy intelligence layer.

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
    if not stats:
        return list(candidates or [])
    adjustment = _clamp(sum(s["adjustment"] for s in stats) / len(stats), -0.025, 0.025)
    sample = sum(s["sample"] for s in stats)
    out = []
    for original in candidates or []:
        c = dict(original)
        old = float(c.get("model_probability") or 0.5)
        new = _clamp(old + adjustment, 0.01, 0.99)
        c["context_learning_adjustment"] = adjustment
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

    V19.1 never rejects a ranked candidate merely because evidence is sparse,
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
    """Reward usable single-bet prices and strongly demote tiny payouts.

    1.20 remains acceptable as requested, but the sweet spot starts around 1.25.
    Nothing is hard-banned because the product still has a mandatory-tip policy.
    """
    if not odds or odds <= 1.0:
        return -0.10
    if odds < 1.08:
        return -0.420
    if odds < 1.15:
        return -0.360
    if odds < 1.20:
        return -0.300
    if odds < 1.25:
        return -0.015
    if odds <= 1.80:
        return 0.050
    if odds <= 2.20:
        return 0.040
    if odds <= 2.60:
        return 0.020
    if odds < 3.00:
        return 0.000
    if odds < 4.00:
        return -0.040
    return -0.085



def apply_selection_intelligence(candidates, extracted=None, research=None, audit=None):
    """V19.6 derived-market + hard-floor single-bet selector.

    Every readable market can compete on probability, evidence, price, EV and risk.
    There is no bonus for being W1/Total/BTTS and no artificial diversity/randomness.
    A Team Total, handicap, combo or half-market wins only when its risk-adjusted
    case is genuinely stronger.
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

        # Accuracy remains first, but a single bet must also pay enough to justify risk.
        score = p * 0.555 + evidence * 0.125
        score += max(-0.050, min(0.055, ev * 0.24))
        score += max(-0.020, min(0.020, edge * 0.10))
        score -= min(0.095, risk * 0.12)

        if odds > 1.0:
            win_profit_mass = p * (odds - 1.0)
            score += min(0.060, win_profit_mass * 0.21)

        score += _price_quality_adjustment(odds)
        score += 0.034 if not c.get("odds_estimated") else -0.034

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

        # V19.6 HARD FLOOR: a real screenshot quote below 1.20 is never
        # eligible for the final single bet. Keep it in diagnostics only so we can
        # compare its football thesis with better model-derived alternatives.
        if (not c.get("odds_estimated")) and 1.0 < odds < 1.20:
            c["single_bet_ineligible"] = True
            c["single_bet_ineligible_reason"] = "VISIBLE_ODDS_BELOW_1_20"
            score -= 1.0
        else:
            c["single_bet_ineligible"] = False

        c["market_thesis"] = _candidate_thesis(c)
        c["price_quality_adjustment"] = _price_quality_adjustment(odds)
        c["selection_intelligence_score"] = score
        c["selection_intelligence_version"] = "V19.6"
        out.append(c)

    if not out:
        return []

    def safety_score(c):
        return (
            float(c.get("model_probability") or 0.0) * 0.76
            + float(c.get("evidence_confidence") or 0.0) * 0.15
            - max(0.0, float(c.get("risk_penalty") or 0.0)) * 0.09
            + (0.025 if c.get("model_supported") else -0.020)
        )

    leader = max(out, key=safety_score)
    leader_odds = float(leader.get("odds") or 0.0)
    leader_p = float(leader.get("model_probability") or 0.0)
    leader_ev = float(leader.get("expected_value") or 0.0)
    thesis = leader.get("market_thesis")

    if leader_odds and leader_odds < 1.20:
        min_related_p = max(0.55, leader_p - 0.20)
        for c in out:
            if c is leader:
                continue
            odds = float(c.get("odds") or 0.0)
            p = float(c.get("model_probability") or 0.0)
            evidence = float(c.get("evidence_confidence") or 0.0)
            if not (1.20 <= odds <= 2.80 and p >= min_related_p):
                continue
            if evidence + 0.20 < float(leader.get("evidence_confidence") or 0.0):
                continue

            same_thesis = thesis is not None and c.get("market_thesis") == thesis
            materially_better_value = float(c.get("expected_value") or 0.0) >= leader_ev + 0.030

            if same_thesis and c.get("model_supported"):
                c["selection_intelligence_score"] += 0.105
                c["nearby_market_upgrade"] = True
                c["nearby_market_from"] = {
                    "market_name": leader.get("market_name"),
                    "selection": leader.get("selection"),
                    "odds": leader_odds,
                }
            elif c.get("model_supported") and materially_better_value and p >= max(0.58, leader_p - 0.15):
                c["selection_intelligence_score"] += 0.050
                c["value_upgrade"] = True

    return sorted(
        out,
        key=lambda x: float(x.get("selection_intelligence_score") or -999),
        reverse=True,
    )

