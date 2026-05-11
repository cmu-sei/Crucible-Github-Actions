#!/usr/bin/env python3
"""CLI wrapper to render the PR-body 'Settings changes to review' section."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from settings_sync.flatten import LeafType
from settings_sync.pr_body import render_settings_section


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--readme-path", default="")
    parser.add_argument("--added", default="{}")
    parser.add_argument("--removed", default="[]")
    args = parser.parse_args()

    added_raw = json.loads(args.added) if args.added.strip() else {}
    removed = json.loads(args.removed) if args.removed.strip() else []

    added: dict[str, LeafType] = {
        k: LeafType(v) for k, v in added_raw.items()
    }

    section = render_settings_section(
        source_repo=args.source_repo,
        release_tag=args.release_tag,
        readme_path=args.readme_path or None,
        added=added,
        removed=removed,
    )
    if section:
        print(section)
    return 0


if __name__ == "__main__":
    sys.exit(main())
