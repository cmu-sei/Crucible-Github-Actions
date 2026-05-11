#!/usr/bin/env python3

"""
Utility invoked by the Update Helm Chart composite action.

Responsibilities:
  * Normalize an application version from a release tag.
  * Determine the release type (major/minor/patch) relative to the existing appVersion.
  * Update the Chart.yaml for the application to set appVersion and bump chart version.
  * Optionally bump parent chart versions.
  * Emit a JSON payload with the before/after state so the caller can surface outputs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from settings_sync import SettingsSyncError, run as run_settings_sync  # noqa: E402

SEMVER_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class ChartUpdateError(RuntimeError):
    """Raised when the script cannot safely update the chart metadata."""


def extract_semver(version_source: str) -> Tuple[str, Tuple[int, int, int]]:
    """
    Extract the first semantic version from the provided string.

    Returns the string representation and the parsed tuple.
    """
    match = SEMVER_RE.search(version_source)
    if not match:
        raise ChartUpdateError(f"Unable to find semantic version inside '{version_source}'.")
    major, minor, patch = match.groups()
    return match.group(0), (int(major), int(minor), int(patch))


def determine_release_type(
    old_version: Optional[str], new_version_tuple: Tuple[int, int, int]
) -> str:
    """
    Decide whether the release is a major/minor/patch change.
    Falls back to 'patch' when no previous version is available.
    """
    if not old_version:
        return "patch"

    try:
        _, old_tuple = extract_semver(old_version)
    except ChartUpdateError:
        return "patch"

    new_major, new_minor, new_patch = new_version_tuple
    old_major, old_minor, old_patch = old_tuple

    if (new_major, new_minor, new_patch) < (old_major, old_minor, old_patch):
        raise ChartUpdateError(
            f"New version {new_major}.{new_minor}.{new_patch} is older than existing appVersion "
            f"{old_major}.{old_minor}.{old_patch}."
        )

    if new_major != old_major:
        return "major"
    if new_minor != old_minor:
        return "minor"
    if new_patch != old_patch:
        return "patch"

    # No change in semantic version components.
    return "none"


def bump_semver(version: str, release_type: str) -> str:
    """
    Increment the provided version string according to the release type.
    """
    _, (major, minor, patch) = extract_semver(version)

    if release_type == "major":
        return f"{major + 1}.0.0"
    if release_type == "minor":
        return f"{major}.{minor + 1}.0"
    if release_type == "patch":
        return f"{major}.{minor}.{patch + 1}"

    raise ChartUpdateError(f"Unsupported release type '{release_type}'.")


def load_yaml(path: Path) -> Dict:
    if not path.exists():
        raise ChartUpdateError(f"Expected Chart.yaml at '{path}' but the file does not exist.")
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


def dump_yaml(path: Path, data: Dict) -> None:
    with path.open("w", encoding="utf-8") as stream:
        yaml.safe_dump(data, stream, sort_keys=False)


def ensure_chart_version(chart: Dict) -> str:
    version = chart.get("version")
    if not isinstance(version, str):
        raise ChartUpdateError("Chart.yaml is missing a string 'version' field.")
    return version


@dataclass
class ChartUpdateResult:
    old_app_version: str
    new_app_version: str
    old_chart_version: str
    new_chart_version: str
    release_type: str
    chart_modified: bool


def update_chart(
    chart_path: Path,
    new_version: str,
    release_type: str,
) -> ChartUpdateResult:
    """Update the target chart and return metadata about the operation."""
    chart = load_yaml(chart_path)
    old_app_version = chart.get("appVersion")
    old_chart_version = ensure_chart_version(chart)

    _, new_version_tuple = extract_semver(new_version)

    effective_release_type = release_type
    if release_type == "auto":
        effective_release_type = determine_release_type(old_app_version, new_version_tuple)

    chart_modified = effective_release_type != "none"

    if chart_modified:
        if "appVersion" in chart:
            chart["appVersion"] = new_version
        new_chart_version = bump_semver(old_chart_version, effective_release_type)
        chart["version"] = new_chart_version
        dump_yaml(chart_path, chart)
    else:
        new_chart_version = old_chart_version

    return ChartUpdateResult(
        old_app_version=str(old_app_version) if old_app_version is not None else "",
        new_app_version=new_version,
        old_chart_version=old_chart_version,
        new_chart_version=new_chart_version,
        release_type=effective_release_type,
        chart_modified=chart_modified,
    )


def write_github_output(path: Optional[str], payload: Dict[str, Any]) -> None:
    """Append composite action outputs to the GITHUB_OUTPUT file."""
    if not path:
        return

    output_path = Path(path)
    with output_path.open("a", encoding="utf-8") as handle:
        for key, value in payload.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                serialized = json.dumps(value)
            elif isinstance(value, bool):
                serialized = "true" if value else "false"
            else:
                serialized = str(value)
            handle.write(f"{key}={serialized}\n")


def compute_branch_name(app_name: str, app_version: Optional[str], release_tag: Optional[str]) -> str:
    version = (app_version or "").strip()
    if not version:
        try:
            version, _ = extract_semver(release_tag or "")
        except ChartUpdateError:
            version = "latest"

    slug = re.sub(r"[^a-z0-9]+", "-", app_name.lower()).strip("-") or "app"
    return f"update-{slug}-{version}"


def handle_update(args: argparse.Namespace) -> int:
    helm_repo_dir = Path(args.helm_repo_dir).resolve()
    chart_path = (helm_repo_dir / args.chart_file).resolve()

    new_version, _ = extract_semver(args.release_tag)

    result = update_chart(chart_path, new_version, "auto")

    parent_update: Dict[str, str] = {}
    parent_chart_file = (args.parent_chart_file or "").strip()
    if parent_chart_file and result.release_type != "none":
        parent_result = update_chart(
            chart_path=(helm_repo_dir / parent_chart_file).resolve(),
            new_version=new_version,
            release_type=result.release_type,
        )
        if parent_result.chart_modified:
            parent_update = {
                "path": parent_chart_file,
                "old_version": parent_result.old_chart_version,
                "new_version": parent_result.new_chart_version,
            }

    branch_name = ""
    if args.app_name:
        branch_name = compute_branch_name(
            args.app_name, result.new_app_version, args.release_tag
        )

    settings_added: Dict[str, str] = {}
    settings_removed: list = []
    previous_release_tag = ""
    settings_changed = False

    if args.settings_file:
        if not args.settings_file_kind:
            raise ChartUpdateError(
                "--settings-file-kind is required when --settings-file is set."
            )
        sync = run_settings_sync(
            app_repo_dir=Path(args.app_repo_dir).resolve(),
            helm_repo_dir=helm_repo_dir,
            settings_file=args.settings_file,
            settings_file_kind=args.settings_file_kind,
            chart_file=args.chart_file,
            parent_chart_file=args.parent_chart_file or None,
            release_tag=args.release_tag,
        )
        settings_added = {k: v.value for k, v in sync.added.items()}
        settings_removed = list(sync.removed)
        previous_release_tag = sync.previous_tag or ""
        settings_changed = bool(settings_added or settings_removed)

    has_changes = (
        result.chart_modified or bool(parent_update) or settings_changed
    )

    result_payload: Dict[str, Any] = {
        "old_app_version": result.old_app_version,
        "new_app_version": result.new_app_version,
        "old_chart_version": result.old_chart_version,
        "new_chart_version": result.new_chart_version,
        "release_type": result.release_type,
        "chart_modified": result.chart_modified,
        "parent_chart_update": parent_update or None,
        "branch_name": branch_name,
        "has_changes": has_changes,
        "settings_added": settings_added,
        "settings_removed": settings_removed,
        "settings_changed": settings_changed,
        "previous_release_tag": previous_release_tag,
    }

    if args.result_file:
        result_file = Path(args.result_file)
        result_file.parent.mkdir(parents=True, exist_ok=True)
        with result_file.open("w", encoding="utf-8") as stream:
            json.dump(result_payload, stream)

    print(json.dumps(result_payload, indent=2))

    write_github_output(
        args.github_output,
        {
            "new_app_version": result.new_app_version,
            "release_type": result.release_type,
            "new_chart_version": result.new_chart_version,
            "parent_chart_update": parent_update or None,
            "chart_modified": result.chart_modified,
            "branch_name": branch_name,
            "has_changes": has_changes,
            "settings_added": settings_added,
            "settings_removed": settings_removed,
            "settings_changed": settings_changed,
            "previous_release_tag": previous_release_tag,
        },
    )

    return 0


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update Helm chart metadata and emit composite-action outputs."
    )
    parser.add_argument("--helm-repo-dir", required=True)
    parser.add_argument("--chart-file", required=True)
    parser.add_argument("--parent-chart-file", default="")
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--result-file", default="")
    parser.add_argument("--app-name", default="")
    parser.add_argument("--github-output", default="")
    parser.add_argument("--settings-file", default="")
    parser.add_argument("--settings-file-kind", default="")
    parser.add_argument("--source-repo", default="")
    parser.add_argument("--app-repo-dir", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        return handle_update(args)
    except (ChartUpdateError, SettingsSyncError) as exc:
        print(f"[update_helm_chart] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
