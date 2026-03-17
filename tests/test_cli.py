"""Tests for CLI entry points using Click's CliRunner."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from scanner.cli import cli
from scanner.config import IaCType
from scanner.models import CloudProvider, Sample


class TestCliHelp:
    def test_root_help_shows_all_commands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "discover" in result.output
        assert "scan" in result.output
        assert "report" in result.output
        assert "run" in result.output

    def test_discover_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["discover", "--help"])
        assert result.exit_code == 0
        assert "--max-repos-per-org" in result.output

    def test_scan_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--help"])
        assert result.exit_code == 0
        assert "--external-localstack" in result.output

    def test_scan_help_shows_localstack_image(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["scan", "--help"])
        assert result.exit_code == 0
        assert "--localstack-image" in result.output

    def test_run_help_shows_localstack_image(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "--localstack-image" in result.output

    def test_report_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--help"])
        assert result.exit_code == 0
        assert "--input" in result.output
        assert "--output" in result.output


def _make_sample(name: str, iac_type: IaCType) -> Sample:
    return Sample(
        name=name,
        org="test-org",
        url=f"https://github.com/test-org/{name}",
        iac_type=iac_type,
        cloud_provider=CloudProvider.AWS,
        description="",
        topics=[],
        language="",
        default_branch="main",
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


class TestScanCommand:
    def test_scan_exits_with_error_when_no_registry(self, tmp_path):
        """scan command should exit(1) when registry is empty."""
        runner = CliRunner()
        with patch("scanner.cli.Config") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.registry_path = str(tmp_path / "missing_registry.json")
            mock_cfg_cls.return_value = mock_cfg

            result = runner.invoke(cli, ["scan"])
            assert result.exit_code == 1
            assert "No samples" in result.output or "discover" in result.output

    def test_scan_limit_uses_highest_priority_samples(self, tmp_path):
        """scan --limit N deploys N highest-priority samples, not first N by insertion order."""
        # CDK is first by insertion order; Terraform is second — but Terraform has higher priority.
        cdk_sample = _make_sample("cdk-app", IaCType.CDK)
        tf_sample = _make_sample("tf-app", IaCType.TERRAFORM)

        runner = CliRunner()
        with (
            patch("scanner.cli.Config") as mock_cfg_cls,
            patch("scanner.discovery.registry.SampleRegistry") as mock_reg_cls,
            patch("scanner.priority.sort_samples_by_priority", wraps=__import__("scanner.priority", fromlist=["sort_samples_by_priority"]).sort_samples_by_priority) as mock_sort,
            patch("scanner.runner.orchestrator.ScanOrchestrator") as mock_orch_cls,
            patch("scanner.runner.localstack.LocalStackManager") as mock_ls_cls,
            patch("scanner.report.generator.ReportGenerator"),
            patch("scanner.report.trends.TrendTracker"),
            patch("scanner.runner.orchestrator._prune_old_results"),
        ):
            mock_cfg = MagicMock()
            mock_cfg.scan_priority = [IaCType.TERRAFORM, IaCType.AZURE_BICEP, IaCType.CDK]
            mock_cfg.results_dir = str(tmp_path / "results")
            mock_cfg.reports_dir = str(tmp_path / "reports")
            mock_cfg.trends_path = str(tmp_path / "trends.json")
            mock_cfg_cls.return_value = mock_cfg

            mock_reg = MagicMock()
            mock_reg.load.return_value = [cdk_sample, tf_sample]  # CDK first by insertion
            mock_reg_cls.return_value = mock_reg

            mock_orch = MagicMock()
            scan_report = MagicMock()
            scan_report.scan_date = "2024-01-01"
            scan_report.to_json.return_value = "{}"
            scan_report.success_count = 1
            scan_report.failure_count = 0
            scan_report.timeout_count = 0
            scan_report.unsupported_count = 0
            mock_orch.run.return_value = scan_report
            mock_orch_cls.return_value = mock_orch

            mock_ls = MagicMock()
            mock_ls.__enter__ = MagicMock(return_value=mock_ls)
            mock_ls.__exit__ = MagicMock(return_value=False)
            mock_ls_cls.return_value = mock_ls

            result = runner.invoke(cli, ["scan", "--limit", "1"])

        assert result.exit_code == 0, result.output
        # sort_samples_by_priority was called (sort happened before limit)
        mock_sort.assert_called_once()
        # orchestrator received only the Terraform sample (highest priority), not CDK (first by insertion)
        called_samples = mock_orch.run.call_args.kwargs["samples"]
        assert len(called_samples) == 1
        assert called_samples[0].iac_type == IaCType.TERRAFORM


    def test_scan_localstack_image_flag_overrides_config(self, tmp_path):
        """--localstack-image overrides config.localstack_image before LocalStackManager is created."""
        tf_sample = _make_sample("tf-app", IaCType.TERRAFORM)

        runner = CliRunner()
        with (
            patch("scanner.cli.Config") as mock_cfg_cls,
            patch("scanner.discovery.registry.SampleRegistry") as mock_reg_cls,
            patch("scanner.runner.orchestrator.ScanOrchestrator") as mock_orch_cls,
            patch("scanner.runner.localstack.LocalStackManager") as mock_ls_cls,
            patch("scanner.report.generator.ReportGenerator"),
            patch("scanner.report.trends.TrendTracker"),
            patch("scanner.runner.orchestrator._prune_old_results"),
        ):
            mock_cfg = MagicMock()
            mock_cfg.scan_priority = [IaCType.TERRAFORM]
            mock_cfg.results_dir = str(tmp_path / "results")
            mock_cfg.reports_dir = str(tmp_path / "reports")
            mock_cfg.trends_path = str(tmp_path / "trends.json")
            mock_cfg_cls.return_value = mock_cfg

            mock_reg = MagicMock()
            mock_reg.load.return_value = [tf_sample]
            mock_reg_cls.return_value = mock_reg

            mock_orch = MagicMock()
            scan_report = MagicMock()
            scan_report.scan_date = "2024-01-01"
            scan_report.to_json.return_value = "{}"
            scan_report.success_count = 1
            scan_report.failure_count = 0
            scan_report.timeout_count = 0
            scan_report.unsupported_count = 0
            mock_orch.run.return_value = scan_report
            mock_orch_cls.return_value = mock_orch

            mock_ls = MagicMock()
            mock_ls.__enter__ = MagicMock(return_value=mock_ls)
            mock_ls.__exit__ = MagicMock(return_value=False)
            mock_ls_cls.return_value = mock_ls

            result = runner.invoke(cli, ["scan", "--localstack-image", "custom:v1"])

        assert result.exit_code == 0, result.output
        # config.localstack_image must be set to the custom image before LocalStackManager
        assert mock_cfg.localstack_image == "custom:v1"


class TestRunCommand:
    def test_run_localstack_image_flag_passes_through(self, tmp_path):
        """run --localstack-image passes the image value into the scan phase."""
        tf_sample = _make_sample("tf-app", IaCType.TERRAFORM)

        runner = CliRunner()
        with (
            patch("scanner.cli.Config") as mock_cfg_cls,
            patch("scanner.discovery.registry.SampleRegistry") as mock_reg_cls,
            patch("scanner.discovery.github_client.GitHubClient") as mock_gh_cls,
            patch("scanner.discovery.etag_cache.ETagCache"),
            patch("scanner.runner.orchestrator.ScanOrchestrator") as mock_orch_cls,
            patch("scanner.runner.localstack.LocalStackManager") as mock_ls_cls,
            patch("scanner.report.generator.ReportGenerator"),
            patch("scanner.report.trends.TrendTracker"),
            patch("scanner.runner.orchestrator._prune_old_results"),
        ):
            mock_cfg = MagicMock()
            mock_cfg.scan_priority = [IaCType.TERRAFORM]
            mock_cfg.target_orgs = ["aws-samples"]
            mock_cfg.results_dir = str(tmp_path / "results")
            mock_cfg.reports_dir = str(tmp_path / "reports")
            mock_cfg.trends_path = str(tmp_path / "trends.json")
            mock_cfg_cls.return_value = mock_cfg

            mock_gh = MagicMock()
            mock_gh.discover_all.return_value = []
            mock_gh_cls.return_value = mock_gh

            mock_reg = MagicMock()
            mock_reg.load.return_value = [tf_sample]
            mock_reg_cls.return_value = mock_reg

            mock_orch = MagicMock()
            scan_report = MagicMock()
            scan_report.scan_date = "2024-01-01"
            scan_report.to_json.return_value = "{}"
            scan_report.success_count = 1
            scan_report.failure_count = 0
            scan_report.timeout_count = 0
            scan_report.unsupported_count = 0
            mock_orch.run.return_value = scan_report
            mock_orch_cls.return_value = mock_orch

            mock_ls = MagicMock()
            mock_ls.__enter__ = MagicMock(return_value=mock_ls)
            mock_ls.__exit__ = MagicMock(return_value=False)
            mock_ls_cls.return_value = mock_ls

            result = runner.invoke(cli, ["run", "--localstack-image", "custom:v1"])

        assert result.exit_code == 0, result.output
        # config.localstack_image must be set to the custom image before scan executes
        assert mock_cfg.localstack_image == "custom:v1"


class TestDiscoverCommand:
    @patch("scanner.discovery.registry.SampleRegistry")
    @patch("scanner.discovery.github_client.GitHubClient")
    def test_discover_uses_discover_all(self, mock_client_cls, mock_registry_cls):
        """discover command calls client.discover_all() (not legacy list_repos)."""
        mock_client = MagicMock()
        mock_client.discover_all.return_value = []
        mock_client_cls.return_value = mock_client

        mock_registry = MagicMock()
        mock_registry.load.return_value = []
        mock_registry_cls.return_value = mock_registry

        runner = CliRunner()
        with patch("scanner.cli.Config") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.max_repos_per_org = 5
            mock_cfg.target_orgs = ["aws-samples"]
            mock_cfg.registry_path = "/tmp/registry.json"
            mock_cfg.cache_ttl_hours = 24
            mock_cfg_cls.return_value = mock_cfg

            result = runner.invoke(cli, ["discover", "--max-repos-per-org", "5"])

        assert result.exit_code == 0
        mock_client.discover_all.assert_called_once()

    @patch("scanner.discovery.registry.SampleRegistry")
    @patch("scanner.discovery.github_client.GitHubClient")
    def test_discover_no_cache_passes_none_cache(self, mock_client_cls, mock_registry_cls):
        """--no-cache flag passes cache=None to discover_all, bypassing the TTL cache."""
        mock_client = MagicMock()
        mock_client.discover_all.return_value = []
        mock_client_cls.return_value = mock_client

        mock_registry = MagicMock()
        mock_registry.load.return_value = []
        mock_registry_cls.return_value = mock_registry

        runner = CliRunner()
        with patch("scanner.cli.Config") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.target_orgs = ["aws-samples"]
            mock_cfg.registry_path = "/tmp/registry.json"
            mock_cfg.cache_ttl_hours = 24
            mock_cfg_cls.return_value = mock_cfg

            result = runner.invoke(cli, ["discover", "--no-cache"])

        assert result.exit_code == 0
        _, kwargs = mock_client.discover_all.call_args
        assert kwargs.get("cache") is None

    def test_discover_help_shows_no_cache_flag(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["discover", "--help"])
        assert result.exit_code == 0
        assert "--no-cache" in result.output


class TestReportCommand:
    def test_report_fails_gracefully_on_missing_input(self, tmp_path):
        """report command should fail if input file is missing."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["report", "--input", str(tmp_path / "missing.json"), "--output", str(tmp_path / "out")],
        )
        assert result.exit_code != 0
