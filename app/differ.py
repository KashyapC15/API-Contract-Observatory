"""A focused deterministic detector for common OpenAPI contract changes."""

import argparse
import json
import sys
from collections.abc import Mapping
from typing import Any

from app.analyzer import AnalysisError, analyze_changes
from app.models import Change, ChangeType, DiffResult
from app.parser import SpecParseError, load_spec, validate_spec

HTTP_METHODS = {
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
}


class SpecDiffError(ValueError):
    """Raised when a document uses a schema reference the detector cannot resolve."""


def compare_specs(old_spec: Mapping[str, Any], new_spec: Mapping[str, Any]) -> DiffResult:
    """Compare two OpenAPI 3.x documents and return supported contract changes."""
    old_document = validate_spec(dict(old_spec), source="Old OpenAPI document")
    new_document = validate_spec(dict(new_spec), source="New OpenAPI document")
    changes: list[Change] = []

    old_paths = old_document["paths"]
    new_paths = new_document["paths"]
    all_paths = sorted(set(old_paths) | set(new_paths))

    for path in all_paths:
        old_item = old_paths.get(path, {})
        new_item = new_paths.get(path, {})
        if not isinstance(old_item, Mapping) or not isinstance(new_item, Mapping):
            continue

        old_methods = _operations(old_item)
        new_methods = _operations(new_item)
        for method in sorted(set(old_methods) | set(new_methods)):
            if method not in old_methods:
                changes.append(
                    Change(
                        change_type=ChangeType.ENDPOINT_ADDED,
                        path=path,
                        method=method,
                        breaking=False,
                        message=f"Added {method.upper()} {path}.",
                    )
                )
                continue
            if method not in new_methods:
                changes.append(
                    Change(
                        change_type=ChangeType.ENDPOINT_REMOVED,
                        path=path,
                        method=method,
                        breaking=True,
                        message=f"Removed {method.upper()} {path}.",
                    )
                )
                continue

            old_operation = old_methods[method]
            new_operation = new_methods[method]
            changes.extend(
                _compare_parameters(
                    old_item,
                    new_item,
                    old_operation,
                    new_operation,
                    path,
                    method,
                )
            )

            for scope, old_schema, new_schema, schema_label in _operation_schemas(
                old_operation, new_operation
            ):
                changes.extend(
                    _compare_schema(
                        old_schema,
                        new_schema,
                        old_document,
                        new_document,
                        path,
                        method,
                        scope,
                        schema_label,
                        set(),
                    )
                )

    changes.sort(
        key=lambda change: (
            change.path,
            change.method or "",
            change.scope or "",
            change.field or "",
            change.change_type.value,
        )
    )
    return DiffResult(changes=changes)


def _operations(path_item: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        key.lower(): value
        for key, value in path_item.items()
        if isinstance(key, str)
        and key.lower() in HTTP_METHODS
        and isinstance(value, Mapping)
    }


def _operation_schemas(
    old_operation: Mapping[str, Any], new_operation: Mapping[str, Any]
) -> list[tuple[str, Any, Any, str]]:
    schemas: list[tuple[str, Any, Any, str]] = []
    old_body = old_operation.get("requestBody", {})
    new_body = new_operation.get("requestBody", {})
    if isinstance(old_body, Mapping) and isinstance(new_body, Mapping):
        old_content = old_body.get("content", {})
        new_content = new_body.get("content", {})
        if isinstance(old_content, Mapping) and isinstance(new_content, Mapping):
            for media_type in sorted(set(old_content) & set(new_content)):
                old_media = old_content[media_type]
                new_media = new_content[media_type]
                if isinstance(old_media, Mapping) and isinstance(new_media, Mapping):
                    if "schema" in old_media and "schema" in new_media:
                        schemas.append(
                            (
                                "request",
                                old_media["schema"],
                                new_media["schema"],
                                f"requestBody.{media_type}",
                            )
                        )

    old_responses = old_operation.get("responses", {})
    new_responses = new_operation.get("responses", {})
    if isinstance(old_responses, Mapping) and isinstance(new_responses, Mapping):
        for status in sorted(set(old_responses) & set(new_responses), key=str):
            if not _is_success_status(status):
                continue
            old_response = old_responses[status]
            new_response = new_responses[status]
            if not isinstance(old_response, Mapping) or not isinstance(new_response, Mapping):
                continue
            old_content = old_response.get("content", {})
            new_content = new_response.get("content", {})
            if not isinstance(old_content, Mapping) or not isinstance(new_content, Mapping):
                continue
            for media_type in sorted(set(old_content) & set(new_content)):
                old_media = old_content[media_type]
                new_media = new_content[media_type]
                if isinstance(old_media, Mapping) and isinstance(new_media, Mapping):
                    if "schema" in old_media and "schema" in new_media:
                        schemas.append(
                            (
                                "response",
                                old_media["schema"],
                                new_media["schema"],
                                f"response.{status}.{media_type}",
                            )
                        )
    return schemas


def _is_success_status(status: Any) -> bool:
    try:
        return 200 <= int(status) < 300
    except (TypeError, ValueError):
        return False


def _compare_parameters(
    old_path_item: Mapping[str, Any],
    new_path_item: Mapping[str, Any],
    old_operation: Mapping[str, Any],
    new_operation: Mapping[str, Any],
    path: str,
    method: str,
) -> list[Change]:
    old_parameters = _effective_parameters(old_path_item, old_operation)
    new_parameters = _effective_parameters(new_path_item, new_operation)
    changes: list[Change] = []

    for key in sorted(new_parameters):
        old_parameter = old_parameters.get(key)
        new_parameter = new_parameters[key]
        if (
            new_parameter.get("required") is True
            and (
                old_parameter is None
                or old_parameter.get("required") is not True
            )
        ):
            parameter_name = key[1]
            parameter_in = key[0]
            changes.append(
                Change(
                    change_type=ChangeType.PARAMETER_REQUIRED,
                    path=path,
                    method=method,
                    scope=f"request.parameter.{parameter_in}",
                    field=parameter_name,
                    old_value=(
                        old_parameter.get("required")
                        if old_parameter is not None
                        else None
                    ),
                    new_value=True,
                    breaking=True,
                    message=(
                        f"Parameter '{parameter_name}' in '{parameter_in}' is now required."
                    ),
                )
            )
    return changes


def _effective_parameters(
    path_item: Mapping[str, Any], operation: Mapping[str, Any]
) -> dict[tuple[str, str], Mapping[str, Any]]:
    parameters: dict[tuple[str, str], Mapping[str, Any]] = {}
    for source in (path_item.get("parameters", []), operation.get("parameters", [])):
        if not isinstance(source, list):
            continue
        for parameter in source:
            if not isinstance(parameter, Mapping):
                continue
            name = parameter.get("name")
            location = parameter.get("in")
            if isinstance(name, str) and isinstance(location, str):
                parameters[(location, name)] = parameter
    return parameters


def _compare_schema(
    old_schema: Any,
    new_schema: Any,
    old_document: Mapping[str, Any],
    new_document: Mapping[str, Any],
    path: str,
    method: str,
    scope: str,
    field_prefix: str,
    seen_pairs: set[tuple[int, int, str]],
) -> list[Change]:
    if not isinstance(old_schema, Mapping) or not isinstance(new_schema, Mapping):
        return []

    old_schema, old_ref_name = _resolve_schema(old_schema, old_document)
    new_schema, new_ref_name = _resolve_schema(new_schema, new_document)
    if not isinstance(old_schema, Mapping) or not isinstance(new_schema, Mapping):
        return []

    if field_prefix.startswith(("response.", "requestBody.")):
        if old_ref_name is not None and old_ref_name == new_ref_name:
            field_prefix = old_ref_name

    pair = (id(old_schema), id(new_schema), scope)
    if pair in seen_pairs:
        return []
    seen_pairs.add(pair)

    changes: list[Change] = []
    if old_schema.get("type") != new_schema.get("type"):
        changes.append(
            Change(
                change_type=ChangeType.FIELD_TYPE_CHANGED,
                path=path,
                method=method,
                scope=scope,
                field=field_prefix,
                old_value=old_schema.get("type"),
                new_value=new_schema.get("type"),
                breaking=True,
                message=(
                    f"Changed the type of '{field_prefix}' from "
                    f"{old_schema.get('type', 'unspecified')} to "
                    f"{new_schema.get('type', 'unspecified')}."
                ),
            )
        )

    old_properties = old_schema.get("properties", {})
    new_properties = new_schema.get("properties", {})
    if not isinstance(old_properties, Mapping) or not isinstance(new_properties, Mapping):
        return changes

    old_required = _required_names(old_schema)
    new_required = _required_names(new_schema)
    for property_name in sorted(set(old_properties) | set(new_properties), key=str):
        old_property = old_properties.get(property_name)
        new_property = new_properties.get(property_name)
        field_name = _field_name(field_prefix, str(property_name))

        if property_name not in old_properties:
            is_required = property_name in new_required
            changes.append(
                Change(
                    change_type=ChangeType.FIELD_ADDED,
                    path=path,
                    method=method,
                    scope=scope,
                    field=field_name,
                    new_value=_schema_type(new_property),
                    breaking=scope == "request" and is_required,
                    message=f"Added field '{field_name}'.",
                )
            )
            continue
        if property_name not in new_properties:
            changes.append(
                Change(
                    change_type=ChangeType.FIELD_REMOVED,
                    path=path,
                    method=method,
                    scope=scope,
                    field=field_name,
                    old_value=_schema_type(old_property),
                    breaking=True,
                    message=f"Removed field '{field_name}'.",
                )
            )
            continue

        if property_name in new_required and property_name not in old_required:
            changes.append(
                Change(
                    change_type=ChangeType.REQUIRED_FIELD_ADDED,
                    path=path,
                    method=method,
                    scope=scope,
                    field=field_name,
                    old_value=False,
                    new_value=True,
                    breaking=scope == "request",
                    message=f"Field '{field_name}' is now required.",
                )
            )

        if isinstance(old_property, Mapping) and isinstance(new_property, Mapping):
            changes.extend(
                _compare_schema(
                    old_property,
                    new_property,
                    old_document,
                    new_document,
                    path,
                    method,
                    scope,
                    field_name,
                    seen_pairs,
                )
            )
    return changes


def _required_names(schema: Mapping[str, Any]) -> set[Any]:
    required = schema.get("required", [])
    if isinstance(required, list):
        return set(required)
    return set()


def _schema_type(schema: Any) -> Any:
    if isinstance(schema, Mapping):
        return schema.get("type")
    return None


def _field_name(prefix: str, property_name: str) -> str:
    return f"{prefix}.{property_name}"


def _resolve_schema(
    schema: Mapping[str, Any], document: Mapping[str, Any]
) -> tuple[Mapping[str, Any], str | None]:
    reference = schema.get("$ref")
    if not isinstance(reference, str):
        return schema, None
    if not reference.startswith("#/"):
        raise SpecDiffError(f"External schema reference '{reference}' is not supported.")

    value: Any = document
    try:
        for token in reference[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[token]
    except (KeyError, TypeError) as error:
        raise SpecDiffError(f"Could not resolve schema reference '{reference}'.") from error
    if not isinstance(value, Mapping):
        raise SpecDiffError(f"Schema reference '{reference}' does not point to an object.")

    component_name = reference.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
    if len(schema) == 1:
        return value, component_name
    return {**value, **{key: val for key, val in schema.items() if key != "$ref"}}, component_name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two OpenAPI 3.x documents and print deterministic changes."
    )
    parser.add_argument("old_spec", help="Path to the older OpenAPI JSON/YAML file.")
    parser.add_argument("new_spec", help="Path to the newer OpenAPI JSON/YAML file.")
    parser.add_argument(
        "--output",
        "-o",
        help="Write JSON results to this file instead of standard output.",
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="Assess detected changes using a local Ollama model.",
    )
    parser.add_argument(
        "--model",
        help="Ollama model name (defaults to OLLAMA_MODEL or qwen3:4b).",
    )
    parser.add_argument(
        "--ollama-url",
        help="Ollama base URL (defaults to OLLAMA_BASE_URL or localhost:11434).",
    )
    args = parser.parse_args()

    try:
        result = compare_specs(load_spec(args.old_spec), load_spec(args.new_spec))
        if args.ai:
            analysis = analyze_changes(
                result,
                model=args.model,
                base_url=args.ollama_url,
            )
            output = json.dumps(
                {
                    "changes": result.model_dump(mode="json")["changes"],
                    "analysis": analysis.model_dump(mode="json"),
                },
                indent=2,
                ensure_ascii=False,
            )
        else:
            output = result.model_dump_json(indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as output_file:
                output_file.write(output + "\n")
        else:
            print(output)
    except (OSError, SpecParseError, SpecDiffError, AnalysisError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
