"""CDK deployer using cdklocal."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from scanner.deployer.base import Deployer
from scanner.models import DeployResult, DeployStatus

logger = logging.getLogger(__name__)

_CDK_ENV = {
    **os.environ,
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
    "CDK_DEFAULT_ACCOUNT": "000000000000",
    "CDK_DEFAULT_REGION": "us-east-1",
}


class CdkDeployer(Deployer):
    """Deploys CDK samples via cdklocal."""

    def bootstrap(self, timeout: int = 300) -> tuple[bool, str]:
        result = subprocess.run(
            ["cdklocal", "bootstrap"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_CDK_ENV,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or "CDK bootstrap failed"
            logger.warning("CDK bootstrap failed: %s", error)
            return False, error
        return True, ""

    def prepare(self, sample_dir: Path) -> bool:
        if (sample_dir / "package.json").exists():
            result = subprocess.run(
                ["npm", "install"],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                timeout=180,
            )
            return result.returncode == 0
        if (sample_dir / "requirements.txt").exists():
            result = subprocess.run(
                ["pip", "install", "-r", "requirements.txt"],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                timeout=180,
            )
            return result.returncode == 0
        return True

    def deploy(self, sample_dir: Path, timeout: int) -> DeployResult:
        start = time.monotonic()
        try:
            result = subprocess.run(
                ["cdklocal", "deploy", "--all", "--require-approval=never"],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                timeout=timeout,
                env=_CDK_ENV,
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
                deployer_command="cdklocal deploy",
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
                deployer_command="cdklocal deploy",
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
            deployer_command="cdklocal deploy",
        )

    def cleanup(self, sample_dir: Path) -> None:
        subprocess.run(
            ["cdklocal", "destroy", "--all", "--force"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
        )
