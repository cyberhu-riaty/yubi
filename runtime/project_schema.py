"""Versioned project document conversion.

Project files are persisted user documents.  Version 1 used Chinese machine keys
(``项目``, ``模型``, ``算法`` ...).  Version 2 uses English machine keys while a
project's display name, notes and appearance values may remain Chinese.  Old
documents are converted on read; new documents are written as version 2.  No
information is dropped: entries that cannot be mapped to a known plugin or
parameter identifier are kept in a clearly separated legacy list.

The module deliberately has no dependency on the runtime or algorithm modules so
it can be tested in isolation.  Callers provide a plugin identifier index when
they need legacy display names resolved to module names.
"""
from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

LEGACY_TOP_LEVEL = {
    "项目": "project",
    "模型": "model",
    "算法": "algorithms",
    "参数": "parameters",
    "外观": "appearance",
    "备注": "notes",
    "实验专用": "experiment_only",
    "_说明": "comment",
    "_顺序说明": "order_note",
    "_默认说明": "default_note",
    # Version-2 comment keys are accepted when an already migrated document is read.
    "_comment": "comment",
    "_notes": "notes",
    "_order_note": "order_note",
    "_default_note": "default_note",
}

LEGACY_ALGORITHM_KEYS = {"插件": "plugin", "类": "class", "文件": "file"}
LEGACY_APPEARANCE_KEYS = {"风格": "style", "主题": "theme"}

V2_KEYS = (
    "schema_version", "comment", "project", "model", "algorithms", "parameters",
    "legacy_parameters", "appearance", "notes", "experiment_only", "order_note",
    "default_note",
)

# Keys that describe the document or the operator, not machine identifiers.
_TEXT_KEYS = ("comment", "notes", "order_note", "default_note")


def is_ascii(value: object) -> bool:
    return isinstance(value, str) and value.isascii()


def looks_legacy(data: Mapping[str, Any]) -> bool:
    return any(key in data for key in LEGACY_TOP_LEVEL)


def _algorithm_entry(entry: Any) -> Any:
    if isinstance(entry, str):
        return {"plugin": entry} if entry.strip() else None
    if not isinstance(entry, Mapping):
        return None
    result: dict[str, Any] = {}
    for key, value in entry.items():
        name = LEGACY_ALGORITHM_KEYS.get(key, key)
        result[str(name)] = value
    plugin = str(result.get("plugin") or "").strip()
    if not plugin:
        return None
    result["plugin"] = plugin
    return result


def _algorithm_entries(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text in ("*", "全部", "all"):
            return "*"
        return [{"plugin": text}] if text else []
    if not isinstance(value, Iterable) or isinstance(value, (bytes, bytearray)):
        return []
    result = []
    for entry in value:
        normalized = _algorithm_entry(entry)
        if normalized:
            result.append(normalized)
    return result


def _legacy_parameter_bucket(
    buckets: dict[str, dict[str, Any]], plugin_name: str, parameter: str, value: Any,
) -> None:
    bucket = buckets.setdefault(plugin_name, {"plugin_name": plugin_name, "parameters": []})
    bucket["parameters"].append({"name": parameter, "value": value})


def _canonical_parameter(
    plugin: str, parameter: str, aliases: Mapping[str, Mapping[str, str]],
) -> str | None:
    mapped = aliases.get(plugin, {}).get(parameter, parameter)
    return str(mapped) if is_ascii(mapped) else None


def normalize_parameters(
    value: Any,
    plugin_index: Mapping[str, str] | None = None,
    parameter_aliases: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Return ``(english_parameters, unresolved_legacy_entries)``.

    ``plugin_index`` maps a display/English/module name to the module identifier.
    Parameters that already live under an ASCII module name are kept even when the
    module is not in the index (for example a plugin temporarily moved away).
    """
    index = plugin_index or {}
    aliases = parameter_aliases or {}
    parameters: dict[str, dict[str, Any]] = {}
    legacy: dict[str, dict[str, Any]] = {}
    if not isinstance(value, Mapping):
        return parameters, []
    for raw_plugin, raw_items in value.items():
        plugin_name = str(raw_plugin)
        canonical = index.get(plugin_name)
        if canonical is None and is_ascii(plugin_name):
            canonical = plugin_name
        if canonical is None:
            if isinstance(raw_items, Mapping):
                for parameter, item_value in raw_items.items():
                    _legacy_parameter_bucket(legacy, plugin_name, str(parameter), item_value)
            else:
                _legacy_parameter_bucket(legacy, plugin_name, "", raw_items)
            continue
        if not isinstance(raw_items, Mapping):
            continue
        for parameter, item_value in raw_items.items():
            parameter_name = _canonical_parameter(canonical, str(parameter), aliases)
            if parameter_name is None:
                _legacy_parameter_bucket(legacy, plugin_name, str(parameter), item_value)
                continue
            parameters.setdefault(canonical, {})[parameter_name] = item_value
    return parameters, list(legacy.values())


def normalize_project(
    data: Any,
    plugin_index: Mapping[str, str] | None = None,
    parameter_aliases: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Convert a version-1 or version-2 project document to the English in-memory form."""
    if not isinstance(data, Mapping):
        return {}
    source: dict[str, Any] = {}
    legacy_fields: dict[str, Any] = {}
    for key, value in data.items():
        name = LEGACY_TOP_LEVEL.get(str(key), str(key))
        if name in source and name != key:
            # Version 2 already owns the field; keep the legacy copy isolated.
            legacy_fields[str(key)] = value
            continue
        source[name] = value

    project = str(source.get("project") or "").strip()
    model = str(source.get("model") or "").strip()
    algorithms = _algorithm_entries(source.get("algorithms", "*"))
    parameters, legacy_parameters = normalize_parameters(
        source.get("parameters"), plugin_index, parameter_aliases)
    if isinstance(source.get("legacy_parameters"), list):
        known = {str(item.get("plugin_name")) for item in legacy_parameters
                 if isinstance(item, dict)}
        for item in source["legacy_parameters"]:
            if isinstance(item, dict) and str(item.get("plugin_name")) not in known:
                legacy_parameters.append(item)
    appearance_source = source.get("appearance")
    appearance: dict[str, Any] = {}
    if isinstance(appearance_source, Mapping):
        for key, value in appearance_source.items():
            appearance[LEGACY_APPEARANCE_KEYS.get(str(key), str(key))] = value

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "model": model,
        "algorithms": algorithms,
        "parameters": parameters,
        "appearance": appearance,
    }
    if legacy_parameters:
        result["legacy_parameters"] = legacy_parameters
    for key in _TEXT_KEYS:
        text = source.get(key)
        if text:
            result[key] = text
    if bool(source.get("experiment_only", False)):
        result["experiment_only"] = True

    extras: dict[str, Any] = {}
    existing_extra = source.get("extra")
    if isinstance(existing_extra, Mapping):
        extras.update({str(key): value for key, value in existing_extra.items()})
    existing_legacy = source.get("legacy_fields")
    if isinstance(existing_legacy, Mapping):
        legacy_fields.update({str(key): value for key, value in existing_legacy.items()})
    for key, value in source.items():
        if key in V2_KEYS or key in _TEXT_KEYS or key in ("schema_version", "extra", "legacy_fields"):
            continue
        if is_ascii(key):
            extras[str(key)] = value
        else:
            legacy_fields[str(key)] = value
    if extras:
        result["extra"] = extras
    if legacy_fields:
        result["legacy_fields"] = legacy_fields
    return result


def serialize_project(data: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize the in-memory form as a version-2 document (keys are ASCII)."""
    normalized = normalize_project(data)
    document: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    if normalized.get("comment"):
        document["_comment"] = normalized["comment"]
    document["project"] = normalized.get("project", "")
    document["model"] = normalized.get("model", "")
    document["algorithms"] = normalized.get("algorithms", "*")
    document["parameters"] = normalized.get("parameters", {})
    if normalized.get("legacy_parameters"):
        document["legacy_parameters"] = normalized["legacy_parameters"]
    appearance = normalized.get("appearance") or {}
    if appearance:
        document["appearance"] = appearance
    if normalized.get("notes"):
        document["notes"] = normalized["notes"]
    for key in ("order_note", "default_note"):
        if normalized.get(key):
            document["_" + key] = normalized[key]
    if normalized.get("experiment_only"):
        document["experiment_only"] = True
    document.update(normalized.get("extra") or {})
    legacy_fields = normalized.get("legacy_fields") or {}
    if legacy_fields:
        document["legacy_fields"] = legacy_fields
    return document


# ---------------------------------------------------------------------------
# Static plugin identifier index (no plugin import: AST only)
# ---------------------------------------------------------------------------
_IDENTIFIER_CACHE: dict[tuple[str, ...], tuple[dict[str, str], dict[str, dict[str, str]]]] = {}


def _string_dict(node: ast.AST | None) -> dict[str, str]:
    if not isinstance(node, ast.Dict):
        return {}
    result: dict[str, str] = {}
    for key, value in zip(node.keys, node.values):
        if (isinstance(key, ast.Constant) and isinstance(key.value, str)
                and isinstance(value, ast.Constant) and isinstance(value.value, str)):
            result[key.value] = value.value
    return result


def plugin_identifier_index(
    directories: Iterable[str | Path],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Scan algorithm files for display-name and legacy-parameter mappings.

    Returns ``(name_index, parameter_aliases)``.  The result is cached per set of
    directories; the algorithm tree changes rarely and this only runs when a
    legacy project is read.
    """
    roots = tuple(str(Path(directory)) for directory in directories)
    cached = _IDENTIFIER_CACHE.get(roots)
    if cached is not None:
        return cached
    index: dict[str, str] = {}
    aliases: dict[str, dict[str, str]] = {}
    for root in roots:
        path = Path(root)
        if not path.is_dir():
            continue
        for file in sorted(path.rglob("*.py")):
            if file.name.startswith("_") or "__pycache__" in file.parts:
                continue
            try:
                tree = ast.parse(file.read_text(encoding="utf-8-sig"), filename=str(file))
            except (OSError, SyntaxError, UnicodeError):
                continue
            module = file.stem
            index.setdefault(module, module)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for child in node.body:
                    if not isinstance(child, ast.Assign) or len(child.targets) != 1:
                        continue
                    target = child.targets[0]
                    if not isinstance(target, ast.Name):
                        continue
                    if target.id in ("name", "english_name") and isinstance(child.value, ast.Constant):
                        if isinstance(child.value.value, str) and child.value.value.strip():
                            index.setdefault(child.value.value.strip(), module)
                    elif target.id == "parameter_aliases":
                        mapping = _string_dict(child.value)
                        if mapping:
                            aliases.setdefault(module, {}).update(mapping)
    result = (index, aliases)
    _IDENTIFIER_CACHE[roots] = result
    return result
