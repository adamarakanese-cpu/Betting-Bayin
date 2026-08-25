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
