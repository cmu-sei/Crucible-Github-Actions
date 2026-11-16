"""Patch the `env:` block of a values.yaml document.

Operates on a `ruamel.yaml`-loaded document in place. Returns True iff the
document was modified, so callers can decide whether to write the file back.

Rules (spec: Dotnet-appsettings patcher):
  * At the root (`subkey=None`) the env: block is created if missing.
  * Under a subkey (e.g. "player-api" in parent values.yaml) the env: block
    is NOT created. If missing, we skip — parent values.yaml is hand-curated.
  * Additions are appended at the end of the env: block.
  * Values (see `_value_for`): a number or bool takes its entry in `defaults`
    (the value appsettings.json sets), with numbers of 1e6 or more quoted.
    Strings, and keys with no entry (dotnet-conf), get a blank by type:
    string -> "", bool -> False, number -> 0.
  * Removals delete the key line in place; preceding comments are left alone.
  * Whitespace and dedented comments trailing the env: block stay trailing it,
    rather than being pushed between the old and new last keys — see
    `_move_trailing_block_tail`.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import CommentMark
from ruamel.yaml.scalarstring import DoubleQuotedScalarString
from ruamel.yaml.tokens import CommentToken

from .flatten import LeafType


_BLANK_BY_TYPE: Mapping[LeafType, object] = {
    LeafType.STRING: DoubleQuotedScalarString(""),
    LeafType.BOOL: False,
    LeafType.NUMBER: 0,
}


# Helm loads values-file numbers as float64, and the API charts render env values with
# `tpl ($val | toString)`, which writes 1e6 and larger in scientific notation: 6000000000
# becomes "6e+09", and .NET's configuration binder can't read that as an int or long. Quoted,
# the number reaches the app as written.
_QUOTE_NUMBERS_FROM = 1_000_000


def _value_for(
    key: str, leaf_type: LeafType, defaults: Optional[Mapping[str, object]]
) -> object:
    """The chart value for a key that is new in this release.

    Numbers and bools take the appsettings.json value, because that is what the
    app uses when the key isn't set: 0 or false in a chart can change what the
    app does. Strings get "", as most of the hand-written charts' strings are:
    appsettings.json strings are largely localhost URLs, connection strings and
    development credentials, which don't belong in a chart. A key with no value
    (dotnet-conf passes none) gets the blank for its type.
    """
    value = defaults.get(key) if defaults else None
    if leaf_type is LeafType.BOOL and isinstance(value, bool):
        return value
    if (
        leaf_type is LeafType.NUMBER
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        if abs(value) >= _QUOTE_NUMBERS_FROM:
            return DoubleQuotedScalarString(str(value))
        return value
    return _BLANK_BY_TYPE[leaf_type]


def patch_values(
    doc: CommentedMap,
    subkey: Optional[str],
    added: Dict[str, LeafType],
    removed: List[str],
    defaults: Optional[Mapping[str, object]] = None,
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

    last_before = next(reversed(container), None) if container else None

    for key, leaf_type in added.items():
        if key in container:
            continue
        container[key] = _value_for(key, leaf_type, defaults)
        modified = True

    last_after = next(reversed(container), None) if container else None
    if last_before is not None and last_after != last_before:
        _move_trailing_block_tail(container, last_before, last_after)

    return modified


def _move_trailing_block_tail(
    container: CommentedMap, old_last: str, new_last: str
) -> None:
    """Keep what trailed the block trailing it after appending keys.

    ruamel hangs everything between a mapping's final key and the next line of
    real YAML — blank lines and comments alike — off that final key. Appending
    keys therefore emits them *after* that whole run, which misplaces two things
    a values.yaml routinely has at the end of an env: block:

      * the blank line separating subchart blocks in a parent values.yaml. The
        child file has no separator (its env: block ends at EOF), so leaving it
        between the old and new keys desyncs the pair and fails helm-charts'
        parent/child values-sync check on a release that only added keys.
      * comments introducing the *next* sibling key, e.g. topomojo-api's
        "## Create a seed data file ..." above `seedData:`. Those are dedented
        relative to the env: keys, so appending after them reads as if the new
        setting belongs to seedData.

    Comments indented at or past the block's own key column documented the keys
    inside the block, so they stay where they are.
    """
    entry = container.ca.items.get(old_last)
    if not entry or new_last in container.ca.items:
        return
    token = entry[2]
    if isinstance(token, list):
        token = token[-1] if token else None
    if token is None or not isinstance(getattr(token, "value", None), str):
        return

    # The column the block's keys are written at. `start_mark` on the comment
    # token is where the comment text begins, not where the block is indented.
    lc_data = getattr(getattr(container, "lc", None), "data", None) or {}
    if old_last not in lc_data:
        return
    column = lc_data[old_last][1]

    # The first newline terminates the last rendered line and any end-of-line
    # comment on it; everything past it is a full line of its own.
    head, sep, rest = token.value.partition("\n")
    if not sep:
        return
    lines = rest.splitlines(keepends=True)
    split = len(lines)
    while split and _belongs_after_block(lines[split - 1], column):
        split -= 1
    if split == len(lines):
        return

    token.value = head + sep + "".join(lines[:split])
    container.ca.items[new_last] = [
        None,
        None,
        CommentToken("\n" + "".join(lines[split:]), CommentMark(column), None),
        None,
    ]


def _belongs_after_block(line: str, column: int) -> bool:
    """True for a blank line, or a comment dedented out of the block."""
    stripped = line.strip()
    if not stripped:
        return True
    return stripped.startswith("#") and len(line) - len(line.lstrip()) < column


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
