"""SAM deployer using samlocal."""
from __future__ import annotations

import logging
import re
import subprocess
import time
from pathlib import Path

from scanner.deployer.base import Deployer
from scanner.models import DeployResult, DeployStatus

logger = logging.getLogger(__name__)


def _stack_name(sample_dir: Path) -> str:
    """Generate a valid CloudFormation stack name from a directory name."""
    name = sample_dir.name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:128] or "scanner-stack"


class SamDeployer(Deployer):
    """Deploys SAM samples via samlocal."""

    def prepare(self, sample_dir: Path) -> bool:
        # Try no-container build first (avoids Docker-in-Docker issues in CI)
        result = subprocess.run(
            ["samlocal", "build", "--no-use-container"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            timeout=180,
        )
        if result.returncode == 0:
            return True
        logger.warning("SAM no-container build failed, retrying with container build")
        result = subprocess.run(
            ["samlocal", "build"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            timeout=180,
        )
        return result.returncode == 0

    def deploy(self, sample_dir: Path, timeout: int) -> DeployResult:
        start = time.monotonic()
        stack = _stack_name(sample_dir)
        try:
            result = subprocess.run(
                [
                    "samlocal",
                    "deploy",
                    "--stack-name",
                    stack,
                    "--capabilities",
                    "CAPABILITY_IAM",
                    "CAPABILITY_AUTO_EXPAND",
                    "--resolve-s3",
                    "--no-confirm-changeset",
                ],
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
                deployer_command="samlocal deploy",
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
                deployer_command="samlocal deploy",
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
            deployer_command="samlocal deploy",
        )

    def cleanup(self, sample_dir: Path) -> None:
        stack = _stack_name(sample_dir)
        subprocess.run(
            ["awslocal", "cloudformation", "delete-stack", "--stack-name", stack],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            timeout=180,
        )
