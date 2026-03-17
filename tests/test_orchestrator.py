"""Tests for ScanOrchestrator and Sandbox."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from scanner.config import CloudProvider, Config, IaCType
from scanner.models import DeployResult, DeployStatus, Sample


def _make_sample(iac_type: IaCType = IaCType.CLOUDFORMATION, name: str = "test-repo") -> Sample:
    return Sample(
        name=name,
        org="aws-samples",
        url=f"https://github.com/aws-samples/{name}",
        iac_type=iac_type,
        cloud_provider=CloudProvider.AWS,
        description="Test",
        topics=[],
        language="Python",
        default_branch="main",
        updated_at=datetime.now(),
    )


def _make_result(status: DeployStatus = DeployStatus.SUCCESS) -> DeployResult:
    return DeployResult(
        sample_name="test-repo",
        org="aws-samples",
        status=status,
        duration=1.0,
        stdout="ok",
        stderr="",
        error_message=None,
        services_used=[],
        deployer_command="",
    )


def _make_orchestrator(sandbox: MagicMock | None = None):
    from scanner.runner.orchestrator import ScanOrchestrator

    sb = sandbox if sandbox is not None else MagicMock()
    orch = ScanOrchestrator(Config(), sandbox=sb)
    return orch, sb


# ---------------------------------------------------------------------------
# ScanOrchestrator tests
# ---------------------------------------------------------------------------


class TestScanOrchestrator:
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_resets_state_for_each_sample(self, mock_get_deployer, mock_sleep, _):
        samples = [_make_sample(), _make_sample(name="repo2")]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        assert ls_manager.reset.call_count == 2

    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_returns_scan_report(self, mock_get_deployer, mock_sleep, _):
        from scanner.models import ScanReport

        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        assert isinstance(report, ScanReport)
        assert len(report.results) == 1

    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_bootstraps_before_cdk_sample(self, mock_get_deployer, mock_sleep, _):
        samples = [_make_sample(iac_type=IaCType.CDK)]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.bootstrap.return_value = True
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        mock_deployer.bootstrap.assert_called_once()

    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_skips_cdk_sample_if_bootstrap_fails(self, mock_get_deployer, mock_sleep, _):
        samples = [_make_sample(iac_type=IaCType.CDK)]
        ls_manager = MagicMock()
        mock_deployer = MagicMock()
        mock_deployer.bootstrap.return_value = False
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator()
        report = orch.run(samples, ls_manager)

        assert report.results[0].status == DeployStatus.SKIPPED

    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_records_failure_if_prepare_fails(self, mock_get_deployer, mock_sleep, _):
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = False
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        assert report.results[0].status == DeployStatus.FAILURE

    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_calls_cleanup_after_deploy(self, mock_get_deployer, mock_sleep, _):
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        mock_deployer.cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# Sandbox tests
# ---------------------------------------------------------------------------


class TestSandbox:
    @patch("scanner.runner.sandbox.subprocess.run")
    @patch("scanner.runner.sandbox.tempfile.mkdtemp")
    def test_clone_sample_calls_git_clone(self, mock_mkdtemp, mock_run, tmp_path):
        from scanner.runner.sandbox import Sandbox

        mock_mkdtemp.return_value = str(tmp_path)
        mock_run.return_value = MagicMock(returncode=0)
        sandbox = Sandbox()
        sample = _make_sample()
        sandbox.clone_sample(sample)
        cmd = mock_run.call_args[0][0]
        assert "git" in cmd
        assert "clone" in cmd
        assert "--depth" in cmd
        assert sample.url in cmd

    @patch("scanner.runner.sandbox.shutil.rmtree")
    def test_cleanup_removes_directory(self, mock_rmtree, tmp_path):
        from scanner.runner.sandbox import Sandbox

        sandbox = Sandbox()
        sandbox.cleanup(tmp_path)
        mock_rmtree.assert_called_once_with(tmp_path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Data retention pruning
# ---------------------------------------------------------------------------


class TestPruneOldResults:
    def test_prune_keeps_most_recent(self, tmp_path):
        from scanner.runner.orchestrator import _prune_old_results

        for i in range(5):
            f = tmp_path / f"2026-0{i + 1}-01.json"
            f.write_text("{}")
            os.utime(f, (i * 1000, i * 1000))

        _prune_old_results(tmp_path, keep=3)
        assert len(list(tmp_path.glob("*.json"))) == 3

    def test_prune_does_nothing_when_under_limit(self, tmp_path):
        from scanner.runner.orchestrator import _prune_old_results

        (tmp_path / "2026-01-01.json").write_text("{}")
        _prune_old_results(tmp_path, keep=12)
        assert len(list(tmp_path.glob("*.json"))) == 1
