"""Tests for SamDeployer."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


class TestSamDeployer:
    def setup_method(self):
        from scanner.deployer.sam import SamDeployer

        self.deployer = SamDeployer()

    def _mock_run(self, returncode=0, stdout="ok", stderr=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    @patch("scanner.deployer.sam.subprocess.run")
    def test_prepare_runs_samlocal_build_no_container(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0)
        result = self.deployer.prepare(tmp_path)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "samlocal" in cmd
        assert "build" in cmd
        assert "--no-use-container" in cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_prepare_retries_with_container_on_failure(self, mock_run, tmp_path):
        mock_run.side_effect = [self._mock_run(1, "", "Error"), self._mock_run(0)]
        result = self.deployer.prepare(tmp_path)
        assert result is True
        assert mock_run.call_count == 2
        second_cmd = mock_run.call_args_list[1][0][0]
        assert "samlocal" in second_cmd
        assert "--no-use-container" not in second_cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_prepare_returns_false_when_both_builds_fail(self, mock_run, tmp_path):
        mock_run.side_effect = [self._mock_run(1, "", "Err1"), self._mock_run(1, "", "Err2")]
        result = self.deployer.prepare(tmp_path)
        assert result is False

    @patch("scanner.deployer.sam.subprocess.run")
    def test_deploy_runs_samlocal_deploy(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0, "Successfully deployed")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.SUCCESS
        cmd = mock_run.call_args[0][0]
        assert "samlocal" in cmd
        assert "deploy" in cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_deploy_includes_stack_name(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0)
        self.deployer.deploy(tmp_path, timeout=60)
        cmd = mock_run.call_args[0][0]
        assert "--stack-name" in cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_deploy_returns_failure_on_nonzero_exit(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(1, "", "Deploy failed")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.FAILURE
        assert result.error_message is not None

    @patch("scanner.deployer.sam.subprocess.run")
    def test_deploy_returns_timeout_on_subprocess_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="samlocal", timeout=1)
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=1)
        assert result.status == DeployStatus.TIMEOUT

    @patch("scanner.deployer.sam.subprocess.run")
    def test_cleanup_runs_awslocal_delete_stack(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0)
        self.deployer.cleanup(tmp_path)
        cmd = mock_run.call_args[0][0]
        assert "awslocal" in cmd
        assert "delete-stack" in cmd
