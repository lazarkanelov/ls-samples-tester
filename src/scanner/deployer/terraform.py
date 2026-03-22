"""Terraform deployer using tflocal."""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from scanner.deployer.base import Deployer
from scanner.models import DeployResult, DeployStatus

logger = logging.getLogger(__name__)


class TerraformDeployer(Deployer):
    """Deploys Terraform samples via tflocal."""

    def prepare(self, sample_dir: Path) -> bool:
        result = subprocess.run(
            ["tflocal", "init"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            timeout=180,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or "tflocal init failed"
            logger.warning("tflocal init failed: %s", error)
            return False
        return True

    def deploy(self, sample_dir: Path, timeout: int) -> DeployResult:
        start = time.monotonic()
        try:
            result = subprocess.run(
                ["tflocal", "apply", "-auto-approve", "-input=false"],
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
                deployer_command="tflocal apply",
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
                error_message=result.stderr.strip() or result.stdout.strip() or "Non-zero exit code",
                services_used=[],
                deployer_command="tflocal apply",
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
            deployer_command="tflocal apply",
        )

    def cleanup(self, sample_dir: Path) -> None:
        subprocess.run(
            ["tflocal", "destroy", "-auto-approve"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            timeout=180,
        )
