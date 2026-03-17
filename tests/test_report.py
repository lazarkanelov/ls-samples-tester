"""Tests for HTML report generator."""
from __future__ import annotations

from html.parser import HTMLParser

from scanner.config import CloudProvider, IaCType
from scanner.models import DeployResult, DeployStatus, ScanReport


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

    def test_output_dir_created_if_missing(self, tmp_path):
        from scanner.report.generator import ReportGenerator

        output = tmp_path / "nested" / "output"
        assert not output.exists()
        ReportGenerator(output).generate(_make_report([_make_result()]))
        assert output.exists()
