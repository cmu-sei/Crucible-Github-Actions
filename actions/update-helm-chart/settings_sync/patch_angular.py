"""Patch `settings:` (stringified JSON) and `settingsYaml:` blocks.

Two emission strategies live here:

* `settings:` (stringified JSON) — parsed, mutated, re-serialized.
* `settingsYaml:` (commented-out nested YAML) — additions appended as
  commented-out lines via a post-dump string splice. ruamel's in-map comment
  APIs don't reliably render end-of-mapping comments for empty/flow-style maps
  (a common state for this block), so we post-process the dumped text instead.

The post-dump step is applied by the caller via `finalize_dump(text, pending)`.
Patchers register pending settingsYaml additions on the document using
`_pending_attr`; the runner calls `finalize_dump` after `yaml.dump(...)` to
splice them in.
"""
from __future__ import annotations

import json
from typing import Dict, List, Mapping, Optional

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString

from .flatten import LeafType


_BLANK_BY_TYPE: Mapping[LeafType, object] = {
    LeafType.STRING: DoubleQuotedScalarString(""),
    LeafType.BOOL: False,
    LeafType.NUMBER: 0,
}

# Attribute name used to stash the list of pending (path, leaf_type) additions
# so `finalize_dump` can find them on the document. Using a dunder attribute
# avoids collision with any user YAML key.
_PENDING_ATTR = "__settings_yaml_pending__"


def patch_values(
    doc: CommentedMap,
    subkey: Optional[str],
    added: Dict[str, LeafType],
    removed: List[str],
) -> bool:
    if not added and not removed:
        return False

    root = _locate_root(doc, subkey)
    if root is None:
        return False

    modified = False

    if "settings" in root and isinstance(root["settings"], str):
        new_json = _patch_settings_json(root["settings"], added, removed)
        if new_json is not None and new_json != root["settings"]:
            root["settings"] = new_json
            modified = True

    if "settingsYaml" in root and added:
        # Register pending additions on the top-level doc for finalize_dump.
        pending = getattr(doc, _PENDING_ATTR, None)
        if pending is None:
            pending = []
            setattr(doc, _PENDING_ATTR, pending)
        pending.append((subkey, dict(added)))
        modified = True

    return modified


def finalize_dump(text: str, doc: CommentedMap) -> str:
    """Splice any pending settingsYaml additions into the dumped YAML text.

    Must be called by the runner after `yaml.dump(doc, buf)` so that the
    commented-out lines land in the output file. If `patch_values` was never
    called with angular kind, this is a no-op.
    """
    pending = getattr(doc, _PENDING_ATTR, None)
    if not pending:
        return text

    for subkey, added in pending:
        text = _splice_settings_yaml(text, subkey, added)
    return text


def _locate_root(doc: CommentedMap, subkey: Optional[str]) -> Optional[CommentedMap]:
    if subkey is None:
        return doc
    parent = doc.get(subkey)
    if not isinstance(parent, CommentedMap):
        return None
    return parent


def _patch_settings_json(
    raw: str, added: Dict[str, LeafType], removed: List[str]
) -> Optional[str]:
    try:
        obj = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    for path in removed:
        _delete_at_pointer(obj, path)
    for path, leaf_type in added.items():
        _set_at_pointer(obj, path, _json_blank(leaf_type))
    return json.dumps(obj)


def _json_blank(leaf_type: LeafType) -> object:
    if leaf_type == LeafType.STRING:
        return ""
    if leaf_type == LeafType.BOOL:
        return False
    return 0


def _pointer_parts(path: str) -> list[str]:
    if not path.startswith("/"):
        return []
    return path[1:].split("/") if path != "/" else []


def _set_at_pointer(obj: dict, path: str, value: object) -> None:
    parts = _pointer_parts(path)
    if not parts:
        return
    cur: dict = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _delete_at_pointer(obj: dict, path: str) -> None:
    parts = _pointer_parts(path)
    if not parts:
        return
    cur: dict = obj
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            return
        cur = nxt
    cur.pop(parts[-1], None)


def _render_commented_yaml(
    nested: dict, indent_prefix: str
) -> list[str]:
    """Render a nested dict as commented-out YAML lines.

    `indent_prefix` is the whitespace that goes before the `#` on every line
    (matching the block's child indent). Nested structure is expressed by
    adding two spaces *after* the `# `, matching the existing UI chart
    convention, e.g.:

        settingsYaml:
          # OIDCSettings:
          #   authority: ""
    """
    lines: list[str] = []
    _render_commented(nested, indent_prefix, "", lines)
    return lines


def _render_commented(
    obj: dict, outer_indent: str, inner_indent: str, out: list[str]
) -> None:
    for key, value in obj.items():
        if isinstance(value, dict):
            out.append(f"{outer_indent}# {inner_indent}{key}:")
            _render_commented(value, outer_indent, inner_indent + "  ", out)
        else:
            out.append(
                f"{outer_indent}# {inner_indent}{key}: {_render_scalar(value)}"
            )


def _render_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return '""'


def _splice_settings_yaml(
    text: str, subkey: Optional[str], added: Dict[str, LeafType]
) -> str:
    """Insert commented-out additions after the settingsYaml: line.

    Finds the `settingsYaml:` key line (scoped under `subkey:` if provided),
    determines the child indent, and appends commented lines that mirror the
    nested JSON-pointer structure of `added`.
    """
    nested: dict = {}
    for path, leaf_type in added.items():
        _set_at_pointer(nested, path, leaf_type)

    lines = text.split("\n")

    # Locate the `settingsYaml:` line. When subkey is given, only consider
    # occurrences inside the subkey's block (between the subkey line and the
    # next top-level key) to avoid matching a sibling subkey's settingsYaml.
    target_indent: Optional[int] = None
    search_start = 0
    search_end = len(lines)
    if subkey is None:
        target_indent = 0
    else:
        subkey_line = None
        for idx, line in enumerate(lines):
            if line == f"{subkey}:" or line.startswith(f"{subkey}:"):
                subkey_line = idx
                break
        if subkey_line is None:
            return text
        # Child indent: find next non-blank line's leading whitespace.
        for line in lines[subkey_line + 1 :]:
            if line.strip():
                target_indent = len(line) - len(line.lstrip(" "))
                break
        # Bound search to the subkey's block: stop at the next line that
        # starts in column 0 with a non-space character (a sibling top-level
        # key or list item).
        search_start = subkey_line + 1
        search_end = len(lines)
        for idx in range(search_start, len(lines)):
            line = lines[idx]
            if line and not line[0].isspace():
                search_end = idx
                break

    if target_indent is None:
        return text

    key_line_idx = _find_settings_yaml_line(
        lines, target_indent, search_start, search_end
    )
    if key_line_idx is None:
        return text

    child_indent_str = " " * (target_indent + 2)
    commented = _render_commented_yaml(
        _resolve_types(nested), child_indent_str
    )
    if not commented:
        return text

    # If the existing line is `settingsYaml: {}` (or a flow-style variant),
    # rewrite it to `settingsYaml:` so the appended commented children read
    # as siblings of other block-style content rather than dangling under an
    # empty flow map.
    key_line = lines[key_line_idx]
    stripped = key_line.strip()
    if stripped.startswith("settingsYaml:") and stripped != "settingsYaml:":
        remainder = stripped[len("settingsYaml:") :].strip()
        if remainder in ("{}", ""):
            leading = key_line[: len(key_line) - len(key_line.lstrip(" "))]
            lines[key_line_idx] = f"{leading}settingsYaml:"

    insert_at = key_line_idx + 1
    new_lines = lines[:insert_at] + commented + lines[insert_at:]
    return "\n".join(new_lines)


def _find_settings_yaml_line(
    lines: list[str],
    indent: int,
    start: int = 0,
    end: Optional[int] = None,
) -> Optional[int]:
    prefix = " " * indent + "settingsYaml:"
    stop = len(lines) if end is None else end
    for idx in range(start, stop):
        line = lines[idx]
        if line == prefix or line.startswith(prefix + " ") or line == prefix.rstrip():
            return idx
    return None


def _resolve_types(nested: dict) -> dict:
    """Convert LeafType values at leaves into raw scalar placeholders.

    The splicer's renderer emits "true"/"false"/"0"/'""' based on Python
    types, so we convert LeafType.BOOL -> False, NUMBER -> 0, STRING -> "".
    """
    out: dict = {}
    for key, value in nested.items():
        if isinstance(value, dict):
            out[key] = _resolve_types(value)
        elif isinstance(value, LeafType):
            if value == LeafType.BOOL:
                out[key] = False
            elif value == LeafType.NUMBER:
                out[key] = 0
            else:
                out[key] = ""
        else:
            out[key] = value
    return out
