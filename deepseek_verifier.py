import json
import os
import requests

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"


def _compact_research(research):
    return {
        "home_team": research.get("home_team"),
        "away_team": research.get("away_team"),
        "competition": research.get("competition"),
        "match_date": research.get("match_date"),
        "home_recent_matches": (research.get("home_recent_matches") or [])[:8],
        "away_recent_matches": (research.get("away_recent_matches") or [])[:8],
        "injuries": research.get("injuries"),
        "suspensions": research.get("suspensions"),
        "lineups": research.get("lineups"),
        "rest_and_schedule": research.get("rest_and_schedule"),
        "match_importance": research.get("match_importance"),
        "verification_quality": research.get("verification_quality"),
        "research_quality": research.get("research_quality"),
        "raw_research_errors": research.get("raw_research_errors"),
    }


def verify_model_context(research, probability):
    """DeepSeek is an evidence auditor, never the source of final probabilities."""
    if not DEEPSEEK_API_KEY:
        return {
            "enabled": False,
            "status": "NO_KEY",
            "quality_score": None,
            "warnings": ["DEEPSEEK_API_KEY not configured."],
            "contradiction": False,
        }

    payload = {
        "research": _compact_research(research),
        "model": {
            "expected_goals": probability.get("expected_goals"),
            "one_x_two": probability.get("one_x_two"),
            "totals": probability.get("totals"),
            "btts": probability.get("btts"),
            "model_confidence": probability.get("model_confidence"),
        },
    }

    system = (
        "You are a football evidence auditor. Do NOT invent injuries, results, lineups, odds, "
        "or probabilities. Audit only the supplied JSON. Return JSON only with keys: "
        "quality_score (0..1), contradiction (boolean), warnings (array of short strings), "
        "notes (array of short strings). quality_score measures whether the supplied evidence "
        "is coherent enough to trust the statistical model; it is not a match-win probability."
    )

    body = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": "Audit this JSON:\n" + json.dumps(payload, ensure_ascii=False)},
        ],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 700,
        "stream": False,
    }

    try:
        response = requests.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=(3.0, 8.0),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        score = float(data.get("quality_score", 0.5))
        return {
            "enabled": True,
            "status": "OK",
            "quality_score": max(0.0, min(1.0, score)),
            "contradiction": bool(data.get("contradiction", False)),
            "warnings": list(data.get("warnings") or []),
            "notes": list(data.get("notes") or []),
            "model": DEEPSEEK_MODEL,
        }
    except Exception as exc:
        return {
            "enabled": True,
            "status": "ERROR",
            "quality_score": None,
            "contradiction": False,
            "warnings": [f"DeepSeek verifier unavailable: {type(exc).__name__}"],
            "notes": [],
            "model": DEEPSEEK_MODEL,
        }
