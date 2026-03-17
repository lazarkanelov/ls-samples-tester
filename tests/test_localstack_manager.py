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
