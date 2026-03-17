"""Local TTL-based cache for GitHub Code Search results.

Stores search results per (org, iac_type) pair keyed by a composite string.
Avoids redundant API calls when re-running discovery within the TTL window.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scanner.config import IaCType
    from scanner.models import Sample

logger = logging.getLogger(__name__)


class ETagCache:
    """JSON file cache keyed by (org, iac_type). Entries expire after ttl_hours."""

    def __init__(self, path: str, ttl_hours: int = 24) -> None:
        self._path = Path(path)
        self._ttl = timedelta(hours=ttl_hours)
        self._data: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get(self, org: str, iac_type: IaCType) -> list[Sample] | None:
        """Return cached samples if the entry exists and is fresh; else None."""
        from scanner.models import Sample

        key = self._key(org, iac_type)
        entry = self._data.get(key)
        if not entry:
            return None

        fetched_at = datetime.fromisoformat(entry["fetched_at"])
        if datetime.now(tz=UTC) - fetched_at > self._ttl:
            logger.debug("Cache entry expired for %s", key)
            return None

        return [Sample.from_dict(r) for r in entry["repos"]]

    def put(self, org: str, iac_type: IaCType, samples: list[Sample]) -> None:
        """Store samples for (org, iac_type) with the current timestamp."""
        key = self._key(org, iac_type)
        self._data[key] = {
            "fetched_at": datetime.now(tz=UTC).isoformat(),
            "repos": [s.to_dict() for s in samples],
        }
        self._save()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(org: str, iac_type: IaCType) -> str:
        return f"{org}:{iac_type.value}"

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load ETag cache from %s: %s", self._path, exc)
                self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2))
        except OSError as exc:
            logger.warning("Could not write ETag cache to %s: %s", self._path, exc)
