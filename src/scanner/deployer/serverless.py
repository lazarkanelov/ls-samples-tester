"""Serverless Framework deployer with serverless-localstack plugin injection."""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from scanner.deployer.base import Deployer
from scanner.models import DeployResult, DeployStatus

logger = logging.getLogger(__name__)

_PLUGIN_NAME = "serverless-localstack"
_SLS_CONFIG_FILES = ["serverless.yml", "serverless.yaml"]


def _inject_plugin(config_path: Path) -> None:
    """Ensure serverless-localstack plugin and custom.localstack config are present."""
    try:
        from ruamel.yaml import YAML

        yaml = YAML()
        yaml.preserve_quotes = True
        with config_path.open("r") as fh:
            data = yaml.load(fh)
        if data is None:
            data = {}

        # Inject plugin if not already present
        plugins = data.get("plugins", [])
        if _PLUGIN_NAME not in plugins:
            plugins.append(_PLUGIN_NAME)
            data["plugins"] = plugins

        # Inject custom.localstack.stages config if missing
        custom = data.setdefault("custom", {})
        if "localstack" not in custom:
            custom["localstack"] = {"stages": ["local"]}

        with config_path.open("w") as fh:
            yaml.dump(data, fh)
    except Exception as exc:
        logger.warning("Failed to inject serverless-localstack plugin: %s", exc)


class ServerlessDeployer(Deployer):
    """Deploys Serverless Framework samples via serverless-localstack."""

    def prepare(self, sample_dir: Path) -> bool:
        # Install npm deps
        result = subprocess.run(
            ["npm", "install"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            timeout=180,
        )
        if result.returncode != 0:
            logger.warning("npm install failed: %s", result.stderr)
            return False

        # Inject plugin into serverless config
        for name in _SLS_CONFIG_FILES:
            config_path = sample_dir / name
            if config_path.exists():
                _inject_plugin(config_path)
                break

        return True

    def deploy(self, sample_dir: Path, timeout: int) -> DeployResult:
        start = time.monotonic()
        try:
            result = subprocess.run(
                ["npx", "serverless", "deploy", "--stage", "local"],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return DeployResult(
                sample_name=sample_dir.name,
                org="",
                status=DeployStatus.TIMEOUT,
                duration=time.monotonic() - start,
                stdout="",
                stderr="",
                error_message=f"Deploy timed out after {timeout}s",
                services_used=[],
                deployer_command="serverless deploy",
            )
        duration = time.monotonic() - start
        if result.returncode != 0:
            return DeployResult(
                sample_name=sample_dir.name,
                org="",
                status=DeployStatus.FAILURE,
                duration=duration,
                stdout=result.stdout,
                stderr=result.stderr,
                error_message=result.stderr or "Non-zero exit code",
                services_used=[],
                deployer_command="serverless deploy",
            )
        return DeployResult(
            sample_name=sample_dir.name,
            org="",
            status=DeployStatus.SUCCESS,
            duration=duration,
            stdout=result.stdout,
            stderr=result.stderr,
            error_message=None,
            services_used=[],
            deployer_command="serverless deploy",
        )

    def cleanup(self, sample_dir: Path) -> None:
        subprocess.run(
            ["npx", "serverless", "remove", "--stage", "local"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            timeout=180,
        )
