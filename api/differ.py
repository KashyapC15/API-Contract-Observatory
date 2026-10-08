from collections.abc import Mapping
from typing import Any

from api.models import Change, ChangeType

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


def compare_specs(
    old_spec: Mapping[str, Any], new_spec: Mapping[str, Any]
) -> list[Change]:
    changes: list[Change] = []
    old_operations = _operations(old_spec)
    new_operations = _operations(new_spec)

    for operation in sorted(new_operations.keys() - old_operations.keys()):
        changes.append(Change(type="ENDPOINT_ADDED", location=operation))
    for operation in sorted(old_operations.keys() - new_operations.keys()):
        changes.append(Change(type="ENDPOINT_REMOVED", location=operation))

    old_schemas = _component_schemas(old_spec)
    new_schemas = _component_schemas(new_spec)
    for schema_name in sorted(old_schemas.keys() | new_schemas.keys()):
        old_schema = old_schemas.get(schema_name, {})
        new_schema = new_schemas.get(schema_name, {})
        _compare_schema(
            old_schema,
            new_schema,
            schema_name,
            changes,
            removed_type="FIELD_REMOVED",
        )

    for operation in sorted(old_operations.keys() & new_operations.keys()):
        _compare_inline_responses(
            old_operations[operation],
            new_operations[operation],
            operation,
            changes,
        )

    return changes


def _operations(spec: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    operations: dict[str, Mapping[str, Any]] = {}
    paths = spec.get("paths", {})
    if not isinstance(paths, Mapping):
        return operations

    for path, path_item in paths.items():
        if not isinstance(path_item, Mapping):
            continue
        for method, operation in path_item.items():
            if (
                isinstance(method, str)
                and method.lower() in HTTP_METHODS
                and isinstance(operation, Mapping)
            ):
                operations[f"{method.upper()} {path}"] = operation
    return operations


def _component_schemas(spec: Mapping[str, Any]) -> Mapping[str, Any]:
    components = spec.get("components", {})
    if not isinstance(components, Mapping):
        return {}
    schemas = components.get("schemas", {})
    return schemas if isinstance(schemas, Mapping) else {}


def _compare_schema(
    old_schema: Any,
    new_schema: Any,
    location: str,
    changes: list[Change],
    *,
    removed_type: ChangeType,
) -> None:
    if not isinstance(old_schema, Mapping) or not isinstance(new_schema, Mapping):
        return

    old_type = old_schema.get("type")
    new_type = new_schema.get("type")
    if old_type is not None and new_type is not None and old_type != new_type:
        changes.append(
            Change(type="FIELD_TYPE_CHANGED", location=location)
        )

    old_properties = old_schema.get("properties", {})
    new_properties = new_schema.get("properties", {})
    if not isinstance(old_properties, Mapping) or not isinstance(
        new_properties, Mapping
    ):
        return

    old_required = _string_set(old_schema.get("required", []))
    new_required = _string_set(new_schema.get("required", []))

    for name in sorted(new_properties.keys() - old_properties.keys()):
        property_location = f"{location}.{name}"
        changes.append(Change(type="FIELD_ADDED", location=property_location))
        if name in new_required:
            changes.append(
                Change(type="REQUIRED_FIELD_ADDED", location=property_location)
            )

    for name in sorted(old_properties.keys() - new_properties.keys()):
        changes.append(
            Change(type=removed_type, location=f"{location}.{name}")
        )

    for name in sorted(old_properties.keys() & new_properties.keys()):
        property_location = f"{location}.{name}"
        old_property = old_properties[name]
        new_property = new_properties[name]
        if name not in old_required and name in new_required:
            changes.append(
                Change(type="REQUIRED_FIELD_ADDED", location=property_location)
            )
        _compare_schema(
            old_property,
            new_property,
            property_location,
            changes,
            removed_type=removed_type,
        )


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def _compare_inline_responses(
    old_operation: Mapping[str, Any],
    new_operation: Mapping[str, Any],
    operation_location: str,
    changes: list[Change],
) -> None:
    old_responses = old_operation.get("responses", {})
    new_responses = new_operation.get("responses", {})
    if not isinstance(old_responses, Mapping) or not isinstance(
        new_responses, Mapping
    ):
        return

    for status in sorted(old_responses.keys() & new_responses.keys(), key=str):
        old_response_schema = _inline_json_schema(old_responses[status])
        new_response_schema = _inline_json_schema(new_responses[status])
        _compare_schema(
            old_response_schema,
            new_response_schema,
            f"{operation_location}.responses.{status}",
            changes,
            removed_type="RESPONSE_PROPERTY_REMOVED",
        )


def _inline_json_schema(response: Any) -> Mapping[str, Any]:
    if not isinstance(response, Mapping):
        return {}
    content = response.get("content", {})
    if not isinstance(content, Mapping):
        return {}
    json_content = content.get("application/json", {})
    if not isinstance(json_content, Mapping):
        return {}
    schema = json_content.get("schema", {})
    if not isinstance(schema, Mapping) or "$ref" in schema:
        return {}
    return schema
