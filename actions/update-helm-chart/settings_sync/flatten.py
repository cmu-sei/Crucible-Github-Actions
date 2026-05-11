"""Flatten a parsed JSON object to a leaf-path -> type map.

Two strategies:
  - flatten_dotnet: emits ASP.NET Core env-var style keys (`Section__Key`,
    `Array__0`). Skips containers that end up empty after JSONC comments are
    stripped upstream.
  - flatten_angular: emits JSON Pointer paths (`/Section/key`, `/Array/0`).
    Used for strict-JSON Angular settings files. Same empty-container skip.

Only scalar-array elements are expanded, and only element 0 is emitted as a
placeholder (matching existing values.yaml convention). Object arrays and
deeper array shapes beyond the first scalar element are not flattened further.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict


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
    _walk_dotnet(data, [], result)
    return result


def _walk_dotnet(node: Any, path: list[str], out: Dict[str, LeafType]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _walk_dotnet(value, path + [str(key)], out)
        return
    if isinstance(node, list):
        if not node:
            return
        first = node[0]
        if _is_scalar(first):
            key = "__".join(path + ["0"])
            out[key] = _leaf_type(first)  # type: ignore[assignment]
        return
    lt = _leaf_type(node)
    if lt is None:
        return
    out["__".join(path)] = lt


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
