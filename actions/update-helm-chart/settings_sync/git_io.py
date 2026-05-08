"""Thin wrapper around `git` subprocess calls. Mockable in tests."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional


def list_tags(repo_dir: Path) -> List[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "tag", "--list", "--sort=-v:refname"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def previous_tag(repo_dir: Path, target_tag: str) -> Optional[str]:
    """Return the tag immediately preceding `target_tag` in version order.

    None when target is not in the tag list or is the oldest tag.
    """
    tags = list_tags(repo_dir)
    try:
        idx = tags.index(target_tag)
    except ValueError:
        return None
    if idx + 1 >= len(tags):
        return None
    return tags[idx + 1]


def show_file_at_ref(
    repo_dir: Path, ref: str, file_path: str
) -> Optional[str]:
    """Return the content of `file_path` at `ref`, or None if not present."""
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "show", f"{ref}:{file_path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout
