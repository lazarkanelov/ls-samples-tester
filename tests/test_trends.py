"""Tests for TrendTracker and GitHub Pages index generation."""
from __future__ import annotations

import json
from pathlib import Path

from scanner.config import CloudProvider, IaCType
from scanner.models import DeployResult, DeployStatus, FailureCategory, ScanReport


def _make_result(
    name: str,
    status: DeployStatus,
    org: str = "aws-samples",
    iac_type: IaCType = IaCType.CDK,
) -> DeployResult:
    return DeployResult(
        sample_name=name,
        org=org,
        status=status,
        duration=5.0,
        stdout="",
        stderr="",
        error_message=None if status == DeployStatus.SUCCESS else "error",
        services_used=[],
        deployer_command="cmd",
        iac_type=iac_type,
        cloud_provider=CloudProvider.AWS,
    )


def _write_results_file(path: Path, results: list[dict[str, object]], date: str = "2026-03-09") -> None:
    """Write a fake results JSON file in ScanReport.to_dict() format."""
    data: dict[str, object] = {
        "scan_date": date,
        "total_samples": len(results),
        "results": results,
        "tool_versions": {},
        "summary": {},
    }
    path.write_text(json.dumps(data))


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


class TestTrendsByFailureCategory:
    def test_update_stores_by_failure_category(self, tmp_path):
        from scanner.report.trends import TrendTracker

        report = _make_report(successes=2, failures=1)
        report.results[-1].failure_category = FailureCategory.LOCALSTACK_BUG
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report)
        data = json.loads((tmp_path / "trends.json").read_text())
        assert "by_failure_category" in data[0]
        assert data[0]["by_failure_category"]["LOCALSTACK_BUG"] == 1

    def test_update_by_failure_category_empty_when_no_failures(self, tmp_path):
        from scanner.report.trends import TrendTracker

        report = _make_report(successes=3, failures=0)
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report)
        data = json.loads((tmp_path / "trends.json").read_text())
        assert data[0]["by_failure_category"] == {}

    def test_index_shows_failure_breakdown(self, tmp_path):
        from scanner.report.trends import TrendTracker

        report = _make_report(successes=2, failures=1)
        report.results[-1].failure_category = FailureCategory.LOCALSTACK_BUG
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report)
        tracker.generate_index(tmp_path)
        html = (tmp_path / "index.html").read_text()
        assert "Failure Breakdown" in html
        assert "LOCALSTACK_BUG" in html


class TestPartialDataset:
    def test_get_chart_data_includes_partial_dataset(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report())
        chart = tracker.get_chart_data()
        labels = [ds["label"] for ds in chart["datasets"]]
        assert "Partial" in labels

    def test_partial_count_stored_in_entry(self, tmp_path):
        from scanner.report.trends import TrendTracker

        report = _make_report(successes=2, failures=1)
        report.results.append(_make_result("partial-0", DeployStatus.PARTIAL))
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report)
        data = json.loads((tmp_path / "trends.json").read_text())
        assert data[0]["partial"] == 1

    def test_partial_dataset_values_correct(self, tmp_path):
        from scanner.report.trends import TrendTracker

        report = _make_report(successes=2, failures=1)
        report.results.append(_make_result("partial-0", DeployStatus.PARTIAL))
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report)
        chart = tracker.get_chart_data()
        partial_ds = next(ds for ds in chart["datasets"] if ds["label"] == "Partial")
        assert partial_ds["data"][0] == 1


class TestRegressionDetection:
    def test_detect_regressions_empty_when_no_results_dir(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        report = _make_report("2026-03-16")
        tracker.update(report, results_dir=None)
        data = json.loads((tmp_path / "trends.json").read_text())
        assert data[0]["regressions"] == []

    def test_detect_regressions_empty_when_only_current_file(self, tmp_path):
        from scanner.report.trends import TrendTracker

        results_dir = tmp_path / "results"
        results_dir.mkdir()
        report = _make_report("2026-03-16", successes=2, failures=1)
        # Write current file — no previous file exists
        _write_results_file(
            results_dir / "2026-03-16.json",
            [r.to_dict() for r in report.results],
            date="2026-03-16",
        )
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report, results_dir=results_dir)
        data = json.loads((tmp_path / "trends.json").read_text())
        assert data[0]["regressions"] == []

    def test_detect_regressions_finds_pass_to_fail(self, tmp_path):
        from scanner.report.trends import TrendTracker

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        # Previous file: sample "repo-0" was SUCCESS
        prev_result = _make_result("repo-0", DeployStatus.SUCCESS)
        _write_results_file(
            results_dir / "2026-03-09.json",
            [prev_result.to_dict()],
            date="2026-03-09",
        )

        # Current report: same sample is now FAILURE
        report = ScanReport(
            results=[_make_result("repo-0", DeployStatus.FAILURE)],
            scan_date="2026-03-16",
            total_samples=1,
        )
        _write_results_file(
            results_dir / "2026-03-16.json",
            [r.to_dict() for r in report.results],
            date="2026-03-16",
        )
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report, results_dir=results_dir)
        data = json.loads((tmp_path / "trends.json").read_text())
        regressions = data[0]["regressions"]
        assert len(regressions) == 1
        assert regressions[0]["name"] == "aws-samples/repo-0"
        assert regressions[0]["from"] == "SUCCESS"
        assert regressions[0]["to"] == "FAILURE"

    def test_detect_regressions_ignores_new_samples(self, tmp_path):
        from scanner.report.trends import TrendTracker

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        # Previous file: different sample
        prev_result = _make_result("old-sample", DeployStatus.SUCCESS)
        _write_results_file(
            results_dir / "2026-03-09.json",
            [prev_result.to_dict()],
            date="2026-03-09",
        )

        # Current: new sample that wasn't in previous → not a regression
        report = ScanReport(
            results=[_make_result("new-sample", DeployStatus.FAILURE)],
            scan_date="2026-03-16",
            total_samples=1,
        )
        _write_results_file(
            results_dir / "2026-03-16.json",
            [r.to_dict() for r in report.results],
            date="2026-03-16",
        )
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report, results_dir=results_dir)
        data = json.loads((tmp_path / "trends.json").read_text())
        assert data[0]["regressions"] == []

    def test_detect_regressions_ignores_fail_to_fail(self, tmp_path):
        from scanner.report.trends import TrendTracker

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        prev_result = _make_result("repo-0", DeployStatus.FAILURE)
        _write_results_file(
            results_dir / "2026-03-09.json",
            [prev_result.to_dict()],
            date="2026-03-09",
        )

        report = ScanReport(
            results=[_make_result("repo-0", DeployStatus.FAILURE)],
            scan_date="2026-03-16",
            total_samples=1,
        )
        _write_results_file(
            results_dir / "2026-03-16.json",
            [r.to_dict() for r in report.results],
            date="2026-03-16",
        )
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report, results_dir=results_dir)
        data = json.loads((tmp_path / "trends.json").read_text())
        assert data[0]["regressions"] == []

    def test_detect_regressions_partial_scan_guard(self, tmp_path):
        from scanner.report.trends import TrendTracker

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        # Previous file: 5 samples (all SUCCESS)
        prev_results = [_make_result(f"repo-{i}", DeployStatus.SUCCESS).to_dict() for i in range(5)]
        _write_results_file(
            results_dir / "2026-03-09.json",
            prev_results,
            date="2026-03-09",
        )

        # Current: 10 samples (prev has only 50% of current → guard triggers)
        report = ScanReport(
            results=[_make_result(f"repo-{i}", DeployStatus.FAILURE) for i in range(10)],
            scan_date="2026-03-16",
            total_samples=10,
        )
        _write_results_file(
            results_dir / "2026-03-16.json",
            [r.to_dict() for r in report.results],
            date="2026-03-16",
        )
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report, results_dir=results_dir)
        data = json.loads((tmp_path / "trends.json").read_text())
        # Guard: prev (5) < 80% of current (10) → no regressions reported
        assert data[0]["regressions"] == []

    def test_detect_regressions_finds_partial_regression(self, tmp_path):
        from scanner.report.trends import TrendTracker

        results_dir = tmp_path / "results"
        results_dir.mkdir()

        prev_result = _make_result("repo-0", DeployStatus.SUCCESS)
        _write_results_file(
            results_dir / "2026-03-09.json",
            [prev_result.to_dict()],
            date="2026-03-09",
        )

        # SUCCESS → PARTIAL is also a regression
        report = ScanReport(
            results=[_make_result("repo-0", DeployStatus.PARTIAL)],
            scan_date="2026-03-16",
            total_samples=1,
        )
        _write_results_file(
            results_dir / "2026-03-16.json",
            [r.to_dict() for r in report.results],
            date="2026-03-16",
        )
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report, results_dir=results_dir)
        data = json.loads((tmp_path / "trends.json").read_text())
        regressions = data[0]["regressions"]
        assert len(regressions) == 1
        assert regressions[0]["to"] == "PARTIAL"


class TestIaCChartData:
    def test_get_iac_chart_data_returns_labels_and_datasets(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report("2026-03-16"))
        chart = tracker.get_iac_chart_data()
        assert "labels" in chart
        assert "datasets" in chart
        assert len(chart["labels"]) == 1

    def test_iac_chart_data_reflects_iac_types(self, tmp_path):
        from scanner.report.trends import TrendTracker

        report = _make_report()
        # All results are CDK (from _make_report helper)
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report)
        chart = tracker.get_iac_chart_data()
        dataset_labels = [ds["label"] for ds in chart["datasets"]]
        assert "CDK" in dataset_labels


class TestCategoryChartData:
    def test_get_category_chart_data_returns_labels_and_datasets(self, tmp_path):
        from scanner.report.trends import TrendTracker

        report = _make_report(successes=2, failures=1)
        report.results[-1].failure_category = FailureCategory.LOCALSTACK_BUG
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report)
        chart = tracker.get_category_chart_data()
        assert "labels" in chart
        assert "datasets" in chart

    def test_category_chart_data_reflects_failure_categories(self, tmp_path):
        from scanner.report.trends import TrendTracker

        report = _make_report(successes=2, failures=1)
        report.results[-1].failure_category = FailureCategory.LOCALSTACK_BUG
        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(report)
        chart = tracker.get_category_chart_data()
        dataset_labels = [ds["label"] for ds in chart["datasets"]]
        assert "LOCALSTACK_BUG" in dataset_labels


class TestIndexPageRegressions:
    def test_index_shows_regression_section_when_regressions_exist(self, tmp_path):
        from scanner.report.trends import TrendTracker

        # Directly inject a trend entry with regressions
        trends_path = tmp_path / "trends.json"
        entry = {
            "date": "2026-03-16",
            "total": 2,
            "success": 1,
            "failure": 1,
            "timeout": 0,
            "unsupported": 0,
            "skipped": 0,
            "partial": 0,
            "by_iac_type": {},
            "by_cloud": {},
            "by_failure_category": {},
            "regressions": [{"name": "aws-samples/repo-0", "from": "SUCCESS", "to": "FAILURE"}],
        }
        trends_path.write_text(json.dumps([entry]))
        tracker = TrendTracker(trends_path)
        tracker.generate_index(tmp_path)
        html = (tmp_path / "index.html").read_text()
        assert "Regressions" in html
        assert "aws-samples/repo-0" in html

    def test_index_no_regression_section_when_empty(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report())
        tracker.generate_index(tmp_path)
        html = (tmp_path / "index.html").read_text()
        # The regression content block should not appear when there are no regressions
        assert "Regressions This Week" not in html

    def test_index_has_iac_chart_canvas(self, tmp_path):
        from scanner.report.trends import TrendTracker

        tracker = TrendTracker(tmp_path / "trends.json")
        tracker.update(_make_report())
        tracker.generate_index(tmp_path)
        html = (tmp_path / "index.html").read_text()
        assert "iac-chart" in html
