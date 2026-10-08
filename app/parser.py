"""Loading and basic validation for OpenAPI documents."""

import json
from pathlib import Path
from typing import Any

import yaml


class SpecParseError(ValueError):
    """Raised when a file cannot be read as a supported OpenAPI document."""


def load_spec(file_path: str | Path) -> dict[str, Any]:
    """Load an OpenAPI document from a JSON, YAML, or YML file."""
    path = Path(file_path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise SpecParseError(f"OpenAPI document '{path}' must be UTF-8 encoded.") from error
    return parse_spec_text(text, file_name=path.name, source=str(path))


def parse_spec_text(
    text: str, file_name: str, source: str | None = None
) -> dict[str, Any]:
    """Parse an OpenAPI JSON or YAML string using its filename extension."""
    source = source or file_name
    suffix = Path(file_name).suffix.lower()

    try:
        if suffix == ".json":
            document = json.loads(text)
        elif suffix in {".yaml", ".yml"}:
            document = yaml.safe_load(text)
        else:
            raise SpecParseError(
                f"Unsupported specification format '{suffix}'. Use .json, .yaml, or .yml."
            )
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise SpecParseError(f"Could not parse OpenAPI document '{source}': {error}") from error

    return validate_spec(document, source=source)


def validate_spec(document: Any, source: str = "OpenAPI document") -> dict[str, Any]:
    """Validate the top-level structure required by the change detector."""
    if not isinstance(document, dict):
        raise SpecParseError(f"{source} must contain an object at the document root.")
    if not isinstance(document.get("openapi"), str):
        raise SpecParseError(f"{source} is missing a string 'openapi' version.")
    if not document["openapi"].startswith("3."):
        raise SpecParseError(
            f"{source} uses OpenAPI {document['openapi']}; only OpenAPI 3.x is supported."
        )
    if not isinstance(document.get("paths"), dict):
        raise SpecParseError(f"{source} must contain a 'paths' object.")
    return document
