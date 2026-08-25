import math

BASELINE_TOTAL_GOALS = 2.55


def _f(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _rate(value):
    x = _f(value)
    if x is None:
        return None
    if x > 1.0:
        x /= 100.0
    return _clamp(x, 0.0, 1.0)


def _valid_source_url(value):
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _recent_profile(matches):
    rows = []
    for match in matches or []:
        gf = _f(match.get("goals_for"))
        ga = _f(match.get("goals_against"))
        if gf is None or ga is None or gf < 0 or ga < 0:
            continue
        rows.append((gf, ga))

    if not rows:
        return {
            "sample_size": 0,
            "avg_goals_for": None,
            "avg_goals_against": None,
            "avg_total_goals": None,
            "over_1_5_rate": None,
            "over_2_5_rate": None,
            "over_3_5_rate": None,
            "btts_rate": None,
        }

    n = len(rows)
    totals = [gf + ga for gf, ga in rows]
    return {
        "sample_size": n,
        "avg_goals_for": round(sum(gf for gf, _ in rows) / n, 3),
        "avg_goals_against": round(sum(ga for _, ga in rows) / n, 3),
        "avg_total_goals": round(sum(totals) / n, 3),
        "over_1_5_rate": round(sum(1 for t in totals if t > 1.5) / n, 3),
        "over_2_5_rate": round(sum(1 for t in totals if t > 2.5) / n, 3),
        "over_3_5_rate": round(sum(1 for t in totals if t > 3.5) / n, 3),
        "btts_rate": round(sum(1 for gf, ga in rows if gf > 0 and ga > 0) / n, 3),
    }


def _web_profile(raw, minimum_sample=5):
    if not isinstance(raw, dict):
        return None

    sample = int(_f(raw.get("sample_size")) or 0)
    urls = raw.get("source_urls") or []
    if isinstance(urls, str):
        urls = [urls]
    single = raw.get("source_url")
    if single:
        urls = list(urls) + [single]
    urls = [str(x).strip() for x in urls if _valid_source_url(x)]

    avg_total = _f(raw.get("avg_total_goals"))
    avg_gf = _f(raw.get("avg_goals_for"))
    avg_ga = _f(raw.get("avg_goals_against"))

    if sample < minimum_sample or not urls:
        return None
    if avg_total is None and (avg_gf is None or avg_ga is None):
        return None

    if avg_total is None:
        avg_total = avg_gf + avg_ga

    return {
        "sample_size": sample,
        "avg_goals_for": avg_gf,
        "avg_goals_against": avg_ga,
        "avg_total_goals": _clamp(avg_total, 0.6, 5.5),
        "over_1_5_rate": _rate(raw.get("over_1_5_rate")),
        "over_2_5_rate": _rate(raw.get("over_2_5_rate")),
        "over_3_5_rate": _rate(raw.get("over_3_5_rate")),
        "btts_rate": _rate(raw.get("btts_rate")),
        "season": raw.get("season"),
        "style_tags": [str(x) for x in (raw.get("style_tags") or [])][:8],
        "source_urls": urls[:5],
    }


def _weighted_mean(pairs, default=None):
    usable = [(float(v), float(w)) for v, w in pairs if v is not None and w > 0]
    total_w = sum(w for _, w in usable)
    if total_w <= 0:
        return default
    return sum(v * w for v, w in usable) / total_w


def build_match_context_profile(research):
    """Build a conservative, evidence-based league/team goal environment profile.

    This does not pretend to contain every league/team in a static table. It combines:
    - verified recent match scores already gathered by the research pipeline,
    - verified league/team aggregate data when web search found a source,
    and returns bounded context signals for the probability model.
    """
    research = research or {}
    home_recent = _recent_profile(research.get("home_recent_matches") or [])
    away_recent = _recent_profile(research.get("away_recent_matches") or [])

    league = _web_profile(research.get("league_profile"), minimum_sample=10)
    home_web = _web_profile(research.get("home_team_profile"), minimum_sample=5)
    away_web = _web_profile(research.get("away_team_profile"), minimum_sample=5)

    total_pairs = [(BASELINE_TOTAL_GOALS, 0.55)]
    evidence_points = 0.0
    source_count = 0

    if home_recent["sample_size"]:
        total_pairs.append((home_recent["avg_total_goals"], min(0.18, 0.036 * home_recent["sample_size"])))
        evidence_points += min(0.18, 0.036 * home_recent["sample_size"])
    if away_recent["sample_size"]:
        total_pairs.append((away_recent["avg_total_goals"], min(0.18, 0.036 * away_recent["sample_size"])))
        evidence_points += min(0.18, 0.036 * away_recent["sample_size"])

    if league:
        w = min(0.34, 0.14 + league["sample_size"] / 500.0)
        total_pairs.append((league["avg_total_goals"], w))
        evidence_points += w
        source_count += len(league.get("source_urls") or [])
    if home_web:
        w = min(0.18, 0.08 + home_web["sample_size"] / 400.0)
        total_pairs.append((home_web["avg_total_goals"], w))
        evidence_points += w
        source_count += len(home_web.get("source_urls") or [])
    if away_web:
        w = min(0.18, 0.08 + away_web["sample_size"] / 400.0)
        total_pairs.append((away_web["avg_total_goals"], w))
        evidence_points += w
        source_count += len(away_web.get("source_urls") or [])

    target_total = _weighted_mean(total_pairs, BASELINE_TOTAL_GOALS)
    target_total = _clamp(target_total, 1.4, 4.2)

    # Estimate which side is more likely to contribute to the total. This is a
    # soft split only; the main strength/Elo model still decides team strength.
    home_attack = _weighted_mean([
        (home_recent.get("avg_goals_for"), 0.30),
        (away_recent.get("avg_goals_against"), 0.20),
        (home_web.get("avg_goals_for") if home_web else None, 0.25),
        (away_web.get("avg_goals_against") if away_web else None, 0.15),
    ], 1.35)
    away_attack = _weighted_mean([
        (away_recent.get("avg_goals_for"), 0.30),
        (home_recent.get("avg_goals_against"), 0.20),
        (away_web.get("avg_goals_for") if away_web else None, 0.25),
        (home_web.get("avg_goals_against") if home_web else None, 0.15),
    ], 1.15)

    attack_sum = max(0.2, home_attack + away_attack)
    home_goal_share = _clamp(home_attack / attack_sum, 0.30, 0.70)

    quality = _clamp(evidence_points / 0.95, 0.0, 1.0)
    if league:
        quality = max(quality, min(0.92, 0.45 + league["sample_size"] / 300.0))
    if not source_count:
        quality = min(quality, 0.62)

    high_scoring = target_total >= 2.90
    low_scoring = target_total <= 2.20

    return {
        "competition": research.get("competition"),
        "home_team": research.get("home_team"),
        "away_team": research.get("away_team"),
        "target_total_goals": round(target_total, 3),
        "goal_environment_multiplier": round(_clamp(target_total / BASELINE_TOTAL_GOALS, 0.82, 1.22), 3),
        "home_goal_share": round(home_goal_share, 3),
        "quality": round(quality, 3),
        "source_count": source_count,
        "high_scoring_environment": high_scoring,
        "low_scoring_environment": low_scoring,
        "home_recent": home_recent,
        "away_recent": away_recent,
        "league_profile": league,
        "home_team_profile": home_web,
        "away_team_profile": away_web,
        "style_summary": {
            "league": (league or {}).get("style_tags", []),
            "home": (home_web or {}).get("style_tags", []),
            "away": (away_web or {}).get("style_tags", []),
        },
    }
