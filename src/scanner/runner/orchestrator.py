"""Scan orchestrator — runs the full deployment pipeline."""
from __future__ import annotations

import logging
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scanner.classifier import FailureClassifier
from scanner.config import Config, IaCType
from scanner.deployer import get_deployer
from scanner.duration_tracker import DurationTracker
from scanner.models import DeployResult, DeployStatus, FailureCategory, Sample, ScanReport
from scanner.runner.localstack import LocalStackManager
from scanner.runner.sandbox import Sandbox
from scanner.script_detector import ScriptDetector
from scanner.service_extractor import ServiceExtractor
from scanner.verifier import ResourceVerifier

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


_TRANSIENT_SIGNALS = (
    "connection refused",
    "connection error",
    "connectionerror",
    "rate limit",
    "timed out",
    "timeout",
)


def _is_transient_failure(result: DeployResult) -> bool:
    if result.status == DeployStatus.SUCCESS:
        return False
    text = " ".join(
        filter(None, [result.error_message, result.stderr])
    ).lower()
    return any(sig in text for sig in _TRANSIENT_SIGNALS)


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
        self._classifier = FailureClassifier()
        self._duration_tracker = DurationTracker.load(Path(config.durations_path))
        self._service_extractor = ServiceExtractor()

    def _classify_result(self, result: DeployResult) -> None:
        """Classify a failed result in-place; never raises."""
        if (
            result.status in (DeployStatus.SUCCESS, DeployStatus.PARTIAL)
            or result.failure_category is not None
        ):
            return
        try:
            category = self._classifier.classify(result, self._config.localstack_endpoint)
            if category is not None:
                result.failure_category = category
        except Exception as exc:
            logger.debug("Classification failed for %s: %s", result.sample_name, exc)

    def _verify_sample(self, sample_dir: Path, result: DeployResult) -> None:
        """Run resource verification and script detection; mutates result in-place; never raises."""
        try:
            verifier = ResourceVerifier()
            verify_outcome = verifier.verify(
                self._config.localstack_endpoint,
                timeout=self._config.verification_timeout,
            )

            detector = ScriptDetector()
            scripts = detector.detect(sample_dir)
            script_outcome = detector.run(
                sample_dir, scripts, timeout=self._config.verification_timeout
            )

            any_failed = (not verify_outcome.passed) or (scripts and not script_outcome.passed)
            no_resources = (
                "No verifiable resources" in verify_outcome.summary
                or "SKIPPED" in verify_outcome.summary
            )
            no_scripts = not scripts

            details_parts = verify_outcome.details[:]
            if scripts:
                details_parts.append(script_outcome.summary)
                if script_outcome.details:
                    details_parts.extend(script_outcome.details)

            result.verification_details = "; ".join(details_parts) if details_parts else None

            if any_failed:
                result.verification_status = "FAILED"
                result.status = DeployStatus.PARTIAL
            elif no_resources and no_scripts:
                result.verification_status = "SKIPPED"
            else:
                result.verification_status = "PASSED"
        except Exception as exc:
            logger.warning("Verification failed for %s: %s", result.sample_name, exc)

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
            reset_time = time.time()
            ls_manager.reset()
            time.sleep(3)  # Allow services to stabilise after reset

            # CDK bootstrap after state reset (before cloning)
            if sample.iac_type == IaCType.CDK:
                cdk_deployer = get_deployer(IaCType.CDK)
                bootstrap_ok, bootstrap_error = cdk_deployer.bootstrap(timeout=120)
                if not bootstrap_ok:
                    logger.warning(
                        "CDK bootstrap failed for %s: %s", sample.name, bootstrap_error
                    )
                    self._results.append(
                        DeployResult(
                            sample_name=sample.name,
                            org=sample.org,
                            status=DeployStatus.FAILURE,
                            duration=0.0,
                            stdout="",
                            stderr="",
                            error_message=bootstrap_error or "CDK bootstrap failed",
                            services_used=[],
                            deployer_command="cdklocal bootstrap",
                            iac_type=sample.iac_type,
                            cloud_provider=sample.cloud_provider,
                            failure_category=FailureCategory.DEPLOYER_ERROR,
                        )
                    )
                    continue

            sample_dir: Path | None = None
            full_name = f"{sample.org}/{sample.name}"
            try:
                sample_dir = self._sandbox.clone_sample(sample)
                deployer = get_deployer(sample.iac_type)

                # Extract AWS services from IaC files before deploying
                services = self._service_extractor.extract(sample_dir, sample.iac_type)

                if not deployer.prepare(sample_dir):
                    result = DeployResult(
                        sample_name=sample.name,
                        org=sample.org,
                        status=DeployStatus.FAILURE,
                        duration=0.0,
                        stdout="",
                        stderr="",
                        error_message="prepare() failed — dependency installation error",
                        services_used=services,
                        deployer_command="",
                        iac_type=sample.iac_type,
                        cloud_provider=sample.cloud_provider,
                    )
                else:
                    timeout = self._duration_tracker.get_timeout(
                        full_name,
                        self._config.per_sample_timeout,
                        self._config.per_sample_timeout_min,
                        self._config.per_sample_timeout_max,
                    )
                    result = deployer.deploy(sample_dir, timeout=timeout)
                    for attempt in range(self._config.max_retries):
                        if not _is_transient_failure(result):
                            break
                        budget_ok = (
                            time.monotonic() + self._config.retry_delay + timeout < deadline
                        )
                        if not budget_ok:
                            break
                        logger.info(
                            "Transient failure for %s, retrying (attempt %d/%d)...",
                            sample.name, attempt + 1, self._config.max_retries,
                        )
                        ls_manager.reset()
                        time.sleep(self._config.retry_delay)
                        result = deployer.deploy(sample_dir, timeout=timeout)
                    result.iac_type = sample.iac_type
                    result.cloud_provider = sample.cloud_provider
                    result.org = sample.org
                    result.sample_name = sample.name
                    # Use extractor services if deployer did not populate services_used
                    if not result.services_used:
                        result.services_used = services

                self._classify_result(result)
                if result.status == DeployStatus.SUCCESS and self._config.enable_verification:
                    self._verify_sample(sample_dir, result)
                result.localstack_logs = ls_manager.get_recent_logs(since_reset=reset_time)
                self._duration_tracker.record(full_name, result.duration)
                self._results.append(result)

                try:
                    deployer.cleanup(sample_dir)
                except Exception as exc:
                    logger.warning("Cleanup failed for %s: %s", sample.name, exc)

            except Exception as exc:
                logger.error("Unexpected error for %s: %s", sample.name, exc)
                exc_result = DeployResult(
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
                self._classify_result(exc_result)
                self._results.append(exc_result)
            finally:
                if sample_dir is not None:
                    self._sandbox.cleanup(sample_dir)

        self._duration_tracker.save(Path(self._config.durations_path))

        return ScanReport(
            results=self._results,
            scan_date=datetime.now(UTC).strftime("%Y-%m-%d"),
            total_samples=total,
            tool_versions=tool_versions,
        )
