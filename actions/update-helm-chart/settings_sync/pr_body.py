"""Render the two PR-body fragments produced by the settings-sync phase."""
from __future__ import annotations

from typing import Dict, List, Optional

from .flatten import LeafType


def _release_url(source_repo: str, tag: str) -> str:
    return f"https://github.com/{source_repo}/releases/tag/{tag}"


def render_release_line(app_name: str, source_repo: str, release_tag: str) -> str:
    url = _release_url(source_repo, release_tag)
    return (
        f"Automated update for {app_name} to version "
        f"[{release_tag}]({url})."
    )


def render_settings_section(
    source_repo: str,
    release_tag: str,
    readme_path: Optional[str],
    added: Dict[str, LeafType],
    removed: List[str],
) -> Optional[str]:
    if not added and not removed:
        return None

    url = _release_url(source_repo, release_tag)
    lines: list[str] = ["## Settings changes to review", ""]
    lead = (
        f"The following settings were introduced in [{release_tag}]({url})."
    )
    if readme_path:
        lead += f"\nREADME updates may be needed in {readme_path}."
    lines.append(lead)
    lines.append("")

    if added:
        lines.append("### Added")
        for key in sorted(added.keys()):
            lines.append(f"- `{key}`")
        lines.append("")

    if removed:
        lines.append("### Removed")
        for key in sorted(removed):
            lines.append(f"- `{key}`")
        lines.append("")

    return "\n".join(lines).rstrip("\n")
