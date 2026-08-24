import os
import base64
import json

from dotenv import load_dotenv
from groq import Groq

from pipeline_engine import (
    run_full_pipeline,
    format_final_report,
    result_to_json,
)


# =========================================================
# BETTING BAYIN V12
# LOCAL FULL PIPELINE
# =========================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen/qwen3.6-27b")
IMAGE_PATH = os.getenv("BETTING_BAYIN_IMAGE", "test.jpeg")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY မတွေ့ပါ")

client = Groq(api_key=GROQ_API_KEY)


VISION_PROMPT = """
You are Betting Bayin's screenshot extraction engine.

Read only visible information from the football betting screenshot.

STRICT RULES:
- Never invent data.
- Never give betting advice.
- Preserve decimal odds exactly.
- Identify PRE-MATCH or LIVE accurately.
- Extract only markets that are visible.
- If something is unreadable, use null.
- Return valid JSON only.
- Do not output markdown.
- Do not output explanations.
- Do not output <think> tags.

Return exactly this structure:

{
  "sport": null,
  "competition": null,
  "round_or_group": null,
  "match": {
    "home_team": null,
    "away_team": null
  },
  "match_type": null,
  "start_date": null,
  "start_time": null,
  "live": {
    "is_live": false,
    "minute": null,
    "score": null
  },
  "markets": [
    {
      "market_name": "",
      "selections": [
        {
          "selection": "",
          "odds": null
        }
      ]
    }
  ],
  "unreadable_items": []
}
"""


def image_to_data_url(path):
    with open(path, "rb") as file:
        encoded = base64.b64encode(file.read()).decode("utf-8")
    return "data:image/jpeg;base64," + encoded


def extract_screenshot(path):
    image_url = image_to_data_url(path)

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "system",
                "content": VISION_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Extract all visible betting information from this screenshot.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url},
                    },
                ],
            },
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    return json.loads(response.choices[0].message.content)


def main():
    print()
    print("👑 BETTING BAYIN V12")
    print("🚀 Unified Full Pipeline")
    print()

    if not os.path.exists(IMAGE_PATH):
        raise FileNotFoundError(f"Screenshot not found: {IMAGE_PATH}")

    print(f"📸 Reading: {IMAGE_PATH}")
    extracted = extract_screenshot(IMAGE_PATH)

    print("✅ Screenshot extraction completed.")
    print("🧠 Running full Betting Bayin pipeline...")

    result = run_full_pipeline(
        extracted,
        force_research_refresh=False,
        enable_recovery=True,
    )

    print()
    print(format_final_report(result))

    print()
    print("━━━━━━━━━━━━━━━━━━")
    print("🔧 FULL DEBUG")
    print("━━━━━━━━━━━━━━━━━━")
    print(result_to_json(result))

    print()
    print("✅ BETTING BAYIN V12 COMPLETE")


if __name__ == "__main__":
    main()
