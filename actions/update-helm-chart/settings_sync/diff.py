"""Compute added and removed leaf paths between two flattened maps.

Modifications (same path, different LeafType) are intentionally ignored:
values.yaml uses blank placeholders, so a type change in the source doesn't
affect the chart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .flatten import LeafType


@dataclass(frozen=True)
class Diff:
    added: Dict[str, LeafType] = field(default_factory=dict)
    removed: List[str] = field(default_factory=list)


def compute_diff(
    prev: Dict[str, LeafType], new: Dict[str, LeafType]
) -> Diff:
    added = {k: v for k, v in new.items() if k not in prev}
    removed = sorted(k for k in prev.keys() if k not in new)
    return Diff(added=added, removed=removed)
