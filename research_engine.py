import os
import json
import time
import re
from urllib.parse import urlparse

from dotenv import load_dotenv
from groq import Groq, RateLimitError

# =========================================================
# BETTING BAYIN
# COMPACT MULTI-PASS RESEARCH ENGINE V5
# =========================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY မတွေ့ပါ")

client = Groq(
    api_key=GROQ_API_KEY,
    default_headers={
        "Groq-Model-Version": "latest"
    }
)

RESEARCH_MODEL = "groq/compound-mini"

MAX_RETRIES = 1
DEFAULT_RETRY_SECONDS = 5


# =========================================================
# HELPERS
# =========================================================

def clean_json_output(content):
    if not content:
        return None

    cleaned = (
        content
        .replace("```json", "")
        .replace("```JSON", "")
        .replace("```", "")
        .strip()
    )

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(
        r"\{.*\}",
        cleaned,
        re.DOTALL
    )

    if match:
        try:
            return json.loads(
                match.group(0)
            )
        except json.JSONDecodeError:
            pass

    return None


def get_retry_seconds(error):
    text = str(error)

    match = re.search(
        r"try again in\s+([\d.]+)s",
        text,
        re.IGNORECASE
    )

    if match:
        try:
            return int(
                float(match.group(1))
            ) + 3
        except ValueError:
            pass

    return DEFAULT_RETRY_SECONDS


def source_domain(url):
    try:
        return (
            urlparse(url)
            .netloc
            .lower()
            .replace("www.", "")
        )
    except Exception:
        return ""


def is_good_source(url):
    domain = source_domain(url)

    trusted_domains = [
        "espn.com",
        "bbc.com",
        "bbc.co.uk",
        "skysports.com",
        "fotmob.com",
        "uefa.com",
        "fifa.com",
        "soccerway.com",
        "worldfootball.net",
        "transfermarkt.com",
        "theanalyst.com",
        "reuters.com",
        "apnews.com",
    ]

    return any(
        trusted in domain
        for trusted in trusted_domains
    )


# =========================================================
# GROQ RESEARCH CALL
# =========================================================

def call_research(prompt):

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):
        try:
            print(
                f"🔎 Research attempt "
                f"{attempt}/{MAX_RETRIES}..."
            )

            response = client.chat.completions.create(
                model=RESEARCH_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                compound_custom={
                    "tools": {
                        "enabled_tools": [
                            "web_search"
                        ]
                    }
                }
            )

            content = (
                response
                .choices[0]
                .message
                .content
            )

            result = clean_json_output(
                content
            )

            if result is None:
                return {
                    "error": "Invalid JSON"
                }

            return result

        except RateLimitError as error:

            if attempt >= MAX_RETRIES:
                return {
                    "error": (
                        "Groq rate limit "
                        "after retries"
                    )
                }

            wait_seconds = (
                get_retry_seconds(
                    error
                )
            )

            print(
                f"⏳ Rate limit. Waiting "
                f"{wait_seconds}s..."
            )

            time.sleep(
                wait_seconds
            )

        except Exception as error:

            return {
                "error": str(error)
            }

    return {
        "error": "Unknown failure"
    }


# =========================================================
# PASS 1 / 2
# RECENT MATCHES - COMPACT
# =========================================================

def research_recent_matches(
    team,
    competition,
    match_date
):

    prompt = f"""
Research ONLY the 5 most recent completed matches for:

Team: {team}
Before date: {match_date}

Rules:
- Max 5 matches.
- Only matches before target date.
- No betting advice.
- No summaries.
- No commentary.
- No extra text.
- Each match must include a source URL.
- Prefer ESPN, FotMob, UEFA, FIFA, BBC, Sky Sports,
  Soccerway, WorldFootball.
- Never invent a score or result.
- If fewer than 5 can be verified, return fewer.
- JSON only.

Return:
{{
  "matches": [
    {{
      "date": "YYYY-MM-DD",
      "opponent": "",
      "venue": "home|away|neutral|unknown",
      "goals_for": null,
      "goals_against": null,
      "result": "W|D|L",
      "competition": "",
      "source_url": ""
    }}
  ]
}}
"""

    return call_research(
        prompt
    )


# =========================================================
# PASS 3
# INJURIES / SUSPENSIONS / PLAYERS
# =========================================================

def research_team_news(
    home_team,
    away_team,
    match_date
):

    prompt = f"""
Research ONLY verified pre-match availability for:

{home_team} vs {away_team}
Before date: {match_date}

Return only:
- important injuries
- important suspensions
- expected/confirmed lineup if found
- key player availability

Rules:
- Omit anything unverified.
- No tactical essay.
- No betting advice.
- Each injury/suspension should include source_url.
- JSON only.

Return:
{{
  "injuries": {{
    "home": [],
    "away": []
  }},
  "suspensions": {{
    "home": [],
    "away": []
  }},
  "lineups": {{
    "home": null,
    "away": null
  }},
  "key_players": {{
    "home": [],
    "away": []
  }}
}}
"""

    return call_research(
        prompt
    )


# =========================================================
# PASS 4
# MATCH CONTEXT - VERY SMALL
# =========================================================

def research_match_context(
    home_team,
    away_team,
    competition,
    match_date
):

    prompt = f"""
Research concise pre-match context for:

{home_team} vs {away_team}
Competition: {competition}
Date: {match_date}

Return only:
- league/group context
- match importance
- rest/schedule if clearly available
- last 3 H2H if easily verifiable

No betting advice.
No long explanations.
JSON only.

Return:
{{
  "league_context": null,
  "league_profile": {
    "season": null,
    "sample_size": 0,
    "avg_total_goals": null,
    "over_1_5_rate": null,
    "over_2_5_rate": null,
    "over_3_5_rate": null,
    "btts_rate": null,
    "style_tags": [],
    "source_urls": []
  },
  "home_team_profile": {
    "sample_size": 0,
    "avg_goals_for": null,
    "avg_goals_against": null,
    "avg_total_goals": null,
    "over_1_5_rate": null,
    "over_2_5_rate": null,
    "over_3_5_rate": null,
    "btts_rate": null,
    "style_tags": [],
    "source_urls": []
  },
  "away_team_profile": {
    "sample_size": 0,
    "avg_goals_for": null,
    "avg_goals_against": null,
    "avg_total_goals": null,
    "over_1_5_rate": null,
    "over_2_5_rate": null,
    "over_3_5_rate": null,
    "btts_rate": null,
    "style_tags": [],
    "source_urls": []
  },
  "match_importance": null,
  "rest_and_schedule": {{
    "home": null,
    "away": null
  }},
  "head_to_head_matches": []
}}
"""

    return call_research(
        prompt
    )


# =========================================================
# MATCH CLEANER
# =========================================================

def clean_match_records(records):

    if not isinstance(
        records,
        list
    ):
        return []

    cleaned = []
    seen = set()

    for item in records:

        if not isinstance(
            item,
            dict
        ):
            continue

        result = str(
            item.get(
                "result",
                ""
            )
        ).upper()

        if result not in {
            "W",
            "D",
            "L"
        }:
            continue

        opponent = item.get(
            "opponent"
        )

        source_url = item.get(
            "source_url"
        )

        date = item.get(
            "date"
        )

        if not opponent:
            continue

        if not source_url:
            continue

        key = (
            str(date),
            str(opponent),
            str(
                item.get(
                    "goals_for"
                )
            ),
            str(
                item.get(
                    "goals_against"
                )
            )
        )

        if key in seen:
            continue

        seen.add(key)

        cleaned.append({
            "date": date,
            "opponent": opponent,
            "venue": item.get(
                "venue",
                "unknown"
            ),
            "goals_for": item.get(
                "goals_for"
            ),
            "goals_against": item.get(
                "goals_against"
            ),
            "result": result,
            "competition": item.get(
                "competition"
            ),
            "source_url": source_url,
            "source_domain": (
                source_domain(
                    source_url
                )
            ),
            "trusted_source": (
                is_good_source(
                    source_url
                )
            )
        })

    return cleaned[:5]


# =========================================================
# PYTHON FORM
# =========================================================

def calculate_form(
    matches
):

    wins = 0
    draws = 0
    losses = 0

    goals_for = 0
    goals_against = 0
    goal_samples = 0

    home_samples = 0
    away_samples = 0

    for match in matches:

        result = match.get(
            "result"
        )

        if result == "W":
            wins += 1

        elif result == "D":
            draws += 1

        elif result == "L":
            losses += 1

        venue = match.get(
            "venue"
        )

        if venue == "home":
            home_samples += 1

        elif venue == "away":
            away_samples += 1

        gf = match.get(
            "goals_for"
        )

        ga = match.get(
            "goals_against"
        )

        try:
            if (
                gf is not None
                and ga is not None
            ):
                gf = int(gf)
                ga = int(ga)

                goals_for += gf
                goals_against += ga
                goal_samples += 1

        except (
            TypeError,
            ValueError
        ):
            pass

    total = (
        wins
        + draws
        + losses
    )

    if total == 0:
        return {
            "matches": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "points_per_match": None,
            "avg_goals_for": None,
            "avg_goals_against": None,
            "home_samples": 0,
            "away_samples": 0
        }

    ppm = (
        wins * 3
        + draws
    ) / total

    avg_gf = (
        goals_for / goal_samples
        if goal_samples
        else None
    )

    avg_ga = (
        goals_against / goal_samples
        if goal_samples
        else None
    )

    return {
        "matches": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points_per_match": round(
            ppm,
            2
        ),
        "avg_goals_for": (
            round(
                avg_gf,
                2
            )
            if avg_gf is not None
            else None
        ),
        "avg_goals_against": (
            round(
                avg_ga,
                2
            )
            if avg_ga is not None
            else None
        ),
        "home_samples": home_samples,
        "away_samples": away_samples
    }


# =========================================================
# PYTHON RESEARCH QUALITY
# =========================================================

def calculate_research_quality(
    home_matches,
    away_matches,
    team_news,
    context
):

    score = 0.0
    notes = []

    # Home recent matches
    if len(
        home_matches
    ) >= 5:
        score += 0.25

    elif len(
        home_matches
    ) >= 3:
        score += 0.15

    else:
        notes.append(
            "Home match coverage weak."
        )

    # Away recent matches
    if len(
        away_matches
    ) >= 5:
        score += 0.25

    elif len(
        away_matches
    ) >= 3:
        score += 0.15

    else:
        notes.append(
            "Away match coverage weak."
        )

    # Trusted source coverage
    all_matches = (
        home_matches
        + away_matches
    )

    if all_matches:

        trusted = sum(
            1
            for match in all_matches
            if match.get(
                "trusted_source"
            )
        )

        ratio = (
            trusted
            / len(all_matches)
        )

        score += (
            0.20 * ratio
        )

        if ratio < 0.5:
            notes.append(
                "Trusted sources below 50%."
            )

    # Team news
    injuries = team_news.get(
        "injuries",
        {}
    )

    suspensions = team_news.get(
        "suspensions",
        {}
    )

    if (
        injuries.get("home")
        or injuries.get("away")
        or suspensions.get("home")
        or suspensions.get("away")
    ):
        score += 0.10

    # Context
    if context.get(
        "league_context"
    ):
        score += 0.08

    if context.get(
        "match_importance"
    ):
        score += 0.07

    rest = context.get(
        "rest_and_schedule",
        {}
    )

    if (
        rest.get("home")
        or rest.get("away")
    ):
        score += 0.05

    score = max(
        0.0,
        min(
            1.0,
            score
        )
    )

    return {
        "score": round(
            score,
            2
        ),
        "notes": notes
    }


# =========================================================
# MAIN RESEARCH
# =========================================================

def research_match(
    home_team,
    away_team,
    competition=None,
    match_date=None
):
    """V13.1 fast research: one web-search call instead of four sequential calls."""

    competition = competition or "Unknown competition"
    match_date = match_date or "Unknown date"

    print("🌐 Research model:", RESEARCH_MODEL)
    print("⚡ V13.1 Single-pass research")

    prompt = f"""
Research this football match in ONE compact pass.

Match: {home_team} vs {away_team}
Competition: {competition}
Target date: {match_date}

Return ONLY verified information available before the target date.
Keep the answer compact. Never invent missing facts.
Prefer ESPN, FotMob, UEFA, FIFA, BBC, Sky Sports, Soccerway,
WorldFootball, Transfermarkt, Reuters and AP.
Every recent-match or player-availability item should include source_url when available.
No betting advice. JSON only.

Return exactly this shape:
{{
  "home_recent_matches": [
    {{
      "date": "YYYY-MM-DD",
      "opponent": "",
      "venue": "home|away|neutral|unknown",
      "goals_for": null,
      "goals_against": null,
      "result": "W|D|L",
      "competition": "",
      "source_url": ""
    }}
  ],
  "away_recent_matches": [],
  "injuries": {{"home": [], "away": []}},
  "suspensions": {{"home": [], "away": []}},
  "lineups": {{"home": null, "away": null}},
  "key_players": {{"home": [], "away": []}},
  "league_context": null,
  "league_profile": {{
    "season": null,
    "sample_size": 0,
    "avg_total_goals": null,
    "over_1_5_rate": null,
    "over_2_5_rate": null,
    "over_3_5_rate": null,
    "btts_rate": null,
    "style_tags": [],
    "source_urls": []
  }},
  "home_team_profile": {{
    "sample_size": 0,
    "avg_goals_for": null,
    "avg_goals_against": null,
    "avg_total_goals": null,
    "over_1_5_rate": null,
    "over_2_5_rate": null,
    "over_3_5_rate": null,
    "btts_rate": null,
    "style_tags": [],
    "source_urls": []
  }},
  "away_team_profile": {{
    "sample_size": 0,
    "avg_goals_for": null,
    "avg_goals_against": null,
    "avg_total_goals": null,
    "over_1_5_rate": null,
    "over_2_5_rate": null,
    "over_3_5_rate": null,
    "btts_rate": null,
    "style_tags": [],
    "source_urls": []
  }},
  "match_importance": null,
  "rest_and_schedule": {{"home": null, "away": null}},
  "head_to_head_matches": []
}}

Rules:
- Maximum 5 recent matches per team.
- Completed matches only and strictly before target date.
- Omit unverified injuries/suspensions instead of guessing.
- For league_profile and team_profile, use numeric aggregates only when a source explicitly supports them.
- source_urls are mandatory for web aggregate profiles; otherwise return null/0/empty values.
- Prefer current-season or the most recent completed season available before the target date.
- style_tags must be short evidence-based descriptions such as high-scoring, low-block, transition-heavy, possession-heavy, open-defence. Never infer style from reputation alone.
- Never assume a small/youth/lower league is high scoring unless verified results/profile data supports it.
- Do not search for bookmaker odds.
"""

    result = call_research(prompt)
    if not isinstance(result, dict):
        result = {"error": "Invalid research result"}

    home_matches = clean_match_records(result.get("home_recent_matches", []))
    away_matches = clean_match_records(result.get("away_recent_matches", []))

    team_news = {
        "injuries": result.get("injuries") or {"home": [], "away": []},
        "suspensions": result.get("suspensions") or {"home": [], "away": []},
        "lineups": result.get("lineups") or {"home": None, "away": None},
        "key_players": result.get("key_players") or {"home": [], "away": []},
    }

    context = {
        "league_context": result.get("league_context"),
        "match_importance": result.get("match_importance"),
        "rest_and_schedule": result.get("rest_and_schedule") or {"home": None, "away": None},
        "head_to_head_matches": result.get("head_to_head_matches") or [],
    }

    home_form = calculate_form(home_matches)
    away_form = calculate_form(away_matches)
    quality = calculate_research_quality(home_matches, away_matches, team_news, context)

    return {
        "home_team": home_team,
        "away_team": away_team,
        "competition": competition,
        "match_date": match_date,
        "home_recent_matches": home_matches,
        "away_recent_matches": away_matches,
        "calculated_form": {"home": home_form, "away": away_form},
        "injuries": team_news["injuries"],
        "suspensions": team_news["suspensions"],
        "lineups": team_news["lineups"],
        "key_players": team_news["key_players"],
        "head_to_head_matches": context["head_to_head_matches"],
        "league_context": context["league_context"],
        "league_profile": result.get("league_profile") or {},
        "home_team_profile": result.get("home_team_profile") or {},
        "away_team_profile": result.get("away_team_profile") or {},
        "rest_and_schedule": context["rest_and_schedule"],
        "match_importance": context["match_importance"],
        "research_quality": quality,
        "raw_research_errors": {
            "home": result.get("error"),
            "away": result.get("error"),
            "team_news": result.get("error"),
            "context": result.get("error"),
        },
    }
