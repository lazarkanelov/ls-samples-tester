"""CloudFormation deployer using awslocal."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path

from scanner.deployer.base import Deployer
from scanner.models import DeployResult, DeployStatus

logger = logging.getLogger(__name__)

_TEMPLATE_NAMES = ["template.yaml", "template.yml", "template.json"]


def _stack_name(sample_dir: Path) -> str:
    """Generate a valid CloudFormation stack name from a directory name."""
    name = sample_dir.name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:128] or "scanner-stack"


def _find_template(sample_dir: Path) -> Path | None:
    # Check root directory first
    for name in _TEMPLATE_NAMES:
        p = sample_dir / name
        if p.exists():
            return p
    # Search one level deep in subdirectories (alphabetical for determinism)
    for subdir in sorted(p for p in sample_dir.iterdir() if p.is_dir()):
        for name in _TEMPLATE_NAMES:
            p = subdir / name
            if p.exists():
                return p
    return None


class CloudFormationDeployer(Deployer):
    """Deploys CloudFormation samples via awslocal."""

    def prepare(self, sample_dir: Path) -> bool:
        template = _find_template(sample_dir)
        if template is None:
            return True
        result = subprocess.run(
            [
                "awslocal",
                "cloudformation",
                "validate-template",
                "--template-body",
                f"file://{template}",
            ],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            timeout=180,
        )
        if result.returncode != 0:
            logger.warning("Template validation failed: %s", result.stderr)
            return False
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
                error_message="No CloudFormation template found",
                services_used=[],
                deployer_command="",
            )
        stack = _stack_name(sample_dir)
        cmd = [
            "awslocal",
            "cloudformation",
            "deploy",
            "--template-file",
            str(template),
            "--stack-name",
            stack,
            "--capabilities",
            "CAPABILITY_IAM",
            "CAPABILITY_AUTO_EXPAND",
        ]
        # Detect parameter files and pass overrides
        param_files = sorted(sample_dir.glob("*parameters*.json"))
        if param_files:
            try:
                params = json.loads(param_files[0].read_text())
                overrides = [
                    f"{p['ParameterKey']}={p['ParameterValue']}" for p in params
                ]
                if overrides:
                    cmd += ["--parameter-overrides"] + overrides
            except Exception as exc:
                logger.warning("Failed to parse parameter file: %s", exc)
        try:
            result = subprocess.run(
                cmd,
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
                deployer_command="awslocal cloudformation deploy",
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
                deployer_command="awslocal cloudformation deploy",
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
            deployer_command="awslocal cloudformation deploy",
        )

    def cleanup(self, sample_dir: Path) -> None:
        stack = _stack_name(sample_dir)
        subprocess.run(
            ["awslocal", "cloudformation", "delete-stack", "--stack-name", stack],
            capture_output=True,
            text=True,
            timeout=180,
        )
