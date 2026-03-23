"""Tests for HTML report generator."""
from __future__ import annotations

from html.parser import HTMLParser

from scanner.config import CloudProvider, IaCType
from scanner.models import DeployResult, DeployStatus, FailureCategory, ScanReport


def _make_result(
    status: DeployStatus = DeployStatus.SUCCESS,
    name: str = "test-repo",
    stdout: str = "deploy output",
    stderr: str = "",
    error: str | None = None,
) -> DeployResult:
    r = DeployResult(
        sample_name=name,
        org="aws-samples",
        status=status,
        duration=12.5,
        stdout=stdout,
        stderr=stderr,
        error_message=error,
        services_used=["s3", "lambda"],
        deployer_command="cdklocal deploy",
        iac_type=IaCType.CDK,
        cloud_provider=CloudProvider.AWS,
    )
    return r


def _make_report(results: list[DeployResult]) -> ScanReport:
    return ScanReport(
        results=results,
        scan_date="2026-03-16",
        total_samples=len(results),
        tool_versions={"cdklocal": "2.0.0"},
    )


class TestReportGenerator:
    def test_generate_creates_report_html(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        report = _make_report([_make_result()])
        ReportGenerator(tmp_path).generate(report)
        assert (tmp_path / "report.html").exists()

    def test_generate_produces_valid_html(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        report = _make_report([_make_result()])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        # html.parser raises on fundamental errors
        parser = HTMLParser()
        parser.feed(html)  # no exception = valid

    def test_summary_has_one_row_per_result(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        results = [_make_result(), _make_result(name="repo2")]
        report = _make_report(results)
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        # header row + 2 data rows → at least 3 <tr
        assert html.count("<tr") >= len(results) + 1

    def test_status_badge_classes_present(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        results = [
            _make_result(DeployStatus.SUCCESS),
            _make_result(DeployStatus.FAILURE, name="r2"),
            _make_result(DeployStatus.TIMEOUT, name="r3"),
            _make_result(DeployStatus.UNSUPPORTED, name="r4"),
        ]
        report = _make_report(results)
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "badge-success" in html
        assert "badge-failure" in html
        assert "badge-timeout" in html
        assert "badge-unsupported" in html

    def test_generates_detail_page_per_result(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        results = [_make_result(), _make_result(name="second-repo")]
        report = _make_report(results)
        ReportGenerator(tmp_path).generate(report)
        html_files = list(tmp_path.glob("*.html"))
        # report.html + 2 detail pages
        assert len(html_files) >= 3

    def test_detail_page_contains_pre_blocks(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.FAILURE, stdout="build ok", stderr="Error!")
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        detail_files = [f for f in tmp_path.glob("*-detail.html")]
        assert len(detail_files) == 1
        detail_html = detail_files[0].read_text()
        assert "<pre>" in detail_html

    def test_detail_page_contains_stdout_content(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        result = _make_result(stdout="unique-stdout-marker")
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        detail_files = list(tmp_path.glob("*-detail.html"))
        assert any("unique-stdout-marker" in f.read_text() for f in detail_files)

    def test_report_html_has_failure_category_column(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.FAILURE, name="bad-app", error="failed")
        result.failure_category = FailureCategory.LOCALSTACK_BUG
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "Failure Category" in html
        assert "LOCALSTACK_BUG" in html

    def test_report_html_has_category_breakdown_section(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.FAILURE, name="bad-app", error="not implemented")
        result.failure_category = FailureCategory.LOCALSTACK_BUG
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "Failure Breakdown" in html

    def test_output_dir_created_if_missing(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        output = tmp_path / "nested" / "output"
        assert not output.exists()
        ReportGenerator(output).generate(_make_report([_make_result()]))
        assert output.exists()

    def test_report_html_has_partial_badge_css(self, tmp_path):
        """report.html must define .badge-partial CSS."""
        from scanner.report.generator import ReportGenerator

        report = _make_report([_make_result()])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "badge-partial" in html

    def test_report_html_has_partial_stat_card(self, tmp_path):
        """Stats section must include a PARTIAL count card."""
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.PARTIAL, name="partial-app")
        result.verification_status = "FAILED"
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "Partial" in html or "partial" in html.lower()

    def test_report_html_has_verification_column(self, tmp_path):
        """Results table must have a Verification column header."""
        from scanner.report.generator import ReportGenerator

        report = _make_report([_make_result()])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "Verification" in html

    def test_report_html_partial_result_shows_badge_partial(self, tmp_path):
        """A PARTIAL result must render badge-partial in report.html."""
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.PARTIAL, name="partial-app")
        result.verification_status = "FAILED"
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "badge-partial" in html

    def test_report_html_no_verification_badge_when_status_none(self, tmp_path):
        """When verification_status is None, no verification badge is shown."""
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.SUCCESS)
        # verification_status defaults to None
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        # No verification badge element should appear (CSS class definitions are ok)
        assert 'badge-passed">' not in html
        assert 'badge-failed">' not in html

    def test_detail_html_has_partial_badge_css(self, tmp_path):
        """sample_detail.html must define .badge-partial CSS."""
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.PARTIAL, name="partial-app")
        result.verification_status = "FAILED"
        result.verification_details = "Lambda fn: FAILED"
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        detail_files = list(tmp_path.glob("*-detail.html"))
        assert len(detail_files) == 1
        detail_html = detail_files[0].read_text()
        assert "badge-partial" in detail_html

    def test_detail_html_shows_verification_details(self, tmp_path):
        """Detail page must show verification_details in a pre block."""
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.PARTIAL, name="partial-app")
        result.verification_status = "FAILED"
        result.verification_details = "Lambda my-fn: FAILED (Unhandled)"
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        detail_files = list(tmp_path.glob("*-detail.html"))
        detail_html = detail_files[0].read_text()
        assert "Lambda my-fn: FAILED (Unhandled)" in detail_html

    def test_detail_html_no_verification_section_when_none(self, tmp_path):
        """Detail page must not render verification section when verification_status is None."""
        from scanner.report.generator import ReportGenerator

        result = _make_result(DeployStatus.SUCCESS)
        # verification_status and verification_details default to None
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        detail_files = list(tmp_path.glob("*-detail.html"))
        detail_html = detail_files[0].read_text()
        assert "Verification" not in detail_html


class TestServiceDashboard:
    def test_service_coverage_shown_when_services_used(self, tmp_path):
        """Section appears when at least one result has non-empty services_used."""
        from scanner.report.generator import ReportGenerator

        report = _make_report([_make_result()])  # has services_used=["s3", "lambda"]
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "Service Coverage" in html

    def test_service_coverage_absent_when_no_services(self, tmp_path):
        """Section absent when all results have empty services_used."""
        from scanner.report.generator import ReportGenerator

        result = _make_result()
        result.services_used = []
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "Service Coverage" not in html

    def test_service_coverage_lists_service_name(self, tmp_path):
        """Service name from services_used appears in coverage table."""
        from scanner.report.generator import ReportGenerator

        result = _make_result()
        result.services_used = ["Lambda"]
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        assert "Lambda" in html

    def test_compute_service_stats_success_count(self, tmp_path):
        """_compute_service_stats tallies success correctly."""
        from scanner.report.generator import _compute_service_stats

        result = _make_result(DeployStatus.SUCCESS)
        result.services_used = ["Lambda"]
        report = _make_report([result])
        stats = _compute_service_stats(report)
        assert stats["Lambda"]["success"] == 1
        assert stats["Lambda"]["total"] == 1

    def test_compute_service_stats_counts_across_statuses(self, tmp_path):
        """Stats count success and failure correctly across results."""
        from scanner.report.generator import _compute_service_stats

        r1 = _make_result(DeployStatus.SUCCESS)
        r1.services_used = ["S3"]
        r2 = _make_result(DeployStatus.FAILURE, name="r2")
        r2.services_used = ["S3"]
        stats = _compute_service_stats(_make_report([r1, r2]))
        assert stats["S3"]["total"] == 2
        assert stats["S3"]["success"] == 1
        assert stats["S3"]["failure"] == 1

    def test_compute_service_stats_sorted_by_total(self, tmp_path):
        """Most-used services appear first in stats."""
        from scanner.report.generator import _compute_service_stats

        r1 = _make_result(DeployStatus.SUCCESS)
        r1.services_used = ["Rare"]
        r2 = _make_result(DeployStatus.SUCCESS, name="r2")
        r2.services_used = ["Common", "Rare"]
        r3 = _make_result(DeployStatus.SUCCESS, name="r3")
        r3.services_used = ["Common"]
        stats = _compute_service_stats(_make_report([r1, r2, r3]))
        service_order = list(stats.keys())
        assert service_order[0] == "Common"  # total=2, first
        assert service_order[1] == "Rare"    # total=2, second (alphabetical tie)

    def test_service_heatmap_shows_iac_type(self, tmp_path):
        """IaC type column appears in the heatmap."""
        from scanner.report.generator import ReportGenerator

        result = _make_result()
        result.services_used = ["Lambda"]
        report = _make_report([result])
        ReportGenerator(tmp_path).generate(report)
        html = (tmp_path / "report.html").read_text()
        # _make_result uses IaCType.CDK
        assert "CDK" in html
