"""LocalStack container lifecycle manager."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any

import docker
import requests

from scanner.config import Config

logger = logging.getLogger(__name__)

_LS_LOG_MAX_BYTES = 50 * 1024  # 50 KB


def _truncate_logs(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= _LS_LOG_MAX_BYTES:
        return text
    return encoded[:_LS_LOG_MAX_BYTES].decode("utf-8", errors="replace") + "\n... [truncated]"


class LocalStackManager:
    """Manages LocalStack container lifecycle.

    In external mode (CI), skips start/stop and only does reset + health check.
    """

    def __init__(self, config: Config, external: bool = False) -> None:
        self._config = config
        self._external = external
        self._client: Any = docker.from_env()
        self._container: Any = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the LocalStack container (no-op in external mode)."""
        if self._external:
            return
        logger.info("Pulling %s...", self._config.localstack_image)
        self._client.images.pull(self._config.localstack_image)

        env = {"DEBUG": "0"}
        auth_token = os.environ.get("LOCALSTACK_AUTH_TOKEN")
        if auth_token:
            env["LOCALSTACK_AUTH_TOKEN"] = auth_token

        logger.info("Starting LocalStack container...")
        self._container = self._client.containers.run(
            self._config.localstack_image,
            detach=True,
            ports={"4566/tcp": 4566},
            name=self._config.localstack_container_name,
            environment=env,
            auto_remove=False,
        )
        self.wait_until_ready(timeout=self._config.localstack_ready_timeout)

    def stop(self) -> None:
        """Stop and remove the LocalStack container (no-op in external mode)."""
        if self._external:
            return
        if self._container is not None:
            try:
                self._container.stop(timeout=10)
                self._container.remove(force=True)
            except Exception as exc:
                logger.warning("Error stopping container: %s", exc)
            finally:
                self._container = None

    def reset(self) -> None:
        """Reset LocalStack state via API. Falls back to container restart on failure."""
        try:
            response = requests.post(
                f"{self._config.localstack_endpoint}/_localstack/state/reset",
                timeout=10,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Reset returned HTTP {response.status_code}")
            logger.debug("LocalStack state reset via API")
            # Verify health after reset
            ok = self.wait_until_ready(timeout=self._config.localstack_reset_timeout)
            if not ok:
                raise RuntimeError("Health check failed after API reset")
        except Exception as exc:
            logger.warning("API reset failed (%s), falling back to container restart", exc)
            self.stop()
            self.start()

    def wait_until_ready(self, timeout: int | None = None) -> bool:
        """Poll health endpoint until ready or timeout. Returns True on success."""
        deadline = time.time() + (timeout or self._config.localstack_ready_timeout)
        url = f"{self._config.localstack_endpoint}/_localstack/health"
        while time.time() < deadline:
            try:
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    return True
            except Exception as exc:
                logger.debug("Health check attempt failed: %s", exc)
            time.sleep(2)
        logger.warning("LocalStack not ready within %ds", timeout)
        return False

    def is_running(self) -> bool:
        """Return True if the container is currently running."""
        return self._container is not None

    def get_logs(self) -> str:
        """Return recent container logs."""
        if self._container is None:
            return ""
        try:
            return self._container.logs(tail=200).decode("utf-8", errors="replace")
        except Exception:
            return ""

    def get_recent_logs(self, since_reset: float) -> str:
        """Return LocalStack logs captured since *since_reset* (Unix timestamp).

        Self-managed mode: reads from the Docker container API.
        External mode: fetches /_localstack/diagnose via HTTP, falls back to
        ``docker logs`` subprocess. Returns an empty string if all sources fail.
        Truncates output to 50 KB.
        """
        raw = self._fetch_recent_logs(since_reset)
        return _truncate_logs(raw)

    def _fetch_recent_logs(self, since_reset: float) -> str:
        if self._container is not None:
            try:
                return self._container.logs(since=since_reset).decode("utf-8", errors="replace")
            except Exception as exc:
                logger.debug("Container log fetch failed: %s", exc)
                return ""
        # External mode: HTTP first, subprocess fallback
        try:
            resp = requests.get(
                f"{self._config.localstack_endpoint}/_localstack/diagnose",
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.text
        except Exception as exc:
            logger.debug("HTTP log fetch failed: %s", exc)
        try:
            result = subprocess.run(
                ["docker", "logs", self._config.localstack_container_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.stdout + result.stderr
        except Exception as exc:
            logger.debug("Subprocess log fetch failed: %s", exc)
        return ""

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> LocalStackManager:
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()
