import copy
import json
from datetime import datetime

from analysis_engine import analyze_betting_data
from data_engine import (
    get_research_cache,
    save_research_cache,
    openfootball_team_history,
)
from research_engine import research_match
from verification_engine import verify_research
from recovery_engine import recover_evidence
from strength_engine import calculate_match_strength
from probability_engine import calculate_match_probabilities
from calibration_engine import calibrate_probability_model
from value_engine import calculate_market_value
from v13_engine import build_v13_decision


# =========================================================
# BETTING BAYIN V12
# UNIFIED PIPELINE ENGINE
# =========================================================

PIPELINE_VERSION = "V15.0 FINAL PRE-BET"


def _required_match_fields(extracted_data):
    match = extracted_data.get("match", {}) or {}
    home = match.get("home_team")
    away = match.get("away_team")
    competition = extracted_data.get("competition")
    match_date = extracted_data.get("start_date")

    missing = []
    if not home:
        missing.append("home_team")
    if not away:
        missing.append("away_team")
    if not competition:
        missing.append("competition")
    if not match_date:
        missing.append("start_date")

    return home, away, competition, match_date, missing


def _load_or_research(home, away, competition, match_date, force_refresh=False):
    if not force_refresh:
        cached = get_research_cache(
            home,
            away,
            competition,
            match_date,
        )
        if cached:
            return cached, {
                "source": "cache",
                "cache_hit": True,
                "fresh_research_used": False,
            }

    structured_home = openfootball_team_history(
        home,
        competition,
        match_date,
    )
    structured_away = openfootball_team_history(
        away,
        competition,
        match_date,
    )

    raw_research = research_match(
        home_team=home,
        away_team=away,
        competition=competition,
        match_date=match_date,
    )

    if len(structured_home) >= 3:
        raw_research["home_recent_matches"] = structured_home

    if len(structured_away) >= 3:
        raw_research["away_recent_matches"] = structured_away

    verified = verify_research(raw_research)

    save_research_cache(
        home_team=home,
        away_team=away,
        competition=competition,
        match_date=match_date,
        payload=verified,
    )

    return verified, {
        "source": "fresh_research",
        "cache_hit": False,
        "fresh_research_used": True,
        "structured_home_matches": len(structured_home),
        "structured_away_matches": len(structured_away),
    }


def _run_models(market_analysis, research):
    strength = calculate_match_strength(research)
    probability = calculate_match_probabilities(strength)
    calibration = calibrate_probability_model(probability)
    value = calculate_market_value(
        market_analysis,
        calibration,
    )

    return {
        "strength": strength,
        "probability": probability,
        "calibration": calibration,
        "value": value,
    }


def _needs_recovery(model_result):
    value = model_result.get("value", {}) or {}
    calibration = model_result.get("calibration", {}) or {}

    decision = value.get("decision")
    suitability = (
        calibration.get("betting_suitability", {})
        .get("suitable_for_betting")
    )

    return (
        decision == "DATA_CONFLICT"
        or suitability == "NO"
    )


def run_full_pipeline(
    extracted_data,
    force_research_refresh=False,
    enable_recovery=True,
):
    """
    One-call Betting Bayin pipeline.

    Input:
        Vision-extracted screenshot JSON.

    Output:
        Market analysis + verified research + recovery +
        strength + probability + calibration + value decision.
    """

    if not isinstance(extracted_data, dict):
        raise ValueError("extracted_data must be a dict")

    home, away, competition, match_date, missing = (
        _required_match_fields(extracted_data)
    )

    if missing:
        return {
            "pipeline_version": PIPELINE_VERSION,
            "status": "INVALID_SCREENSHOT_DATA",
            "decision": "PASS",
            "reason": "Missing required screenshot fields: " + ", ".join(missing),
            "missing_fields": missing,
            "extracted_data": extracted_data,
        }

    sport = str(extracted_data.get("sport") or "").strip().lower()
    if sport and sport != "football":
        return {
            "pipeline_version": PIPELINE_VERSION,
            "status": "UNSUPPORTED_SPORT",
            "decision": "PASS",
            "reason": "Current model supports football only.",
            "extracted_data": extracted_data,
        }

    live = extracted_data.get("live", {}) or {}
    match_type = str(extracted_data.get("match_type") or "").strip().lower()
    if bool(live.get("is_live")) or "live" in match_type:
        return {
            "pipeline_version": PIPELINE_VERSION,
            "status": "LIVE_NOT_SUPPORTED",
            "decision": "PASS",
            "reason": "V15.0 FINAL PRE-BET supports pre-match screenshots only. Live screenshots are blocked.",
            "extracted_data": extracted_data,
        }

    market_analysis = analyze_betting_data(extracted_data)

    research, research_meta = _load_or_research(
        home,
        away,
        competition,
        match_date,
        force_refresh=force_research_refresh,
    )

    first_model = _run_models(
        market_analysis,
        research,
    )

    recovery_result = None
    final_research = research
    final_model = first_model

    if enable_recovery and _needs_recovery(first_model):
        recovery_result = recover_evidence(research)

        recovered_research = recovery_result.get("research") or research

        # Re-run only when recovery actually changed the accepted evidence.
        if recovery_result.get("improved"):
            final_research = recovered_research
            final_model = _run_models(
                market_analysis,
                final_research,
            )

    value = final_model.get("value", {}) or {}

    v13 = build_v13_decision(
        extracted_data,
        final_research,
        final_model["probability"],
        final_model["calibration"],
    )

    return {
        "pipeline_version": PIPELINE_VERSION,
        "status": "OK",
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "match": {
            "home_team": home,
            "away_team": away,
            "competition": competition,
            "match_date": match_date,
            "match_type": extracted_data.get("match_type"),
            "start_time": extracted_data.get("start_time"),
        },
        "research_meta": research_meta,
        "recovery": recovery_result,
        "market_analysis": market_analysis,
        "research": final_research,
        "strength": final_model["strength"],
        "probability": final_model["probability"],
        "calibration": final_model["calibration"],
        "value": value,
        "v13": v13,
        "decision": "TIP_READY" if v13.get("tip") else value.get("decision", "PASS"),
        "reason": value.get("reason", "No final reason available."),
        "extracted_data": extracted_data,
    }


def _pct(value):
    try:
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "N/A"


def _fmt_odds(value):
    try:
        return f"{float(value):.3f}"
    except Exception:
        return "N/A"


def _simple_reason(result):
    value = result.get("value", {}) or {}
    decision = value.get("decision", "PASS")
    confidence = (result.get("probability", {}) or {}).get("model_confidence", {}) or {}
    confidence_score = confidence.get("score")

    if decision == "DATA_CONFLICT":
        return "Market odds နဲ့ AI model အမြင် ကွာဟချက်ကြီးပြီး data ယုံကြည်မှု မလုံလောက်သေးလို့ ဒီပွဲကို မလောင်းပါ။"

    if decision == "PASS":
        return "လက်ရှိ data နဲ့ odds မှာ လုံလောက်တဲ့ value မတွေ့လို့ ဒီပွဲကို မလောင်းပါ။"

    if decision == "CAUTION":
        return "Value အနည်းငယ်ရှိပေမယ့် confidence မလုံလောက်သေးလို့ SKIP လုပ်တာပိုကောင်းပါတယ်။"

    if decision == "BET_CANDIDATE":
        return "Model confidence, market edge နဲ့ expected value စစ်ဆေးမှုတွေကို ဖြတ်ကျော်ထားပါတယ်။"

    if confidence_score is not None:
        return f"Model confidence {float(confidence_score)*100:.1f}% ဖြစ်ပါတယ်။"

    return value.get("reason", result.get("reason", ""))


def _selection_label(selection, home, away):
    labels = {
        "home_win": home,
        "draw": "Draw",
        "away_win": away,
    }
    return labels.get(selection, str(selection or "N/A"))


def _market_tip_text(value, home, away):
    best = value.get("best_selection") or {}
    market = (value.get("market") or {}).get("market_name") or "N/A"
    selection = best.get("selection")

    if not best:
        return "NO BET", None, None

    return (
        f"{market} - {_selection_label(selection, home, away)}",
        best.get("odds"),
        best.get("expected_value_percent"),
    )


def format_final_report(result):
    """Simple Telegram report intended for non-technical users."""

    if result.get("status") != "OK":
        return (
            "👑 BETTING BAYIN\n\n"
            "❌ NO BET\n\n"
            f"အကြောင်းရင်း: {result.get('reason', 'Screenshot data မလုံလောက်ပါ။')}"
        )

    match = result["match"]
    probability = result.get("probability", {}) or {}
    value = result.get("value", {}) or {}

    home = match["home_team"]
    away = match["away_team"]
    competition = match.get("competition") or "N/A"
    match_type_raw = str(match.get("match_type") or "Pre-match")
    match_type = "Pre Bet" if "live" not in match_type_raw.lower() else "Live"

    decision = value.get("decision", "PASS")
    confidence = probability.get("model_confidence", {}) or {}
    confidence_score = confidence.get("score")
    confidence_status = confidence.get("status", "N/A")

    tip_text, tip_odds, tip_ev = _market_tip_text(value, home, away)

    if decision == "BET_CANDIDATE":
        header = "✅ BETTING TIP"
        market_line = tip_text
    elif decision == "CAUTION":
        header = "🟡 SKIP / CAUTION"
        market_line = "NO BET"
    else:
        header = "❌ NO BET"
        market_line = "NO BET"

    lines = [
        "👑 BETTING BAYIN",
        "",
        header,
        "",
        f"⚽ ပွဲစဉ် (Match): {home} vs {away}",
        f"🏆 League: {competition}",
        f"🎫 လောင်းမည့်အမျိုးအစား (Bet Type): {match_type}",
        f"🎯 ရွေးချယ်ထားသော Market (Best Value Market): {market_line}",
    ]

    if decision == "BET_CANDIDATE" and tip_odds is not None:
        lines.append(f"💰 Odds: {_fmt_odds(tip_odds)}")
        if tip_ev is not None:
            lines.append(f"📈 Model EV: {float(tip_ev):+.1f}%")

    if confidence_score is not None:
        lines.append(
            f"🛡 ယုံကြည်မှု (Confidence): {float(confidence_score)*100:.1f}% ({confidence_status})"
        )

    lines.extend([
        "",
        f"📝 အကြောင်းရင်း: {_simple_reason(result)}",
    ])

    if decision != "BET_CANDIDATE":
        lines.extend([
            "",
            "🚫 Tip မပေးပါ — ဒီပွဲကို SKIP လုပ်ပါ။",
        ])

    return "\n".join(lines)
