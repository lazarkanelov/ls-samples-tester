"""Azure deployer for ARM/Bicep samples against LocalStack Azure emulator."""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from scanner.deployer.base import Deployer
from scanner.models import DeployResult, DeployStatus

logger = logging.getLogger(__name__)

_TEMPLATE_NAMES = [
    "azuredeploy.json",
    "azuredeploy.bicep",
    "main.bicep",
    "main.json",
]
_STACK_PREFIX = "scanner"


def _find_template(sample_dir: Path) -> Path | None:
    for name in _TEMPLATE_NAMES:
        p = sample_dir / name
        if p.exists():
            return p
    return None


class AzureDeployer(Deployer):
    """Deploys Azure ARM/Bicep samples via az CLI against LocalStack Azure emulator."""

    def prepare(self, sample_dir: Path) -> bool:
        return True

    def deploy(self, sample_dir: Path, timeout: int) -> DeployResult:
        start = time.monotonic()
        template = _find_template(sample_dir)
        if template is None:
            return DeployResult(
                sample_name=sample_dir.name,
                org="",
                status=DeployStatus.UNSUPPORTED,
                duration=0.0,
                stdout="",
                stderr="",
                error_message="No Azure ARM/Bicep template found",
                services_used=[],
                deployer_command="",
            )
        stack = f"{_STACK_PREFIX}-{sample_dir.name}"[:63]
        try:
            result = subprocess.run(
                [
                    "az",
                    "deployment",
                    "group",
                    "create",
                    "--resource-group",
                    "scanner-rg",
                    "--name",
                    stack,
                    "--template-file",
                    str(template),
                ],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                timeout=timeout,
            )
        except FileNotFoundError:
            return DeployResult(
                sample_name=sample_dir.name,
                org="",
                status=DeployStatus.UNSUPPORTED,
                duration=time.monotonic() - start,
                stdout="",
                stderr="",
                error_message="az CLI not found — Azure deployment requires az CLI",
                services_used=[],
                deployer_command="az deployment group create",
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
                deployer_command="az deployment group create",
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
                deployer_command="az deployment group create",
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
            deployer_command="az deployment group create",
        )

    def cleanup(self, sample_dir: Path) -> None:
        stack = f"{_STACK_PREFIX}-{sample_dir.name}"[:63]
        try:
            subprocess.run(
                [
                    "az",
                    "deployment",
                    "group",
                    "delete",
                    "--resource-group",
                    "scanner-rg",
                    "--name",
                    stack,
                ],
                capture_output=True,
                text=True,
                cwd=sample_dir,
                timeout=180,
            )
        except FileNotFoundError:
            pass
