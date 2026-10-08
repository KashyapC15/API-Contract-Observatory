import json
import os

import requests

from api.models import Change, RiskReport


def analyze_changes(changes: list[Change]) -> RiskReport:
    if not changes:
        return RiskReport(
            risk="LOW",
            breaking=False,
            confidence=1,
            reason="No supported API changes were detected.",
            affected_consumers=[],
            recommended_action="No action is required.",
            human_review_required=False,
        )

    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
    schema = RiskReport.model_json_schema()
    prompt = (
        "Assess the compatibility risk of these detected OpenAPI changes. "
        "Only use the change list below; do not invent changes. "
        "Return a JSON object matching the supplied schema. "
        "Set human_review_required to true if confidence is below 0.7.\n\n"
        f"Changes:\n{json.dumps([change.model_dump() for change in changes])}"
    )

    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "stream": False,
                "format": schema,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an API compatibility risk analyst.",
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not reach Ollama. Start Ollama and confirm the selected model "
            f"'{model}' is available."
        ) from exc

    try:
        payload = response.json()
        content = payload["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned an empty risk report.")
        return RiskReport.model_validate_json(content)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "Ollama returned a response that could not be validated as a risk report."
        ) from exc
