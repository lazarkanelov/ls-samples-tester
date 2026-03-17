"""Tests for CloudFormationDeployer."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


class TestCloudFormationDeployer:
    def setup_method(self):
        from scanner.deployer.cloudformation import CloudFormationDeployer

        self.deployer = CloudFormationDeployer()

    def _mock_run(self, returncode=0, stdout="ok", stderr=""):
        result = MagicMock()
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_prepare_validates_template_json(self, mock_run, tmp_path):
        (tmp_path / "template.json").write_text('{"AWSTemplateFormatVersion": "2010-09-09"}')
        mock_run.return_value = self._mock_run(0)
        result = self.deployer.prepare(tmp_path)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "awslocal" in cmd
        assert "validate-template" in cmd

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_prepare_validates_template_yaml(self, mock_run, tmp_path):
        (tmp_path / "template.yaml").write_text("AWSTemplateFormatVersion: '2010-09-09'\n")
        mock_run.return_value = self._mock_run(0)
        result = self.deployer.prepare(tmp_path)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "validate-template" in cmd

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_prepare_returns_true_when_no_template(self, mock_run, tmp_path):
        result = self.deployer.prepare(tmp_path)
        assert result is True
        mock_run.assert_not_called()

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_deploy_runs_awslocal_cloudformation_deploy(self, mock_run, tmp_path):
        (tmp_path / "template.yaml").write_text("AWSTemplateFormatVersion: '2010-09-09'\n")
        mock_run.return_value = self._mock_run(0, "Successfully deployed")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.SUCCESS
        cmd = mock_run.call_args[0][0]
        assert "awslocal" in cmd
        assert "deploy" in cmd

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_deploy_includes_stack_name(self, mock_run, tmp_path):
        (tmp_path / "template.yaml").write_text("AWSTemplateFormatVersion: '2010-09-09'\n")
        mock_run.return_value = self._mock_run(0)
        self.deployer.deploy(tmp_path, timeout=60)
        cmd = mock_run.call_args[0][0]
        assert "--stack-name" in cmd

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_deploy_returns_unsupported_when_no_template(self, mock_run, tmp_path):
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.UNSUPPORTED
        mock_run.assert_not_called()

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_deploy_returns_failure_on_nonzero_exit(self, mock_run, tmp_path):
        (tmp_path / "template.yaml").write_text("AWSTemplateFormatVersion: '2010-09-09'\n")
        mock_run.return_value = self._mock_run(1, "", "Deploy failed")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.FAILURE

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_deploy_returns_timeout_on_subprocess_timeout(self, mock_run, tmp_path):
        (tmp_path / "template.yaml").write_text("AWSTemplateFormatVersion: '2010-09-09'\n")
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="awslocal", timeout=1)
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=1)
        assert result.status == DeployStatus.TIMEOUT

    @patch("scanner.deployer.cloudformation.subprocess.run")
    def test_cleanup_runs_awslocal_delete_stack(self, mock_run, tmp_path):
        mock_run.return_value = self._mock_run(0)
        self.deployer.cleanup(tmp_path)
        cmd = mock_run.call_args[0][0]
        assert "awslocal" in cmd
        assert "delete-stack" in cmd
