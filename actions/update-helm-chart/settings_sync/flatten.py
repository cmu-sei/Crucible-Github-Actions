"""Flatten a parsed JSON object to a leaf-path -> type map.

Three strategies:
  - flatten_dotnet: emits ASP.NET Core env-var style keys (`Section__Key`,
    `Array__0`). Skips containers that end up empty after JSONC comments are
    stripped upstream.
  - flatten_angular: emits JSON Pointer paths (`/Section/key`, `/Array/0`).
    Used for strict-JSON Angular settings files. Same empty-container skip.
  - flatten_dotnet_conf: parses INI-style `appsettings.conf` text (lines like
    `Section__Key = value`, optionally prefixed with `#` to comment them out)
    and emits the same `Section__Key` shape as flatten_dotnet. Every entry is
    treated as a STRING leaf since the .conf format is untyped.

flatten_dotnet_defaults walks the same tree as flatten_dotnet but keeps each
leaf's value, so the dotnet patcher can write an added number or bool key's
real default (strings stay blank: see patch_dotnet._value_for). The other two
kinds have no equivalent: a sample .conf's commented lines are
mostly examples (`# Pod__Url = pve1.local`), and an Angular settings.json holds
development URLs, so their keys keep blank placeholders.

Only scalar-array elements are expanded, and only element 0 is emitted as a
placeholder (matching existing values.yaml convention). Object arrays and
deeper array shapes beyond the first scalar element are not flattened further.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict


class LeafType(str, Enum):
    STRING = "string"
    BOOL = "bool"
    NUMBER = "number"


def _leaf_type(value: Any) -> LeafType | None:
    if isinstance(value, bool):
        return LeafType.BOOL
    if isinstance(value, (int, float)):
        return LeafType.NUMBER
    if isinstance(value, str):
        return LeafType.STRING
    return None


def _is_scalar(value: Any) -> bool:
    return _leaf_type(value) is not None


def flatten_dotnet(data: Any) -> Dict[str, LeafType]:
    result: Dict[str, LeafType] = {}
    _walk_dotnet(data, [], result, _leaf_type)
    return result


def flatten_dotnet_defaults(data: Any) -> Dict[str, Any]:
    """Same keys as flatten_dotnet, mapped to the value the file sets.

    An appsettings.json value is what the app uses when the setting isn't
    given. The dotnet patcher writes it for new number and bool keys, where a
    blank by type (0, false) would change the app's behavior.
    """
    result: Dict[str, Any] = {}
    _walk_dotnet(data, [], result, lambda value: value)
    return result


def _walk_dotnet(
    node: Any, path: list[str], out: Dict[str, Any], leaf: Callable[[Any], Any]
) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _walk_dotnet(value, path + [str(key)], out, leaf)
        return
    if isinstance(node, list):
        if not node:
            return
        first = node[0]
        if _is_scalar(first):
            key = "__".join(path + ["0"])
            out[key] = leaf(first)
        return
    if not _is_scalar(node):
        return
    out["__".join(path)] = leaf(node)


def flatten_dotnet_conf(raw: str) -> Dict[str, LeafType]:
    result: Dict[str, LeafType] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            stripped = stripped.lstrip("#").strip()
            if not stripped:
                continue
        if "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if not key:
            continue
        if key in result:
            continue
        result[key] = LeafType.STRING
    return result


def flatten_angular(data: Any) -> Dict[str, LeafType]:
    result: Dict[str, LeafType] = {}
    _walk_angular(data, [], result)
    return result


def _walk_angular(node: Any, path: list[str], out: Dict[str, LeafType]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _walk_angular(value, path + [str(key)], out)
        return
    if isinstance(node, list):
        if not node:
            return
        first = node[0]
        if _is_scalar(first):
            key = "/" + "/".join(path + ["0"])
            out[key] = _leaf_type(first)  # type: ignore[assignment]
        return
    lt = _leaf_type(node)
    if lt is None:
        return
    out["/" + "/".join(path)] = lt
