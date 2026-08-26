"""V19 accuracy intelligence layer.

Adds bounded, sample-gated league/team outcome memory and a mandatory best-available-tip policy.
It does not add network calls and therefore does not alter the V18 speed path.
"""
from functools import lru_cache
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
    """Map different bookmaker markets to the same football idea.

    This lets the selector move from a very short 'safe' price to a nearby,
    better-paying market when both are driven by the same match thesis.
    """
    market = _norm(candidate.get("market_name"))
    selection = _norm(candidate.get("selection"))
    joined = f"{market} {selection}"

    if (
        ("total" in market and "under" in selection)
        or ("both teams to score" in market and selection in {"no", "n"})
        or ("btts" in market and selection in {"no", "n"})
        or ("each team to score" in market and "2" in market and selection in {"no", "n"})
        or ("each team to score" in joined and "2" in joined and joined.endswith(" no"))
    ):
        return "lower_scoring"

    if (
        ("total" in market and "over" in selection)
        or ("both teams to score" in market and selection in {"yes", "y"})
        or ("btts" in market and selection in {"yes", "y"})
        or ("each team to score" in market and "2" in market and selection in {"yes", "y"})
    ):
        return "higher_scoring"

    if market == "1x2" and selection.lower() in {"w1", "1", "home", "home win"}:
        return "home_strength"
    if "double chance" in market and selection.lower() in {"1x", "x1"}:
        return "home_strength"
    if market == "1x2" and selection.lower() in {"w2", "2", "away", "away win"}:
        return "away_strength"
    if "double chance" in market and selection.lower() in {"2x", "x2"}:
        return "away_strength"
    return None


def _price_quality_adjustment(odds):
    """Reward usable single-bet prices and strongly demote tiny payouts.

    1.20 remains acceptable as requested, but the sweet spot starts around 1.25.
    Nothing is hard-banned because the product still has a mandatory-tip policy.
    """
    if not odds or odds <= 1.0:
        return -0.10
    if odds < 1.08:
        return -0.180
    if odds < 1.15:
        return -0.125
    if odds < 1.20:
        return -0.075
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
    """V19.4 value-aware single-bet selector.

    The old selector could choose 1.05-1.10 because raw win probability dominated
    everything else. V19.4 keeps accuracy important but also asks whether the
    payout is worth taking. When a short-price leader has a nearby market built on
    the same football thesis (for example low-scoring -> Under 3), a practical
    1.20+ alternative can overtake it if probability/evidence remain respectable.

    This is still mandatory-tip: low odds are demoted, never converted to NO BET.
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

        # Accuracy still leads, but price/value now has enough weight to stop
        # '85% @ 1.069' from automatically beating a sensible 1.25-1.60 option.
        score = p * 0.585 + evidence * 0.135
        score += max(-0.045, min(0.045, ev * 0.22))
        score += max(-0.018, min(0.018, edge * 0.08))
        score -= min(0.080, risk * 0.10)

        # Expected profit on a WIN (not EV) captures the user's practical point:
        # a 1.06 winner barely pays anything even when its hit chance is high.
        if odds > 1.0:
            win_profit_mass = p * (odds - 1.0)
            score += min(0.055, win_profit_mass * 0.20)

        score += _price_quality_adjustment(odds)
        score += 0.030 if not c.get("odds_estimated") else -0.030
        score += 0.018 if c.get("model_supported") else -0.025

        if p < 0.45:
            score -= 0.125
        elif p < 0.50:
            score -= 0.085
        elif p < 0.55:
            score -= 0.050
        elif p >= 0.72:
            score += 0.020
        elif p >= 0.64:
            score += 0.010

        if audit.get("contradiction"):
            score -= 0.025 + (1.0 - evidence) * 0.030

        c["market_thesis"] = _candidate_thesis(c)
        c["price_quality_adjustment"] = _price_quality_adjustment(odds)
        c["selection_intelligence_score"] = score
        c["selection_intelligence_version"] = "V19.4"
        out.append(c)

    if not out:
        return []

    # Find the raw safety leader before the nearby-market upgrade.
    def safety_score(c):
        return (
            float(c.get("model_probability") or 0.0) * 0.78
            + float(c.get("evidence_confidence") or 0.0) * 0.16
            - max(0.0, float(c.get("risk_penalty") or 0.0)) * 0.08
            + (0.02 if c.get("model_supported") else -0.01)
        )

    leader = max(out, key=safety_score)
    leader_odds = float(leader.get("odds") or 0.0)
    leader_p = float(leader.get("model_probability") or 0.0)
    leader_ev = float(leader.get("expected_value") or 0.0)
    thesis = leader.get("market_thesis")

    if leader_odds and leader_odds < 1.20:
        # A related 1.20+ market may replace the tiny-price safety pick when it
        # retains enough probability.  20 percentage points is the maximum
        # safety sacrifice; below 55% it is not considered a sensible substitute.
        min_related_p = max(0.55, leader_p - 0.20)
        for c in out:
            if c is leader:
                continue
            odds = float(c.get("odds") or 0.0)
            p = float(c.get("model_probability") or 0.0)
            evidence = float(c.get("evidence_confidence") or 0.0)
            if not (1.20 <= odds <= 2.60 and p >= min_related_p):
                continue
            if evidence + 0.20 < float(leader.get("evidence_confidence") or 0.0):
                continue

            same_thesis = thesis is not None and c.get("market_thesis") == thesis
            materially_better_value = float(c.get("expected_value") or 0.0) >= leader_ev + 0.035
            if same_thesis:
                c["selection_intelligence_score"] += 0.095
                c["nearby_market_upgrade"] = True
                c["nearby_market_from"] = {
                    "market_name": leader.get("market_name"),
                    "selection": leader.get("selection"),
                    "odds": leader_odds,
                }
            elif c.get("model_supported") and materially_better_value and p >= max(0.58, leader_p - 0.15):
                c["selection_intelligence_score"] += 0.045
                c["value_upgrade"] = True

    return sorted(
        out,
        key=lambda x: float(x.get("selection_intelligence_score") or -999),
        reverse=True,
    )

