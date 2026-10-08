from typing import Any

import yaml


def parse_openapi(contents: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(contents)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(document, dict):
        raise ValueError("The YAML document must contain an OpenAPI object.")
    if not isinstance(document.get("openapi"), str):
        raise ValueError("The document is missing the OpenAPI version.")
    if not isinstance(document.get("paths"), dict):
        raise ValueError("The document must contain a paths object.")

    return document
