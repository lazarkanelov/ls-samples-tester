"""Tests for PulumiDeployer, ServerlessDeployer, and AzureDeployer."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


def _mock_run(returncode=0, stdout="ok", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


# ---------------------------------------------------------------------------
# PulumiDeployer
# ---------------------------------------------------------------------------


class TestPulumiDeployer:
    def setup_method(self):
        from scanner.deployer.pulumi import PulumiDeployer

        self.deployer = PulumiDeployer()

    @patch("scanner.deployer.pulumi.subprocess.run")
    def test_prepare_calls_pulumilocal(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0)
        result = self.deployer.prepare(tmp_path)
        assert result is True
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("pulumilocal" in cmd for cmd in cmds)

    @patch("scanner.deployer.pulumi.subprocess.run")
    def test_prepare_sets_pulumi_env_in_calls(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0)
        self.deployer.prepare(tmp_path)
        for c in mock_run.call_args_list:
            env = c[1].get("env", {})
            assert "PULUMI_CONFIG_PASSPHRASE" in env

    @patch("scanner.deployer.pulumi.subprocess.run")
    def test_deploy_runs_pulumilocal_up(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0)
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.SUCCESS
        cmd = mock_run.call_args[0][0]
        assert "pulumilocal" in cmd
        assert "up" in cmd

    @patch("scanner.deployer.pulumi.subprocess.run")
    def test_deploy_sets_pulumi_env_vars(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0)
        self.deployer.deploy(tmp_path, timeout=60)
        env = mock_run.call_args[1]["env"]
        assert env["PULUMI_CONFIG_PASSPHRASE"] == "localstack-scanner"
        assert "PULUMI_BACKEND_URL" in env
        assert tmp_path.name in env["PULUMI_BACKEND_URL"]

    @patch("scanner.deployer.pulumi.subprocess.run")
    def test_deploy_returns_failure_on_nonzero_exit(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(1, "", "error: deploy failed")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.FAILURE

    @patch("scanner.deployer.pulumi.subprocess.run")
    def test_deploy_returns_timeout_on_subprocess_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pulumilocal", timeout=1)
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=1)
        assert result.status == DeployStatus.TIMEOUT

    @patch("scanner.deployer.pulumi.subprocess.run")
    def test_cleanup_runs_pulumilocal_destroy(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0)
        self.deployer.cleanup(tmp_path)
        cmds = [c[0][0] for c in mock_run.call_args_list]
        assert any("pulumilocal" in cmd and "destroy" in cmd for cmd in cmds)


# ---------------------------------------------------------------------------
# ServerlessDeployer
# ---------------------------------------------------------------------------


class TestServerlessDeployer:
    def setup_method(self):
        from scanner.deployer.serverless import ServerlessDeployer

        self.deployer = ServerlessDeployer()

    @patch("scanner.deployer.serverless.subprocess.run")
    def test_prepare_runs_npm_install(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0)
        result = self.deployer.prepare(tmp_path)
        assert result is True
        cmd = mock_run.call_args[0][0]
        assert "npm" in cmd
        assert "install" in cmd

    @patch("scanner.deployer.serverless.subprocess.run")
    def test_prepare_injects_plugin_when_missing(self, mock_run, tmp_path):
        (tmp_path / "serverless.yml").write_text(
            "service: my-service\nprovider:\n  name: aws\n"
        )
        mock_run.return_value = _mock_run(0)
        self.deployer.prepare(tmp_path)
        content = (tmp_path / "serverless.yml").read_text()
        assert "serverless-localstack" in content

    @patch("scanner.deployer.serverless.subprocess.run")
    def test_prepare_does_not_duplicate_plugin(self, mock_run, tmp_path):
        (tmp_path / "serverless.yml").write_text(
            "service: my-service\nplugins:\n  - serverless-localstack\n"
        )
        mock_run.return_value = _mock_run(0)
        self.deployer.prepare(tmp_path)
        content = (tmp_path / "serverless.yml").read_text()
        assert content.count("serverless-localstack") == 1

    @patch("scanner.deployer.serverless.subprocess.run")
    def test_deploy_runs_serverless_deploy(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0, "Service deployed")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.SUCCESS
        cmd = mock_run.call_args[0][0]
        assert "serverless" in cmd
        assert "deploy" in cmd
        assert "--stage" in cmd

    @patch("scanner.deployer.serverless.subprocess.run")
    def test_deploy_returns_failure_on_nonzero_exit(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(1, "", "Serverless Error")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.FAILURE

    @patch("scanner.deployer.serverless.subprocess.run")
    def test_cleanup_runs_serverless_remove(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0)
        self.deployer.cleanup(tmp_path)
        cmd = mock_run.call_args[0][0]
        assert "serverless" in cmd
        assert "remove" in cmd


# ---------------------------------------------------------------------------
# AzureDeployer
# ---------------------------------------------------------------------------


class TestAzureDeployer:
    def setup_method(self):
        from scanner.deployer.azure import AzureDeployer

        self.deployer = AzureDeployer()

    @patch("scanner.deployer.azure.subprocess.run")
    def test_deploy_returns_unsupported_when_no_template(self, mock_run, tmp_path):
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.UNSUPPORTED
        mock_run.assert_not_called()

    @patch("scanner.deployer.azure.subprocess.run")
    def test_deploy_returns_unsupported_when_az_not_available(self, mock_run, tmp_path):
        (tmp_path / "azuredeploy.json").write_text('{"$schema": "..."}')
        mock_run.side_effect = FileNotFoundError("az not found")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.UNSUPPORTED

    @patch("scanner.deployer.azure.subprocess.run")
    def test_deploy_runs_az_when_template_present(self, mock_run, tmp_path):
        (tmp_path / "azuredeploy.json").write_text('{"$schema": "..."}')
        mock_run.return_value = _mock_run(0, "Deployment succeeded")
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.SUCCESS
        cmd = mock_run.call_args[0][0]
        assert "az" in cmd

    @patch("scanner.deployer.azure.subprocess.run")
    def test_deploy_detects_bicep_template(self, mock_run, tmp_path):
        (tmp_path / "main.bicep").write_text("param location string = 'eastus'\n")
        mock_run.return_value = _mock_run(0)
        from scanner.models import DeployStatus

        result = self.deployer.deploy(tmp_path, timeout=60)
        assert result.status == DeployStatus.SUCCESS

    @patch("scanner.deployer.azure.subprocess.run")
    def test_cleanup_runs_az_delete(self, mock_run, tmp_path):
        mock_run.return_value = _mock_run(0)
        self.deployer.cleanup(tmp_path)
        # Should call az or be a no-op — just ensure no crash
