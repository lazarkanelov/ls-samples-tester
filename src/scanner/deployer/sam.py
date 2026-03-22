"""SAM deployer using samlocal."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path

from scanner.deployer.base import Deployer
from scanner.models import DeployResult, DeployStatus

logger = logging.getLogger(__name__)

_SAM_BUCKET = "localstack-sam-deployments"
_SAM_ENV = {**os.environ, "AWS_DEFAULT_REGION": "us-east-1"}


def _stack_name(sample_dir: Path) -> str:
    """Generate a valid CloudFormation stack name from a directory name."""
    name = sample_dir.name.lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:128] or "scanner-stack"


def _samconfig_s3_bucket(sample_dir: Path) -> str | None:
    """Read s3_bucket from samconfig.toml if present, else return None."""
    samconfig = sample_dir / "samconfig.toml"
    if not samconfig.exists():
        return None
    for line in samconfig.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("s3_bucket"):
            parts = stripped.split("=", 1)
            if len(parts) == 2:
                value = parts[1].strip()
                value = value.split("#")[0].strip()  # strip inline TOML comments first
                value = value.strip('"').strip("'")  # then strip quotes
                return value or None
    return None


class SamDeployer(Deployer):
    """Deploys SAM samples via samlocal."""

    def prepare(self, sample_dir: Path) -> bool:
        # Create the S3 deployment bucket before building
        bucket = _samconfig_s3_bucket(sample_dir) or _SAM_BUCKET
        subprocess.run(
            ["awslocal", "s3", "mb", f"s3://{bucket}", "--region", "us-east-1"],
            capture_output=True,
            text=True,
            env=_SAM_ENV,
            timeout=30,
        )

        # Try no-container build first (avoids Docker-in-Docker issues in CI)
        result = subprocess.run(
            ["samlocal", "build", "--no-use-container", "--region", "us-east-1"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            env=_SAM_ENV,
            timeout=180,
        )
        if result.returncode == 0:
            return True
        logger.warning("SAM no-container build failed, retrying with container build")
        result = subprocess.run(
            ["samlocal", "build", "--region", "us-east-1"],
            capture_output=True,
            text=True,
            cwd=sample_dir,
            env=_SAM_ENV,
            timeout=180,
        )
        return result.returncode == 0

    def deploy(self, sample_dir: Path, timeout: int) -> DeployResult:
        start = time.monotonic()
        stack = _stack_name(sample_dir)

        # Build deploy command — only add --s3-bucket if samconfig.toml doesn't specify one
        existing_bucket = _samconfig_s3_bucket(sample_dir)
        cmd = [
            "samlocal",
            "deploy",
            "--stack-name",
            stack,
            "--capabilities",
            "CAPABILITY_IAM",
            "CAPABILITY_AUTO_EXPAND",
            "--no-confirm-changeset",
            "--region",
            "us-east-1",
        ]
        if not existing_bucket:
            cmd += ["--s3-bucket", _SAM_BUCKET]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=sample_dir,
                env=_SAM_ENV,
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
                error_message=result.stderr.strip() or result.stdout.strip() or "Non-zero exit code",
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
