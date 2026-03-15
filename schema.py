"""Infer schema (key -> type) from a JSON object for the schema tree."""

from __future__ import annotations

import re
from typing import Any


def _is_timestamp_like(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    # ISO8601-ish: 2026-03-15T08:42:31.457Z or with timezone
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", value))


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        if _is_timestamp_like(value):
            return "timestamp"
        return "string"
    if isinstance(value, list):
        if not value:
            return "array"
        elem_types = {_json_type_name(v) for v in value}
        if len(elem_types) == 1:
            return f"array<{next(iter(elem_types))}>"
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def schema_from_object(obj: dict[str, Any]) -> list[tuple[str, str | list[Any]]]:
    """Build a flat list of (key, type_or_children) for tree display.

    For leaves: (key, type_string).
    For nested objects: (key, list of (key, type_or_children) for children).
    """
    result: list[tuple[str, str | list[Any]]] = []
    for key, value in obj.items():
        if key.startswith("_") and key in ("_raw", "_parse_error", "_message"):
            continue
        if isinstance(value, dict) and not value.get("_parse_error"):
            result.append((key, schema_from_object(value)))
        elif isinstance(value, list):
            if not value:
                result.append((key, "array"))
            else:
                result.append((key, _json_type_name(value)))
        else:
            result.append((key, _json_type_name(value)))
    return result


def all_keys_from_entries(entries: list[dict[str, Any]]) -> list[str]:
    """Collect all top-level keys from log entries for display-key selection."""
    keys_set: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict) and not entry.get("_parse_error"):
            for k in entry:
                if not k.startswith("_"):
                    keys_set.add(k)
    return sorted(keys_set)
