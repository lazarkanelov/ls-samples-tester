"""Tests for DurationTracker."""
from __future__ import annotations

import json


class TestDurationTracker:
    def setup_method(self):
        from scanner.duration_tracker import DurationTracker
        self.DurationTracker = DurationTracker

    def test_record_adds_duration(self):
        tracker = self.DurationTracker()
        tracker.record("aws-samples/my-repo", 120.0)
        assert tracker.get_timeout("aws-samples/my-repo", default=600, min_timeout=60, max_timeout=1200) > 0

    def test_get_timeout_returns_median_times_two(self):
        tracker = self.DurationTracker()
        # Median of [100, 200, 300] = 200; * 2 = 400
        tracker.record("repo", 100.0)
        tracker.record("repo", 200.0)
        tracker.record("repo", 300.0)
        result = tracker.get_timeout("repo", default=600, min_timeout=60, max_timeout=1200)
        assert result == 400

    def test_get_timeout_even_count_uses_average_of_two_middle(self):
        tracker = self.DurationTracker()
        # Median of [100, 300] = 200; * 2 = 400
        tracker.record("repo", 100.0)
        tracker.record("repo", 300.0)
        result = tracker.get_timeout("repo", default=600, min_timeout=60, max_timeout=1200)
        assert result == 400

    def test_get_timeout_uses_default_for_unknown_sample(self):
        tracker = self.DurationTracker()
        result = tracker.get_timeout("unknown-repo", default=600, min_timeout=60, max_timeout=1200)
        assert result == 600

    def test_get_timeout_clamps_to_min(self):
        tracker = self.DurationTracker()
        tracker.record("fast-repo", 10.0)  # median * 2 = 20 < min 60
        result = tracker.get_timeout("fast-repo", default=600, min_timeout=60, max_timeout=1200)
        assert result == 60

    def test_get_timeout_clamps_to_max(self):
        tracker = self.DurationTracker()
        tracker.record("slow-repo", 1000.0)  # median * 2 = 2000 > max 1200
        result = tracker.get_timeout("slow-repo", default=600, min_timeout=60, max_timeout=1200)
        assert result == 1200

    def test_save_and_load_roundtrip(self, tmp_path):
        tracker = self.DurationTracker()
        tracker.record("repo-a", 120.0)
        tracker.record("repo-a", 180.0)
        tracker.record("repo-b", 300.0)

        path = tmp_path / "durations.json"
        tracker.save(path)

        loaded = self.DurationTracker.load(path)
        assert loaded.get_timeout("repo-a", default=600, min_timeout=60, max_timeout=1200) == 300
        assert loaded.get_timeout("repo-b", default=600, min_timeout=60, max_timeout=1200) == 600

    def test_load_returns_empty_tracker_for_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        tracker = self.DurationTracker.load(path)
        assert tracker.get_timeout("any", default=600, min_timeout=60, max_timeout=1200) == 600

    def test_save_creates_parent_directories(self, tmp_path):
        tracker = self.DurationTracker()
        tracker.record("repo", 100.0)
        path = tmp_path / "nested" / "dir" / "durations.json"
        tracker.save(path)
        assert path.exists()
        data = json.loads(path.read_text())
        assert "repo" in data
