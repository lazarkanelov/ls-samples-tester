"""Priority-based sorting for discovered samples."""
from __future__ import annotations

from scanner.config import IaCType
from scanner.models import Sample


def sort_samples_by_priority(samples: list[Sample], priority: list[IaCType]) -> list[Sample]:
    """Sort samples by IaC type priority, preserving relative order within each type.

    IaC types not present in the priority list are placed last. The sort is stable
    so samples of the same type retain their original order (typically updated_at DESC).
    """
    priority_index = {iac_type: idx for idx, iac_type in enumerate(priority)}
    # Types not in priority list get an index beyond the end
    fallback = len(priority)
    return sorted(samples, key=lambda s: priority_index.get(s.iac_type, fallback))
