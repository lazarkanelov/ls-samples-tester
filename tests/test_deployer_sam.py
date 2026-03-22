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
        # 3 calls: bucket create, no-container build (fails), container build (succeeds)
        mock_run.side_effect = [
            self._mock_run(0),           # awslocal s3 mb
            self._mock_run(1, "", "Error"),  # samlocal build --no-use-container
            self._mock_run(0),           # samlocal build (container)
        ]
        result = self.deployer.prepare(tmp_path)
        assert result is True
        assert mock_run.call_count == 3
        third_cmd = mock_run.call_args_list[2][0][0]
        assert "samlocal" in third_cmd
        assert "--no-use-container" not in third_cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_prepare_returns_false_when_both_builds_fail(self, mock_run, tmp_path):
        # 3 calls: bucket create, no-container build (fails), container build (fails)
        mock_run.side_effect = [
            self._mock_run(0),           # awslocal s3 mb
            self._mock_run(1, "", "Err1"),  # samlocal build --no-use-container
            self._mock_run(1, "", "Err2"),  # samlocal build (container)
        ]
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

    @patch("scanner.deployer.sam.subprocess.run")
    def test_deploy_includes_region_flag(self, mock_run, tmp_path):
        """SAM deploy must include --region to avoid region resolution errors."""
        mock_run.return_value = self._mock_run(0)
        self.deployer.deploy(tmp_path, timeout=60)
        cmd = mock_run.call_args[0][0]
        assert "--region" in cmd
        assert "us-east-1" in cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_deploy_does_not_use_resolve_s3(self, mock_run, tmp_path):
        """--resolve-s3 must not appear in the deploy command."""
        mock_run.return_value = self._mock_run(0)
        self.deployer.deploy(tmp_path, timeout=60)
        cmd = mock_run.call_args[0][0]
        assert "--resolve-s3" not in cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_deploy_uses_s3_bucket_when_no_samconfig(self, mock_run, tmp_path):
        """Without samconfig.toml, deploy must pass --s3-bucket."""
        mock_run.return_value = self._mock_run(0)
        self.deployer.deploy(tmp_path, timeout=60)
        cmd = mock_run.call_args[0][0]
        assert "--s3-bucket" in cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_deploy_omits_s3_bucket_when_samconfig_has_s3_bucket(self, mock_run, tmp_path):
        """When samconfig.toml already specifies s3_bucket, do not pass --s3-bucket CLI flag."""
        (tmp_path / "samconfig.toml").write_text(
            "[default.deploy.parameters]\ns3_bucket = \"my-existing-bucket\"\n"
        )
        mock_run.return_value = self._mock_run(0)
        self.deployer.deploy(tmp_path, timeout=60)
        cmd = mock_run.call_args[0][0]
        assert "--s3-bucket" not in cmd

    @patch("scanner.deployer.sam.subprocess.run")
    def test_prepare_creates_s3_bucket(self, mock_run, tmp_path):
        """prepare() must create the S3 deployment bucket via awslocal."""
        mock_run.return_value = self._mock_run(0)
        self.deployer.prepare(tmp_path)
        all_cmds = [call[0][0] for call in mock_run.call_args_list]
        bucket_create_cmds = [cmd for cmd in all_cmds if "awslocal" in cmd and "mb" in cmd]
        assert len(bucket_create_cmds) > 0

    def test_samconfig_s3_bucket_strips_inline_comments(self, tmp_path):
        """Bucket name must not include TOML inline comments."""
        from scanner.deployer.sam import _samconfig_s3_bucket
        (tmp_path / "samconfig.toml").write_text(
            "[default.deploy.parameters]\ns3_bucket = my-bucket # deployed manually\n"
        )
        result = _samconfig_s3_bucket(tmp_path)
        assert result == "my-bucket"

    def test_samconfig_s3_bucket_strips_inline_comments_with_quotes(self, tmp_path):
        """Quoted bucket name with trailing comment must parse correctly."""
        from scanner.deployer.sam import _samconfig_s3_bucket
        (tmp_path / "samconfig.toml").write_text(
            '[default.deploy.parameters]\ns3_bucket = "my-bucket" # comment\n'
        )
        result = _samconfig_s3_bucket(tmp_path)
        assert result == "my-bucket"
