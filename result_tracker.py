import re
import threading
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher

from database import (
    get_pending_predictions,
    mark_prediction_checked,
    settle_prediction_score,
)
from result_engine import market_family, market_period

_tracker_started = False
_tracker_lock = threading.Lock()


def _norm_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _similar(a, b):
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.72


def _int_score(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _date_for_sportsdb(raw):
    text = str(raw or "").strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            pass
    return None


def _lookup_thesportsdb(row):
    try:
        from sports_data import search_fixture, normalize_event
        date_text = _date_for_sportsdb(row.get("match_date_text"))
        events = search_fixture(row.get("home_team"), row.get("away_team"), date_text)
        for raw in events or []:
            event = normalize_event(raw)
            if not _similar(event.get("home_team"), row.get("home_team")):
                continue
            if not _similar(event.get("away_team"), row.get("away_team")):
                continue
            hs = _int_score(event.get("home_score"))
            aw = _int_score(event.get("away_score"))
            if hs is None or aw is None:
                continue
            status_text = str(event.get("status") or "").strip().lower()
            finished = any(token in status_text for token in ("finished", "full time", "final", " ft", "ft ")) or status_text == "ft"
            # Some historical TheSportsDB events have no status. A score from a
            # prior calendar day is safe enough; a same-day score is not.
            event_date = str(event.get("date") or "").strip()
            past_day = False
            try:
                past_day = datetime.strptime(event_date, "%Y-%m-%d").date() < datetime.now(timezone.utc).date()
            except ValueError:
                pass
            if not finished and not past_day:
                continue
            return {
                "status": "completed",
                "home_score": hs,
                "away_score": aw,
                "source": "TheSportsDB",
                "confidence": 0.93,
            }
    except Exception as error:
        print("⚠️ TheSportsDB result lookup:", repr(error))
    return None


def _lookup_web(row):
    try:
        from research_engine import call_research
        prompt = f"""
Verify the FINAL completed football result for exactly this fixture.

Home team: {row.get('home_team')}
Away team: {row.get('away_team')}
Competition: {row.get('competition') or 'unknown'}
Scheduled date: {row.get('match_date_text') or 'unknown'}

Use web search. We need the REGULAR-TIME / FULL-TIME score used for normal pre-match markets.
Do not use a score from another fixture, reserve side, youth age group, women/men team, extra time, or penalties.
If the match is not completed yet, return NOT_COMPLETED.
If the exact fixture cannot be verified confidently, return NOT_FOUND.
Never guess.

Return JSON only:
{{
  "status": "COMPLETED|NOT_COMPLETED|NOT_FOUND",
  "home_team": "",
  "away_team": "",
  "home_score": null,
  "away_score": null,
  "confidence": 0.0,
  "sources": ["https://..."]
}}
"""
        data = call_research(prompt)
        if not isinstance(data, dict):
            return None
        if str(data.get("status") or "").upper() != "COMPLETED":
            return {"status": str(data.get("status") or "not_found").lower()}
        if not _similar(data.get("home_team"), row.get("home_team")):
            return None
        if not _similar(data.get("away_team"), row.get("away_team")):
            return None
        hs = _int_score(data.get("home_score"))
        aw = _int_score(data.get("away_score"))
        confidence = float(data.get("confidence") or 0.0)
        sources = [str(x) for x in (data.get("sources") or []) if str(x).startswith("http")]
        if hs is None or aw is None or confidence < 0.85 or not sources:
            return None
        return {
            "status": "completed",
            "home_score": hs,
            "away_score": aw,
            "source": sources[0],
            "confidence": confidence,
        }
    except Exception as error:
        print("⚠️ Web result lookup:", repr(error))
        return None


def lookup_final_score(row):
    # Do not spend external calls on a fixture whose stated date is still in the future.
    date_text = _date_for_sportsdb(row.get("match_date_text"))
    if date_text:
        try:
            match_day = datetime.strptime(date_text, "%d.%m.%Y").date()
            if match_day > datetime.now(timezone.utc).date():
                return {"status": "not_completed"}
        except ValueError:
            pass

    # Fast/free structured source first; verified web-search fallback for lower leagues.
    result = _lookup_thesportsdb(row)
    if result:
        return result
    return _lookup_web(row)


def check_pending_results(limit=4, force=False):
    rows = get_pending_predictions(
        limit=max(1, min(int(limit or 4), 20)),
        min_age_hours=0.0 if force else 2.5,
        recheck_after_hours=0.0 if force else 6.0,
    )
    summary = {"checked": 0, "settled": 0, "unresolved": 0, "pending": len(rows)}
    for row in rows:
        summary["checked"] += 1
        # We only have verified final/full-time scores in the automatic tracker.
        # Do not settle 1st/2nd-half markets with a final score.
        if market_period(row.get("market_name")) != "regular_time":
            mark_prediction_checked(row["id"], note="period_result_requires_manual_settlement")
            summary["unresolved"] += 1
            continue
        lookup = lookup_final_score(row)
        if not lookup or lookup.get("status") != "completed":
            mark_prediction_checked(row["id"], note=(lookup or {}).get("status") if lookup else "not_found")
            continue
        settled = settle_prediction_score(
            row["id"],
            lookup["home_score"],
            lookup["away_score"],
            source=lookup.get("source") or "verified_result",
            confidence=float(lookup.get("confidence") or 0.0),
        )
        if settled and settled.get("result_status") in {"win", "loss", "void"}:
            summary["settled"] += 1
        else:
            summary["unresolved"] += 1
    return summary


def _tracker_loop(interval_seconds):
    # Allow startup/deploy to settle before external calls.
    time.sleep(90)
    while True:
        try:
            result = check_pending_results(limit=4, force=False)
            if result.get("checked"):
                print("📊 Result tracker:", result)
        except Exception as error:
            print("⚠️ Result tracker loop:", repr(error))
        time.sleep(interval_seconds)


def start_result_tracker(interval_seconds=3600):
    global _tracker_started
    with _tracker_lock:
        if _tracker_started:
            return
        _tracker_started = True
        thread = threading.Thread(
            target=_tracker_loop,
            args=(max(1800, int(interval_seconds)),),
            daemon=True,
            name="betting-bayin-result-tracker",
        )
        thread.start()
        print("📊 Automatic result tracking started")
