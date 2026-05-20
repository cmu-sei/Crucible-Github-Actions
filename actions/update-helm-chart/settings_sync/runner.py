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


_yaml = YAML()
_yaml.preserve_quotes = True


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
