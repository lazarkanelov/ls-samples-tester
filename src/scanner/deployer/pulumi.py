"""Pulumi deployer using pulumilocal."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from scanner.deployer.base import Deployer
from scanner.models import DeployResult, DeployStatus

logger = logging.getLogger(__name__)

_PASSPHRASE = "localstack-scanner"


def _pulumi_env(sample_dir: Path) -> dict[str, str]:
    """Build env dict with required Pulumi vars for local backend."""
    env = os.environ.copy()
    env["PULUMI_CONFIG_PASSPHRASE"] = _PASSPHRASE
    env["PULUMI_BACKEND_URL"] = f"file:///tmp/pulumi-{sample_dir.name}/"
    return env


def _stack_name(sample_dir: Path) -> str:
    return f"{sample_dir.name}-scan"


class PulumiDeployer(Deployer):
    """Deploys Pulumi samples via pulumilocal."""

    def prepare(self, sample_dir: Path) -> bool:
        env = _pulumi_env(sample_dir)
        # Initialise local backend
        r = subprocess.run(
            ["pulumilocal", "login", "--local"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            env=env,
            timeout=60,
        )
        if r.returncode != 0:
            logger.warning("pulumilocal login failed: %s", r.stderr)
            return False
        # Create per-sample stack (ignore error if it already exists)
        subprocess.run(
            ["pulumilocal", "stack", "init", _stack_name(sample_dir), "--non-interactive"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            env=env,
            timeout=60,
        )
        # Install language deps
        if (sample_dir / "package.json").exists():
            r = subprocess.run(
                ["npm", "install"],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                env=env,
                timeout=180,
            )
            return r.returncode == 0
        if (sample_dir / "requirements.txt").exists():
            r = subprocess.run(
                ["pip", "install", "-r", "requirements.txt"],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                env=env,
                timeout=180,
            )
            return r.returncode == 0
        return True

    def deploy(self, sample_dir: Path, timeout: int) -> DeployResult:
        start = time.monotonic()
        env = _pulumi_env(sample_dir)
        try:
            result = subprocess.run(
                [
                    "pulumilocal",
                    "up",
                    "--yes",
                    "--non-interactive",
                    "--stack",
                    _stack_name(sample_dir),
                ],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                timeout=timeout,
                env=env,
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
                deployer_command="pulumilocal up",
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
                deployer_command="pulumilocal up",
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
            deployer_command="pulumilocal up",
        )

    def cleanup(self, sample_dir: Path) -> None:
        env = _pulumi_env(sample_dir)
        subprocess.run(
            [
                "pulumilocal",
                "destroy",
                "--yes",
                "--stack",
                _stack_name(sample_dir),
            ],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            env=env,
            timeout=180,
        )
        # Remove per-sample state directory
        state_dir = Path(f"/tmp/pulumi-{sample_dir.name}")
        shutil.rmtree(state_dir, ignore_errors=True)
