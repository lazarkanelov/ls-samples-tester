"""Scan orchestrator — runs the full deployment pipeline."""
from __future__ import annotations

import logging
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scanner.config import Config, IaCType
from scanner.deployer import get_deployer
from scanner.models import DeployResult, DeployStatus, Sample, ScanReport
from scanner.runner.localstack import LocalStackManager
from scanner.runner.sandbox import Sandbox

logger = logging.getLogger(__name__)

_TOOL_CMDS: dict[str, list[str]] = {
    "cdklocal": ["cdklocal", "--version"],
    "samlocal": ["samlocal", "--version"],
    "tflocal": ["tflocal", "--version"],
    "pulumilocal": ["pulumilocal", "version"],
}


def _capture_version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or r.stderr.strip()
    except Exception:
        return "unavailable"


def _capture_tool_versions() -> dict[str, str]:
    return {name: _capture_version(cmd) for name, cmd in _TOOL_CMDS.items()}


def _prune_old_results(results_dir: Path, keep: int) -> None:
    """Remove oldest result JSON files, keeping only `keep` most recent."""
    files = sorted(results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for old in files[: max(0, len(files) - keep)]:
        old.unlink(missing_ok=True)


class ScanOrchestrator:
    """Runs the full scan pipeline — clone, deploy, collect results."""

    def __init__(self, config: Config, sandbox: Sandbox | None = None) -> None:
        self._config = config
        self._sandbox = sandbox if sandbox is not None else Sandbox()
        self._stop = False
        self._results: list[DeployResult] = []

    def _handle_signal(self, *_: Any) -> None:
        logger.warning("Signal received — stopping after current sample")
        self._stop = True

    def run(
        self,
        samples: list[Sample],
        ls_manager: LocalStackManager,
    ) -> ScanReport:
        """Deploy each sample and return a ScanReport."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        self._results = []
        self._stop = False
        total = len(samples)
        tool_versions = _capture_tool_versions()

        deadline = time.monotonic() + self._config.overall_scan_timeout

        for idx, sample in enumerate(samples, start=1):
            if self._stop:
                logger.info("Stopping scan early (signal received)")
                break

            if time.monotonic() > deadline:
                logger.warning("Overall scan timeout reached — stopping early")
                break

            logger.info(
                "Deploying sample %d/%d: %s/%s (%s)",
                idx,
                total,
                sample.org,
                sample.name,
                sample.iac_type.value,
            )

            # Reset LocalStack state before each sample
            ls_manager.reset()
            time.sleep(3)  # Allow services to stabilise after reset

            # CDK bootstrap after state reset (before cloning)
            if sample.iac_type == IaCType.CDK:
                cdk_deployer = get_deployer(IaCType.CDK)
                if not cdk_deployer.bootstrap(timeout=120):
                    logger.warning(
                        "CDK bootstrap failed for %s — skipping", sample.name
                    )
                    self._results.append(
                        DeployResult(
                            sample_name=sample.name,
                            org=sample.org,
                            status=DeployStatus.SKIPPED,
                            duration=0.0,
                            stdout="",
                            stderr="",
                            error_message="CDK bootstrap failed",
                            services_used=[],
                            deployer_command="cdklocal bootstrap",
                            iac_type=sample.iac_type,
                            cloud_provider=sample.cloud_provider,
                        )
                    )
                    continue

            sample_dir: Path | None = None
            try:
                sample_dir = self._sandbox.clone_sample(sample)
                deployer = get_deployer(sample.iac_type)

                if not deployer.prepare(sample_dir):
                    result = DeployResult(
                        sample_name=sample.name,
                        org=sample.org,
                        status=DeployStatus.FAILURE,
                        duration=0.0,
                        stdout="",
                        stderr="",
                        error_message="prepare() failed — dependency installation error",
                        services_used=[],
                        deployer_command="",
                        iac_type=sample.iac_type,
                        cloud_provider=sample.cloud_provider,
                    )
                else:
                    result = deployer.deploy(
                        sample_dir,
                        timeout=self._config.per_sample_timeout,
                    )
                    result.iac_type = sample.iac_type
                    result.cloud_provider = sample.cloud_provider
                    result.org = sample.org
                    result.sample_name = sample.name

                self._results.append(result)

                try:
                    deployer.cleanup(sample_dir)
                except Exception as exc:
                    logger.warning("Cleanup failed for %s: %s", sample.name, exc)

            except Exception as exc:
                logger.error("Unexpected error for %s: %s", sample.name, exc)
                self._results.append(
                    DeployResult(
                        sample_name=sample.name,
                        org=sample.org,
                        status=DeployStatus.FAILURE,
                        duration=0.0,
                        stdout="",
                        stderr="",
                        error_message=str(exc),
                        services_used=[],
                        deployer_command="",
                        iac_type=sample.iac_type,
                        cloud_provider=sample.cloud_provider,
                    )
                )
            finally:
                if sample_dir is not None:
                    self._sandbox.cleanup(sample_dir)

        return ScanReport(
            results=self._results,
            scan_date=datetime.now(UTC).strftime("%Y-%m-%d"),
            total_samples=total,
            tool_versions=tool_versions,
        )
