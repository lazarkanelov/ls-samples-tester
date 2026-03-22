"""Tests for TerraformDeployer."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


class TestTerraformDeployer:
    def setup_method(self):
        from scanner.deployer.terraform import TerraformDeployer

        self.deployer = TerraformDeployer()

    def _mock_run(self, returncode=0, stdout="ok", stderr=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_prepare_runs_tflocal_init(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0)
        result = self.deployer.prepare(tmp_path)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "tflocal" in cmd
        assert "init" in cmd

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_prepare_returns_false_on_init_failure(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(1, "", "Error: init failed")
        result = self.deployer.prepare(tmp_path)
        assert result is False

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_deploy_runs_tflocal_apply(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0, "Apply complete!")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.SUCCESS
        cmd = mock_run.call_args[0][0]
        assert "tflocal" in cmd
        assert "apply" in cmd
        assert "-auto-approve" in cmd

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_deploy_returns_failure_on_nonzero_exit(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(1, "", "Error: apply failed")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.FAILURE
        assert result.error_message is not None

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_deploy_returns_timeout_on_subprocess_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tflocal", timeout=1)
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=1)
        assert result.status == DeployStatus.TIMEOUT

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_deploy_uses_stdout_when_stderr_empty(self, mock_run, tmp_path):
        """Terraform writes errors to stdout — should use it when stderr is empty."""
        from scanner.models import DeployStatus

        mock_run.return_value = self._mock_run(
            1, "Error: resource quota exceeded\nApply failed", ""
        )
        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.FAILURE
        assert "resource quota exceeded" in result.error_message

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_deploy_prefers_stderr_over_stdout_when_both_present(self, mock_run, tmp_path):
        """When both stderr and stdout have content, use stderr."""
        mock_run.return_value = self._mock_run(
            1, "Some stdout content", "Error: actual error in stderr"
        )
        result = self.deployer.deploy(tmp_path, timeout=60)
        assert "actual error in stderr" in result.error_message

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_deploy_fallback_message_when_both_empty(self, mock_run, tmp_path):
        """When both stderr and stdout are empty, use fallback message."""
        mock_run.return_value = self._mock_run(1, "", "")
        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.error_message == "Non-zero exit code"

    @patch("scanner.deployer.terraform.subprocess.run")
    def test_cleanup_runs_tflocal_destroy(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0)
        self.deployer.cleanup(tmp_path)
        cmd = mock_run.call_args[0][0]
        assert "tflocal" in cmd
        assert "destroy" in cmd
        assert "-auto-approve" in cmd
