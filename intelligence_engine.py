"""V20 SAFE BIG ODD intelligence layer.

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

    Final selection has a hard 1.80 floor. Price itself is never allowed to dominate
    football probability: the preferred zone is 1.80-2.80, while very large prices
    are progressively penalized because they normally imply lower hit probability.
    """
    if not odds or odds <= 1.0:
        return -1.000
    if odds < 1.80:
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



def apply_selection_intelligence(candidates, extracted=None, research=None, audit=None):
    """V20 SAFE BIG ODD single-bet selector.

    The final target is one actionable Single Bet with an internal/real price >=1.80.
    Within that price floor, probability, evidence quality and risk remain more important
    than raw odds. Weak matches are not converted to NO BET; they receive lower grades.
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

        # Accuracy remains first. The price floor is a constraint, not a reason to
        # chase the highest odd. This deliberately favors the safest 1.80+ option.
        score = p * 0.620 + evidence * 0.150
        score += max(-0.045, min(0.050, ev * 0.20))
        score += max(-0.018, min(0.018, edge * 0.09))
        score -= min(0.115, risk * 0.16)

        if odds > 1.0:
            # Small value reward only; raw return must never overwhelm hit probability.
            win_profit_mass = p * (odds - 1.0)
            score += min(0.035, win_profit_mass * 0.10)

        score += _price_quality_adjustment(odds)
        # Real bookmaker confirmation is useful, but derived markets remain valid
        # when the screenshot does not expose a suitable 1.80+ quote.
        score += 0.024 if not c.get("odds_estimated") else -0.018

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

        # V20 HARD FLOOR: both real quotes and private derived-price estimates must
        # clear 1.80 before they can become the final SAFE BIG ODD Single Tip.
        # Sub-1.80 candidates stay in diagnostics because they can identify the safest
        # football thesis and help us upgrade to a nearby 1.80+ market.
        if 1.0 < odds < 1.80:
            c["single_bet_ineligible"] = True
            c["single_bet_ineligible_reason"] = "ODDS_BELOW_1_80"
            score -= 1.0
        else:
            c["single_bet_ineligible"] = False
            c["single_bet_ineligible_reason"] = None
        c["safe_big_odd_eligible"] = bool(odds >= 1.80)

        c["market_thesis"] = _candidate_thesis(c)
        c["price_quality_adjustment"] = _price_quality_adjustment(odds)
        c["selection_intelligence_score"] = score
        c["selection_intelligence_version"] = "V20.0"
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

    if leader_odds and leader_odds < 1.80:
        # The safest raw thesis may be a short-priced market. Upgrade to a nearby
        # expression of the same idea that clears 1.80 without sacrificing too much
        # model probability.
        min_related_p = max(0.46, leader_p - 0.20)
        for c in out:
            if c is leader:
                continue
            odds = float(c.get("odds") or 0.0)
            p = float(c.get("model_probability") or 0.0)
            evidence = float(c.get("evidence_confidence") or 0.0)
            if not (1.80 <= odds <= 3.20 and p >= min_related_p):
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

