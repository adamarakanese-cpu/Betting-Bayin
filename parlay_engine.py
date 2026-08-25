import itertools
import math


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _match_key(row):
    return (
        str(row.get("home_team") or "").strip().lower(),
        str(row.get("away_team") or "").strip().lower(),
    )



def _display_market(market, selection):
    market = str(market or "Market").strip()
    selection = str(selection or "").strip()
    low = market.lower()
    period = "Regular Time"
    base = market
    if low.startswith("1st half "):
        period, base = "1st Half", market[len("1st Half "):].strip()
    elif low.startswith("first half "):
        period, base = "1st Half", market[len("First Half "):].strip()
    elif low.startswith("2nd half "):
        period, base = "2nd Half", market[len("2nd Half "):].strip()
    elif low.startswith("second half "):
        period, base = "2nd Half", market[len("Second Half "):].strip()
    elif low.startswith("regular time "):
        period, base = "Regular Time", market[len("Regular Time "):].strip()

    if base.lower() == "total":
        return f"{period} — {selection}"
    return f"{period} — {base} — {selection}" if selection else f"{period} — {base}"

def _leg_quality(row):
    p = max(0.01, min(0.99, _f(row.get("model_probability"), 0.0)))
    evidence = max(0.0, min(1.0, _f(row.get("evidence_confidence"), 0.0)))
    odds = max(1.01, _f(row.get("odds"), 1.01))
    estimated = bool(row.get("odds_estimated"))

    score = p * 0.66 + evidence * 0.24
    if 1.15 <= odds <= 2.20:
        score += 0.05
    elif odds >= 3.0:
        score -= 0.08
    elif odds < 1.08:
        score -= 0.06
    if estimated:
        score -= 0.035
    return score


def _dedupe_matches(rows):
    """Keep only the strongest latest tip per match."""
    best = {}
    for row in rows:
        key = _match_key(row)
        if not all(key):
            continue
        if key not in best or _leg_quality(row) > _leg_quality(best[key]):
            best[key] = row
    return list(best.values())


def build_best_parlay(rows, requested_pool_size=None):
    """Choose the best 2-4 leg accumulator from the supplied recent-tip pool.

    The user's N matches are treated as a candidate pool. We do not force all N
    into the accumulator, because one weak leg can destroy the combined chance.
    """
    rows = _dedupe_matches(list(rows or []))
    if len(rows) < 2:
        return None

    # Safety gate: prefer legs at 55%+; if too few, relax carefully to 52%.
    safe = [r for r in rows if _f(r.get("model_probability")) >= 0.55]
    if len(safe) < 2:
        safe = [r for r in rows if _f(r.get("model_probability")) >= 0.52]
    if len(safe) >= 2:
        rows = safe

    rows = sorted(rows, key=_leg_quality, reverse=True)[:8]
    max_legs = min(4, len(rows))
    candidates = []

    for size in range(2, max_legs + 1):
        for combo in itertools.combinations(rows, size):
            probs = [max(0.01, min(0.99, _f(x.get("model_probability"), 0.01))) for x in combo]
            combined_p = math.prod(probs)
            avg_p = sum(probs) / size
            avg_evidence = sum(max(0.0, min(1.0, _f(x.get("evidence_confidence")))) for x in combo) / size
            estimated_count = sum(bool(x.get("odds_estimated")) for x in combo)

            odds_center = math.prod(max(1.01, _f(x.get("odds"), 1.01)) for x in combo)
            odds_low = math.prod(
                max(1.01, _f(x.get("estimated_odds_low"), _f(x.get("odds"), 1.01)))
                if bool(x.get("odds_estimated")) else max(1.01, _f(x.get("odds"), 1.01))
                for x in combo
            )
            odds_high = math.prod(
                max(1.01, _f(x.get("estimated_odds_high"), _f(x.get("odds"), 1.01)))
                if bool(x.get("odds_estimated")) else max(1.01, _f(x.get("odds"), 1.01))
                for x in combo
            )

            # Balance hit-rate and usable accumulator price. More legs are not
            # automatically better; uncertainty compounds quickly.
            price_bonus = min(0.10, max(0.0, math.log(max(1.0, odds_center), 10)) * 0.07)
            score = (
                combined_p * 0.52
                + avg_p * 0.20
                + avg_evidence * 0.18
                + price_bonus
                - estimated_count * 0.018
                - max(0, size - 3) * 0.025
            )
            candidates.append({
                "legs": list(combo),
                "combined_probability": combined_p,
                "combined_odds": odds_center,
                "combined_odds_low": odds_low,
                "combined_odds_high": odds_high,
                "contains_estimated_odds": estimated_count > 0,
                "score": score,
                "pool_size": requested_pool_size or len(rows),
            })

    return max(candidates, key=lambda x: x["score"]) if candidates else None


def format_parlay(parlay):
    if not parlay:
        return (
            "မောင်းတွဲဖို့ recent Pre-Bet Tip အနည်းဆုံး ၂ ပွဲလိုပါတယ်။\n"
            "Screenshot တွေတစ်ပွဲချင်းပို့ပြီးမှ ‘ခုနက 5 ပွဲကို မောင်းတွဲ’ လို့ပို့ပါ။"
        )

    lines = ["👑 BETTING BAYIN PRE-BET — BEST ACCUMULATOR", ""]
    for idx, leg in enumerate(parlay["legs"], 1):
        market = str(leg.get("market_name") or "Market")
        selection = str(leg.get("selection") or "")
        lines.append(f"{idx}. ⚽ {leg.get('home_team')} vs {leg.get('away_team')}")
        lines.append(f"   🎯 {_display_market(market, selection)}")
        if not bool(leg.get("odds_estimated")):
            lines.append(f"   💰 Odds: {_f(leg.get('odds')):.3f}")
        lines.append(f"   📊 Win Chance: {_f(leg.get('model_probability')) * 100:.0f}%")
        lines.append("")

    if not parlay["contains_estimated_odds"]:
        lines.append(f"💰 Combined Odds: {parlay['combined_odds']:.2f}")
    lines.append(f"📊 Combined Win Chance: {parlay['combined_probability'] * 100:.1f}%")
    lines.append(f"🧩 Selected: {len(parlay['legs'])} legs from recent {parlay['pool_size']} tips")
    return "\n".join(lines)
