import json

from data_engine import (
    get_research_cache,
)

from recovery_engine import (
    recover_evidence,
)


HOME = "Austria"
AWAY = "Israel"

COMPETITION = (
    "UEFA Nations League"
)

MATCH_DATE = (
    "25.09.2026"
)


print()
print(
    "👑 BETTING BAYIN V11"
)

print(
    "🔄 Auto Evidence Recovery Test"
)

print()


research = get_research_cache(
    HOME,
    AWAY,
    COMPETITION,
    MATCH_DATE,
)


if not research:
    raise RuntimeError(
        "Research cache not found. "
        "Run python main.py first."
    )


result = recover_evidence(
    research
)


print()
print(
    "━━━━━━━━━━━━━━━━━━"
)

print(
    "🔧 RECOVERY DEBUG"
)

print(
    "━━━━━━━━━━━━━━━━━━"
)

print()

print(
    json.dumps(
        result,
        indent=2,
        ensure_ascii=False,
        default=str,
    )
)

print()
print(
    "✅ V11 RECOVERY TEST COMPLETE"
)