"""End-to-end orchestration of the settings-sync phase."""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ruamel.yaml import YAML

from . import git_io
from .diff import compute_diff
from .flatten import (
    LeafType,
    flatten_angular,
    flatten_dotnet,
    flatten_dotnet_conf,
)
from .jsonc import strip_jsonc_comments
from . import patch_angular, patch_dotnet


class SettingsSyncError(RuntimeError):
    """Raised when settings-sync cannot proceed."""


@dataclass(frozen=True)
class RunResult:
    previous_tag: Optional[str]
    added: Dict[str, LeafType]
    removed: List[str]
    child_modified: bool
    parent_modified: bool


# Round-trip settings chosen so that re-emitting an untouched values.yaml is a
# no-op. ruamel re-renders the whole document on dump, so anything left at a
# default that disagrees with the chart's existing style shows up as unrelated
# churn in the release PR.
#
#   indent(sequence=4, offset=2) — charts are written in the `helm create` style,
#     with list items indented under their key:
#         hosts:
#           - host: x
#     ruamel defaults to sequence=2/offset=0, which re-emits every block
#     sequence in the file dedented flush with its parent key:
#         hosts:
#         - host: x
#     helm-charts' parent/child values-sync CI check compares the parent block
#     against the child file as raw text, so that reflow fails the check for a
#     release that only added or removed settings keys.
#
#   width — ruamel folds plain/quoted scalars past 80 columns. Long values such
#     as Authorization__AuthorizationScope wrap at a different column in the
#     parent (indented under the subchart key) than in the child, so folding
#     alone is enough to desync the two files.
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(mapping=2, sequence=4, offset=2)
_yaml.width = 4096


def run(
    *,
    app_repo_dir: Path,
    helm_repo_dir: Path,
    settings_file: str,
    settings_file_kind: str,
    chart_file: str,
    parent_chart_file: Optional[str],
    release_tag: str,
) -> RunResult:
    if settings_file_kind not in (
        "dotnet-appsettings",
        "dotnet-conf",
        "angular-settings",
    ):
        raise SettingsSyncError(
            f"Unknown settings_file_kind: {settings_file_kind!r}"
        )

    prev_tag = git_io.previous_tag(app_repo_dir, release_tag)

    prev_content = (
        git_io.show_file_at_ref(app_repo_dir, prev_tag, settings_file)
        if prev_tag
        else None
    )
    new_content = git_io.show_file_at_ref(
        app_repo_dir, release_tag, settings_file
    )
    if new_content is None:
        raise SettingsSyncError(
            f"Settings file {settings_file!r} not found at {release_tag}."
        )

    prev_flat = _parse_and_flatten(prev_content or "{}", settings_file_kind)
    new_flat = _parse_and_flatten(new_content, settings_file_kind)

    diff = compute_diff(prev_flat, new_flat)

    child_values_path = (
        helm_repo_dir / Path(chart_file).parent / "values.yaml"
    ).resolve()
    parent_values_path = (
        (helm_repo_dir / Path(parent_chart_file).parent / "values.yaml").resolve()
        if parent_chart_file
        else None
    )

    subkey = Path(chart_file).parent.name

    child_modified = _apply(
        child_values_path, settings_file_kind, None, diff.added, diff.removed
    )
    parent_modified = False
    if parent_values_path is not None:
        parent_modified = _apply(
            parent_values_path,
            settings_file_kind,
            subkey,
            diff.added,
            diff.removed,
        )

    return RunResult(
        previous_tag=prev_tag,
        added=diff.added,
        removed=diff.removed,
        child_modified=child_modified,
        parent_modified=parent_modified,
    )


def _parse_and_flatten(raw: str, kind: str) -> Dict[str, LeafType]:
    if kind == "dotnet-appsettings":
        cleaned = strip_jsonc_comments(raw)
        try:
            data = json.loads(cleaned) if cleaned.strip() else {}
        except json.JSONDecodeError as exc:
            raise SettingsSyncError(f"Failed to parse appsettings: {exc}")
        return flatten_dotnet(data)
    if kind == "dotnet-conf":
        return flatten_dotnet_conf(raw)
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        raise SettingsSyncError(f"Failed to parse angular settings: {exc}")
    return flatten_angular(data)


def _apply(
    values_path: Path,
    kind: str,
    subkey: Optional[str],
    added: Dict[str, LeafType],
    removed: List[str],
) -> bool:
    if not values_path.exists():
        return False
    doc = _yaml.load(values_path.read_text())
    if doc is None:
        return False

    if kind in ("dotnet-appsettings", "dotnet-conf"):
        changed = patch_dotnet.patch_values(doc, subkey, added, removed)
    else:
        changed = patch_angular.patch_values(doc, subkey, added, removed)

    if changed:
        buf = io.StringIO()
        _yaml.dump(doc, buf)
        text = patch_angular.finalize_dump(buf.getvalue(), doc)
        values_path.write_text(text)
    return changed
