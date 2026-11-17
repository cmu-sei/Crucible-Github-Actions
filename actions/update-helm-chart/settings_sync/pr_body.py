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


def _code(text: str) -> str:
    """Inline code that survives a backtick in the text."""
    if "`" in text:
        return f"`` {text} ``"
    return f"`{text}`"


def render_settings_section(
    source_repo: str,
    release_tag: str,
    readme_path: Optional[str],
    added: Dict[str, LeafType],
    removed: List[str],
    added_values: Optional[Dict[str, str]] = None,
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
        if added_values:
            lines.append(
                "Each key is listed with the value written to `values.yaml`. "
                "A key the chart already set keeps the chart's value."
            )
            lines.append("")
        for key in sorted(added.keys()):
            if added_values and key in added_values:
                lines.append(f"- `{key}`: {_code(added_values[key])}")
            else:
                lines.append(f"- `{key}`")
        lines.append("")

    if removed:
        lines.append("### Removed")
        for key in sorted(removed):
            lines.append(f"- `{key}`")
        lines.append("")

    return "\n".join(lines).rstrip("\n")
