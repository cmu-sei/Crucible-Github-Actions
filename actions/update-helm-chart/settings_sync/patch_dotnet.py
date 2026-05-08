"""Patch the `env:` block of a values.yaml document.

Operates on a `ruamel.yaml`-loaded document in place. Returns True iff the
document was modified, so callers can decide whether to write the file back.

Rules (spec: Dotnet-appsettings patcher):
  * At the root (`subkey=None`) the env: block is created if missing.
  * Under a subkey (e.g. "player-api" in parent values.yaml) the env: block
    is NOT created. If missing, we skip — parent values.yaml is hand-curated.
  * Additions are appended at the end of the env: block.
  * Blank values: string -> "", bool -> False, number -> 0.
  * Removals delete the key line in place; preceding comments are left alone.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from .flatten import LeafType


_BLANK_BY_TYPE: Mapping[LeafType, object] = {
    LeafType.STRING: DoubleQuotedScalarString(""),
    LeafType.BOOL: False,
    LeafType.NUMBER: 0,
}


def patch_values(
    doc: CommentedMap,
    subkey: Optional[str],
    added: Dict[str, LeafType],
    removed: List[str],
) -> bool:
    if not added and not removed:
        return False

    container = _locate_container(doc, subkey, create_env=subkey is None)
    if container is None:
        return False

    modified = False

    for key in removed:
        if key in container:
            del container[key]
            modified = True

    for key, leaf_type in added.items():
        if key in container:
            continue
        container[key] = _BLANK_BY_TYPE[leaf_type]
        modified = True

    return modified


def _locate_container(
    doc: CommentedMap, subkey: Optional[str], create_env: bool
) -> Optional[CommentedMap]:
    if subkey is None:
        env = doc.get("env")
        if not isinstance(env, CommentedMap):
            if env is None and create_env:
                new = CommentedMap()
                doc["env"] = new
                return new
            return None
        return env

    parent = doc.get(subkey)
    if not isinstance(parent, CommentedMap):
        return None
    env = parent.get("env")
    if not isinstance(env, CommentedMap):
        return None
    return env
