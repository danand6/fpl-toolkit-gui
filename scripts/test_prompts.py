import argparse
import json
import csv
import os
from datetime import datetime
from typing import List

import requests

API_URL = os.getenv("CHAT_URL", "http://localhost:5001/api/chat")
OUTPUT_DIR = os.getenv("CHAT_TEST_OUTPUT", "chat_test_logs")


def load_prompts(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as fh:
        if path.endswith(".json"):
            return json.load(fh)
        return [line.strip() for line in fh if line.strip()]


def run_chat(prompt: str) -> dict:
    response = requests.post(
        API_URL,
        json={"message": prompt},
        timeout=15,
    )
    payload = {
        "status": response.status_code,
        "prompt": prompt,
    }
    try:
        data = response.json()
    except ValueError:
        payload["error"] = response.text
        return payload

    payload.update({
        "reply": data.get("reply"),
        "feature_id": data.get("featureId"),
        "has_feature": bool(data.get("feature")),
        "suggestions": ", ".join(s.get("label", "") for s in data.get("suggestions", []) if isinstance(s, dict)),
    })

    feature = data.get("feature") or {}
    if isinstance(feature, dict):
        payload["feature_type"] = feature.get("type")
        payload["metadata"] = json.dumps(feature.get("metadata"), ensure_ascii=False) if feature.get("metadata") else ""
    else:
        payload["feature_type"] = type(feature).__name__
        payload["metadata"] = ""

    return payload


def main():
    parser = argparse.ArgumentParser(description="Batch test chatbot prompts")
    parser.add_argument("prompts", help="Path to prompts file (.json or plain text)")
    parser.add_argument("--output", help="Optional explicit output dir")
    args = parser.parse_args()

    prompts = load_prompts(args.prompts)
    output_dir = args.output or OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = os.path.join(output_dir, f"prompts_{timestamp}.csv")

    print(f"Testing {len(prompts)} prompts against {API_URL}\n")

    rows = []
    for prompt in prompts:
        result = run_chat(prompt)
        rows.append(result)
        status = result["status"]
        feature = result.get("feature_id") or result.get("feature_type") or "—"
        reply = result.get("reply") or result.get("error") or "(no reply)"
        print(f"[{status}] {prompt}\n    → {feature}\n    → {reply[:150].replace('\n', ' ')}\n")

    with open(csv_path, "w", newline='', encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["prompt", "status", "feature_id", "feature_type", "has_feature", "reply", "metadata", "suggestions", "error"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Saved log to {csv_path}")


if __name__ == "__main__":
    main()
