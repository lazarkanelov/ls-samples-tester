"""Per-sample deploy duration history for adaptive timeouts."""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DurationTracker:
    """Tracks historical deploy durations per sample and computes adaptive timeouts."""

    def __init__(self) -> None:
        self._data: dict[str, list[float]] = {}

    def record(self, sample_name: str, duration: float) -> None:
        if sample_name not in self._data:
            self._data[sample_name] = []
        self._data[sample_name].append(duration)

    def get_timeout(
        self, sample_name: str, default: int, min_timeout: int, max_timeout: int
    ) -> int:
        """Return adaptive timeout: median of history * 2, clamped to [min, max].

        Returns *default* when no history exists for *sample_name*.
        """
        history = self._data.get(sample_name, [])
        if not history:
            return default
        sorted_h = sorted(history)
        n = len(sorted_h)
        if n % 2 == 0:
            median = (sorted_h[n // 2 - 1] + sorted_h[n // 2]) / 2
        else:
            median = sorted_h[n // 2]
        return max(min_timeout, min(max_timeout, int(median * 2)))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._data, indent=2))

    @classmethod
    def load(cls, path: Path) -> DurationTracker:
        tracker = cls()
        if path.exists():
            try:
                tracker._data = json.loads(path.read_text())
            except Exception:
                logger.warning("Failed to load durations from %s, starting fresh", path)
        return tracker
