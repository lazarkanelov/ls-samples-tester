"""Tests for TrendTracker and GitHub Pages index generation."""
from __future__ import annotations

import json

from scanner.config import CloudProvider, IaCType
from scanner.models import DeployResult, DeployStatus, ScanReport


def _make_report(date: str = "2026-03-16", successes: int = 3, failures: int = 1) -> ScanReport:
    results = []
    for i in range(successes):
        results.append(
            DeployResult(
                sample_name=f"repo-{i}",
                org="aws-samples",
                status=DeployStatus.SUCCESS,
                duration=5.0,
                stdout="",
                stderr="",
                error_message=None,
                services_used=[],
                deployer_command="cdklocal deploy",
                iac_type=IaCType.CDK,
                cloud_provider=CloudProvider.AWS,
            )
        )
    for i in range(failures):
        results.append(
            DeployResult(
                sample_name=f"fail-{i}",
                org="aws-samples",
                status=DeployStatus.FAILURE,
                duration=3.0,
                stdout="",
                stderr="error",
                error_message="deploy error",
                services_used=[],
                deployer_command="cdklocal deploy",
                iac_type=IaCType.CDK,
                cloud_provider=CloudProvider.AWS,
            )
        )
    return ScanReport(
        results=results,
        scan_date=date,
        total_samples=len(results),
    )


class TestTrendTracker:
    def test_update_creates_trends_file(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report())
        assert (tmp_path / "trends.json").exists()

    def test_update_appends_entry(self, tmp_path):
        from scanner.report.trends import TrendTracker

        trends_path = tmp_path / "trends.json"
        tracker = TrendTracker(trends_path)
        tracker.update(_make_report("2026-03-09"))
        tracker.update(_make_report("2026-03-16"))
        data = json.loads(trends_path.read_text())
        assert len(data) == 2

    def test_update_stores_correct_counts(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report(successes=5, failures=2))
        data = json.loads((tmp_path / "trends.json").read_text())
        entry = data[0]
        assert entry["success"] == 5
        assert entry["failure"] == 2

    def test_update_stores_date(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report("2026-03-16"))
        data = json.loads((tmp_path / "trends.json").read_text())
        assert data[0]["date"] == "2026-03-16"

    def test_update_stores_by_iac_type(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report())
        data = json.loads((tmp_path / "trends.json").read_text())
        assert "by_iac_type" in data[0]
        assert "CDK" in data[0]["by_iac_type"]

    def test_get_chart_data_returns_labels_and_datasets(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report("2026-03-09"))
        tracker.update(_make_report("2026-03-16"))
        chart = tracker.get_chart_data()
        assert "labels" in chart
        assert "datasets" in chart
        assert len(chart["labels"]) == 2
        assert len(chart["datasets"]) >= 2  # at least success + failure series

    def test_get_chart_data_labels_are_dates(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report("2026-03-16"))
        chart = tracker.get_chart_data()
        assert chart["labels"][0] == "2026-03-16"

    def test_update_does_not_duplicate_same_date(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report("2026-03-16"))
        tracker.update(_make_report("2026-03-16"))  # same date
        data = json.loads((tmp_path / "trends.json").read_text())
        assert len(data) == 1  # upsert behaviour

    def test_prune_old_reports_removes_oldest(self, tmp_path):
        import os

        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        for i in range(5):
            d = reports_dir / f"2026-0{i + 1}-01"
            d.mkdir()
            os.utime(d, (i * 1000, i * 1000))
        tracker.prune_old_reports(reports_dir, keep=3)
        remaining = [d for d in reports_dir.iterdir() if d.is_dir()]
        assert len(remaining) == 3


class TestIndexPageGeneration:
    def test_generate_index_creates_file(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report())
        tracker.generate_index(tmp_path)
        assert (tmp_path / "index.html").exists()

    def test_index_contains_canvas_element(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report())
        tracker.generate_index(tmp_path)
        html = (tmp_path / "index.html").read_text()
        assert "<canvas" in html
        assert "trend-chart" in html

    def test_index_contains_report_link(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report("2026-03-16"))
        # Simulate a report directory
        (tmp_path / "2026-03-16").mkdir()
        tracker.generate_index(tmp_path)
        html = (tmp_path / "index.html").read_text()
        assert "2026-03-16" in html
