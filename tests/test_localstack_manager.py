"""Tests for LocalStack container manager."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from scanner.config import Config


class TestLocalStackManager:
    def setup_method(self):
        from scanner.runner.localstack import LocalStackManager
        self.config = Config()
        self.LocalStackManager = LocalStackManager

    @patch("scanner.runner.localstack.docker")
    def test_start_pulls_and_runs_container(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_client.containers.list.return_value = []

        manager = self.LocalStackManager(config=self.config)
        with patch.object(manager, "wait_until_ready", return_value=True):
            manager.start()

        mock_client.images.pull.assert_called_once_with(self.config.localstack_image)
        assert mock_client.containers.run.call_args[0][0] == self.config.localstack_image

    @patch("scanner.runner.localstack.docker")
    def test_stop_removes_container(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_client.containers.list.return_value = [mock_container]
        mock_container.name = self.config.localstack_container_name

        manager = self.LocalStackManager(config=self.config)
        manager._container = mock_container
        manager.stop()

        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()

    @patch("scanner.runner.localstack.requests")
    @patch("scanner.runner.localstack.docker")
    def test_reset_calls_state_reset_api(self, mock_docker, mock_requests):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        # State reset succeeds
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_requests.post.return_value = mock_response

        manager = self.LocalStackManager(config=self.config)
        with patch.object(manager, "wait_until_ready", return_value=True):
            manager.reset()

        mock_requests.post.assert_called_once_with(
            f"{self.config.localstack_endpoint}/_localstack/state/reset",
            timeout=10,
        )

    @patch("scanner.runner.localstack.requests")
    @patch("scanner.runner.localstack.docker")
    def test_reset_falls_back_to_container_restart_on_failure(self, mock_docker, mock_requests):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()

        # State reset fails
        mock_requests.post.side_effect = Exception("connection refused")

        manager = self.LocalStackManager(config=self.config)
        manager._container = mock_container

        with patch.object(manager, "stop") as mock_stop, \
             patch.object(manager, "start") as mock_start:
            manager.reset()
            mock_stop.assert_called_once()
            mock_start.assert_called_once()

    @patch("scanner.runner.localstack.requests")
    @patch("scanner.runner.localstack.docker")
    def test_wait_until_ready_polls_health_endpoint(self, mock_docker, mock_requests):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        ok_response = MagicMock()
        ok_response.status_code = 200

        mock_requests.get.return_value = ok_response

        manager = self.LocalStackManager(config=self.config)
        result = manager.wait_until_ready(timeout=5)

        assert result is True
        mock_requests.get.assert_called_with(
            f"{self.config.localstack_endpoint}/_localstack/health",
            timeout=5,
        )

    @patch("scanner.runner.localstack.docker")
    def test_external_mode_skips_docker_operations(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        manager = self.LocalStackManager(config=self.config, external=True)
        manager.start()  # should be no-op
        manager.stop()   # should be no-op

        mock_client.images.pull.assert_not_called()
        mock_client.containers.run.assert_not_called()

    @patch("scanner.runner.localstack.docker")
    def test_is_running_returns_false_when_no_container(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        manager = self.LocalStackManager(config=self.config)
        assert manager.is_running() is False

    @patch("scanner.runner.localstack.docker")
    def test_context_manager_stops_on_exit(self, mock_docker):
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        manager = self.LocalStackManager(config=self.config)
        with patch.object(manager, "start"), patch.object(manager, "stop") as mock_stop:
            with manager:
                pass
            mock_stop.assert_called_once()

    @patch("scanner.runner.localstack.docker")
    def test_start_uses_custom_image_from_config(self, mock_docker):
        """start() pulls and runs the exact image specified in config.localstack_image."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        config = Config(localstack_image="custom/localstack:v3.0")
        manager = self.LocalStackManager(config=config)
        with patch.object(manager, "wait_until_ready", return_value=True):
            manager.start()

        mock_client.images.pull.assert_called_once_with("custom/localstack:v3.0")
        run_call_image = mock_client.containers.run.call_args[0][0]
        assert run_call_image == "custom/localstack:v3.0"

    # ------------------------------------------------------------------
    # get_recent_logs tests
    # ------------------------------------------------------------------

    @patch("scanner.runner.localstack.docker")
    def test_get_recent_logs_uses_docker_api_in_self_managed_mode(self, mock_docker):
        """In self-managed mode, logs come from the Docker container API."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        mock_container.logs.return_value = b"LocalStack log line\n"

        manager = self.LocalStackManager(config=self.config)
        manager._container = mock_container
        result = manager.get_recent_logs(since_reset=0.0)

        assert "LocalStack log line" in result
        mock_container.logs.assert_called_once()

    @patch("scanner.runner.localstack.requests")
    @patch("scanner.runner.localstack.docker")
    def test_get_recent_logs_uses_http_in_external_mode(self, mock_docker, mock_requests):
        """In external mode (no container), logs come from HTTP /_localstack/diagnose."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Service log from diagnose endpoint"
        mock_requests.get.return_value = mock_response

        manager = self.LocalStackManager(config=self.config, external=True)
        # container is None in external mode
        result = manager.get_recent_logs(since_reset=0.0)

        assert "Service log from diagnose endpoint" in result

    @patch("scanner.runner.localstack.subprocess")
    @patch("scanner.runner.localstack.requests")
    @patch("scanner.runner.localstack.docker")
    def test_get_recent_logs_falls_back_to_subprocess_when_http_fails(
        self, mock_docker, mock_requests, mock_subprocess
    ):
        """Falls back to docker logs subprocess when HTTP diagnose fails."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_requests.get.side_effect = Exception("connection refused")

        proc_result = MagicMock()
        proc_result.stdout = "log from docker subprocess\n"
        proc_result.stderr = ""
        mock_subprocess.run.return_value = proc_result

        manager = self.LocalStackManager(config=self.config, external=True)
        result = manager.get_recent_logs(since_reset=0.0)

        assert "log from docker subprocess" in result

    @patch("scanner.runner.localstack.subprocess")
    @patch("scanner.runner.localstack.requests")
    @patch("scanner.runner.localstack.docker")
    def test_get_recent_logs_returns_empty_when_all_sources_fail(
        self, mock_docker, mock_requests, mock_subprocess
    ):
        """Returns empty string when both HTTP and subprocess fail."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_requests.get.side_effect = Exception("refused")
        mock_subprocess.run.side_effect = Exception("docker not found")

        manager = self.LocalStackManager(config=self.config, external=True)
        result = manager.get_recent_logs(since_reset=0.0)

        assert result == ""

    @patch("scanner.runner.localstack.docker")
    def test_get_recent_logs_truncates_to_50kb(self, mock_docker):
        """Logs exceeding 50 KB are truncated."""
        mock_client = MagicMock()
        mock_docker.from_env.return_value = mock_client
        mock_container = MagicMock()
        # Create > 50 KB of log data
        mock_container.logs.return_value = b"x" * (60 * 1024)

        manager = self.LocalStackManager(config=self.config)
        manager._container = mock_container
        result = manager.get_recent_logs(since_reset=0.0)

        assert len(result.encode("utf-8")) <= 50 * 1024 + 100  # allow for truncation marker
