"""Sample registry — persistent JSON store for discovered samples."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from scanner.models import Sample

logger = logging.getLogger(__name__)


class SampleRegistry:
    """Load/save discovered samples to a JSON file with incremental update support."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def load(self) -> list[Sample]:
        """Load all samples from registry. Returns empty list if file missing."""
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text())
            return [Sample.from_dict(d) for d in data]
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to load registry %s: %s", self._path, exc)
            return []

    def save(self, samples: list[Sample]) -> None:
        """Overwrite registry with the given samples."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps([s.to_dict() for s in samples], indent=2)
        )

    def save_partial(self, org: str, new_samples: list[Sample]) -> None:
        """Merge new_samples for a given org into the registry (replacing that org's entries)."""
        existing = self.load()
        # Keep entries from other orgs, replace this org's entries
        other_orgs = [s for s in existing if s.org != org]
        merged = other_orgs + new_samples
        self.save(merged)

    def is_new_or_updated(self, candidate: Sample, existing: list[Sample]) -> bool:
        """Return True if candidate is not in existing or has a newer updated_at."""
        for s in existing:
            if s.name == candidate.name and s.org == candidate.org:
                return candidate.updated_at > s.updated_at
        return True  # not found → it's new
