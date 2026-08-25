import re


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("−", "-"))


def _period(value=None, market_name=None):
    text = f"{_norm(value)} {_norm(market_name)}"
    compact = re.sub(r"[^a-z0-9]+", "", text)
    if any(token in compact for token in ("1sthalf", "firsthalf", "1half", "half1")):
        return "1st_half"
    if any(token in compact for token in ("2ndhalf", "secondhalf", "2half", "half2")):
        return "2nd_half"
    if any(token in compact for token in ("regulartime", "fulltime", "90min", "match")):
        return "regular_time"
    raw = _norm(value)
    if raw in {"1st_half", "first_half"}:
        return "1st_half"
    if raw in {"2nd_half", "second_half"}:
        return "2nd_half"
    if raw in {"regular_time", "full_time"}:
        return "regular_time"
    # Pre-bet bookmaker screenshots default to regular-time only when no half tab
    # is visible in the extracted market label.
    return "regular_time"


def _strip_period(name):
    text = str(name or "").strip().replace("−", "-")
    patterns = (
        r"\bregular\s*time\b", r"\bfull\s*time\b", r"\b90\s*min(?:ute)?s?\b",
        r"\b1st\s*half\b", r"\bfirst\s*half\b",
        r"\b2nd\s*half\b", r"\bsecond\s*half\b",
    )
    for pattern in patterns:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip(" -—:")


def _market_family(name):
    raw = _norm(_strip_period(name))
    compact = re.sub(r"[^a-z0-9]+", "", raw)
    if compact in {"1x2", "matchresult", "fulltimeresult"}:
        return "1x2"
    if "doublechance" in compact and "bothteam" not in compact:
        return "double chance"
    if compact in {"btts", "bothteamstoscore", "bothteamscore"} or "bothteamstoscore" in compact:
        return "both teams to score"
    if "total" in raw and "team" not in raw:
        return "total"
    if "home" in raw and "team" in raw and "total" in raw:
        return "home team total"
    if "away" in raw and "team" in raw and "total" in raw:
        return "away team total"
    return raw


def _selection_key(market_name, selection):
    family = _market_family(market_name)
    raw = _norm(selection)
    compact = re.sub(r"[^a-z0-9.]+", "", raw)

    if family == "double chance":
        if compact in {"x2", "2x"}:
            return "2x"
        if compact in {"x1", "1x"}:
            return "1x"
        if compact in {"12", "21"}:
            return "12"

    if family == "1x2":
        aliases = {
            "1": "w1", "w1": "w1", "home": "w1", "homewin": "w1",
            "x": "draw", "draw": "draw",
            "2": "w2", "w2": "w2", "away": "w2", "awaywin": "w2",
        }
        return aliases.get(compact, compact)

    if family in {"total", "home team total", "away team total"}:
        m = re.search(r"(over|under|o|u)[^0-9]*([0-9]+(?:\.[0-9]+)?)", raw)
        if m:
            side = "over" if m.group(1) in {"over", "o"} else "under"
            return f"{side}:{m.group(2)}"

    if family == "both teams to score":
        if compact in {"yes", "y"}:
            return "yes"
        if compact in {"no", "n"}:
            return "no"

    return compact


def _first_nonempty(items, getter, default=None):
    for item in items:
        value = getter(item)
        if value not in (None, "", []):
            return value
    return default


def merge_extractions(extractions):
    """Merge multiple bookmaker pages for one match while preserving time scope.

    Regular Time, 1st Half and 2nd Half are separate market namespaces. Latest
    visible price wins only inside the same period + market + selection.
    """
    valid = [x for x in (extractions or []) if isinstance(x, dict)]
    if not valid:
        return {}

    if len(valid) == 1:
        single = dict(valid[0])
        markets = []
        for market in single.get("markets", []) or []:
            item = dict(market)
            item["period"] = _period(item.get("period"), item.get("market_name"))
            item["market_name"] = _strip_period(item.get("market_name")) or str(item.get("market_name") or "").strip()
            markets.append(item)
        single["markets"] = markets
        single["screenshots_merged"] = int(single.get("screenshots_merged", 1) or 1)
        return single

    merged = {
        "sport": _first_nonempty(valid, lambda x: x.get("sport")),
        "competition": _first_nonempty(valid, lambda x: x.get("competition")),
        "round_or_group": _first_nonempty(valid, lambda x: x.get("round_or_group")),
        "match": {
            "home_team": _first_nonempty(valid, lambda x: (x.get("match") or {}).get("home_team")),
            "away_team": _first_nonempty(valid, lambda x: (x.get("match") or {}).get("away_team")),
        },
        "match_type": _first_nonempty(valid, lambda x: x.get("match_type")),
        "start_date": _first_nonempty(valid, lambda x: x.get("start_date")),
        "start_time": _first_nonempty(valid, lambda x: x.get("start_time")),
        "live": {"is_live": False, "minute": None, "score": None},
        "markets": [],
        "unreadable_items": [],
        "screenshots_merged": len(valid),
    }

    for x in valid:
        live = x.get("live") or {}
        if live.get("is_live"):
            merged["live"]["is_live"] = True
        if merged["live"]["minute"] is None and live.get("minute") is not None:
            merged["live"]["minute"] = live.get("minute")
        if merged["live"]["score"] is None and live.get("score") is not None:
            merged["live"]["score"] = live.get("score")
        merged["unreadable_items"].extend(x.get("unreadable_items") or [])

    market_map = {}
    market_order = []
    for x in valid:
        for market in x.get("markets", []) or []:
            name = str(market.get("market_name") or "").strip()
            if not name:
                continue
            period = _period(market.get("period"), name)
            family = _market_family(name)
            market_key = (period, family)
            if market_key not in market_map:
                market_map[market_key] = {
                    "market_name": _strip_period(name) or name,
                    "period": period,
                    "selections": {},
                    "order": [],
                }
                market_order.append(market_key)
            bucket = market_map[market_key]
            bucket["market_name"] = _strip_period(name) or name
            for item in market.get("selections", []) or []:
                selection = str(item.get("selection") or "").strip()
                odds = item.get("odds")
                if not selection or odds is None:
                    continue
                key = _selection_key(name, selection)
                if key not in bucket["selections"]:
                    bucket["order"].append(key)
                bucket["selections"][key] = {"selection": selection, "odds": odds}

    for market_key in market_order:
        bucket = market_map[market_key]
        merged["markets"].append({
            "market_name": bucket["market_name"],
            "period": bucket["period"],
            "selections": [bucket["selections"][k] for k in bucket["order"]],
        })

    seen = set()
    unique_unreadable = []
    for value in merged["unreadable_items"]:
        key = _norm(value)
        if key and key not in seen:
            seen.add(key)
            unique_unreadable.append(value)
    merged["unreadable_items"] = unique_unreadable
    return merged
