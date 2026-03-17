"""Tests for CdkDeployer."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestCdkDeployer:
    def setup_method(self):
        from scanner.deployer.cdk import CdkDeployer
        self.deployer = CdkDeployer()

    def _mock_run(self, returncode=0, stdout="ok", stderr=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_bootstrap_runs_cdklocal_bootstrap(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0, "CDKToolkit bootstrap complete")
        result = self.deployer.bootstrap(timeout=60)
        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "cdklocal" in cmd
        assert "bootstrap" in cmd

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_bootstrap_returns_false_on_failure(self, mock_run):
        mock_run.return_value = self._mock_run(1, "", "Error")
        result = self.deployer.bootstrap(timeout=60)
        assert result is False

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_prepare_runs_npm_install_for_ts_project(self, mock_run, tmp_path):
        (tmp_path / "package.json").write_text('{"name":"test"}')
        mock_run.return_value = self._mock_run(0)
        result = self.deployer.prepare(tmp_path)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "npm" in cmd
        assert "install" in cmd

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_prepare_runs_pip_install_for_python_project(self, mock_run, tmp_path):
        (tmp_path / "requirements.txt").write_text("boto3\n")
        mock_run.return_value = self._mock_run(0)
        result = self.deployer.prepare(tmp_path)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "pip" in cmd

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_prepare_returns_true_when_no_deps_file(self, mock_run, tmp_path):
        result = self.deployer.prepare(tmp_path)
        assert result is True
        mock_run.assert_not_called()

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_deploy_runs_cdklocal_deploy(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0, "✅ deployed")
        from scanner.models import DeployStatus
        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.SUCCESS
        cmd = mock_run.call_args[0][0]
        assert "cdklocal" in cmd
        assert "deploy" in cmd

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_deploy_returns_failure_on_nonzero_exit(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(1, "", "Error: resource not found")
        from scanner.models import DeployStatus
        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.FAILURE
        assert result.error_message is not None

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_deploy_captures_stdout_stderr(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0, "stdout output", "stderr output")
        result = self.deployer.deploy(tmp_path, timeout=60)
        assert "stdout output" in result.stdout
        assert "stderr output" in result.stderr

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_cleanup_runs_cdklocal_destroy(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0)
        self.deployer.cleanup(tmp_path)
        cmd = mock_run.call_args[0][0]
        assert "cdklocal" in cmd
        assert "destroy" in cmd

    @patch("scanner.deployer.cdk.subprocess.run")
    def test_deploy_returns_timeout_on_subprocess_timeout(self, mock_run, tmp_path):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="cdklocal", timeout=1)
        from scanner.models import DeployStatus
        result = self.deployer.deploy(tmp_path, timeout=1)
        assert result.status == DeployStatus.TIMEOUT
