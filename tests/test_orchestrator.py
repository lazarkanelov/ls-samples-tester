"""Tests for ScanOrchestrator and Sandbox."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from scanner.config import CloudProvider, Config, IaCType
from scanner.models import DeployResult, DeployStatus, FailureCategory, Sample


def _make_sample(iac_type: IaCType = IaCType.CLOUDFORMATION, name: str = "test-repo") -> Sample:
    return Sample(
        name=name,
        org="aws-samples",
        url=f"https://github.com/aws-samples/{name}",
        iac_type=iac_type,
        cloud_provider=CloudProvider.AWS,
        description="Test",
        topics=[],
        language="Python",
        default_branch="main",
        updated_at=datetime.now(),
    )


def _make_result(status: DeployStatus = DeployStatus.SUCCESS) -> DeployResult:
    return DeployResult(
        sample_name="test-repo",
        org="aws-samples",
        status=status,
        duration=1.0,
        stdout="ok",
        stderr="",
        error_message=None,
        services_used=[],
        deployer_command="",
    )


def _make_orchestrator(sandbox: MagicMock | None = None):
    from scanner.runner.orchestrator import ScanOrchestrator

    sb = sandbox if sandbox is not None else MagicMock()
    orch = ScanOrchestrator(Config(), sandbox=sb)
    return orch, sb


# ---------------------------------------------------------------------------
# ScanOrchestrator tests
# ---------------------------------------------------------------------------


def _make_verify_mocks(passed: bool = True, has_resources: bool = True):
    """Helper to create ResourceVerifier and ScriptDetector mocks."""
    from scanner.script_detector import ScriptOutcome
    from scanner.verifier import VerifyOutcome

    mock_verifier_cls = MagicMock()
    summary = "All passed" if passed else "Lambda fn: FAILED"
    outcome = VerifyOutcome(passed=passed, summary=summary, details=["detail"])
    mock_verifier_cls.return_value.verify.return_value = outcome

    mock_detector_cls = MagicMock()
    mock_detector_cls.return_value.detect.return_value = []
    mock_detector_cls.return_value.run.return_value = ScriptOutcome(
        passed=True, summary="No test scripts found"
    )
    return mock_verifier_cls, mock_detector_cls


class TestScanOrchestrator:
    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_resets_state_for_each_sample(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        samples = [_make_sample(), _make_sample(name="repo2")]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.side_effect = mock_verifier_cls.side_effect
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        assert ls_manager.reset.call_count == 2

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_returns_scan_report(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        from scanner.models import ScanReport

        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        assert isinstance(report, ScanReport)
        assert len(report.results) == 1

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_bootstraps_before_cdk_sample(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        samples = [_make_sample(iac_type=IaCType.CDK)]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.bootstrap.return_value = (True, "")
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        mock_deployer.bootstrap.assert_called_once()

    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_records_failure_if_cdk_bootstrap_fails(self, mock_get_deployer, mock_sleep, _):
        """Bootstrap failure produces FAILURE+DEPLOYER_ERROR, not SKIPPED."""
        samples = [_make_sample(iac_type=IaCType.CDK)]
        ls_manager = MagicMock()
        mock_deployer = MagicMock()
        mock_deployer.bootstrap.return_value = (False, "CDK bootstrap failed: account not resolved")
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator()
        report = orch.run(samples, ls_manager)

        result = report.results[0]
        assert result.status == DeployStatus.FAILURE
        assert result.failure_category == FailureCategory.DEPLOYER_ERROR
        assert result.error_message == "CDK bootstrap failed: account not resolved"

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_records_failure_if_prepare_fails(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = False
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        assert report.results[0].status == DeployStatus.FAILURE

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_classifies_failure_results(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        """Every non-SUCCESS result must have failure_category set by the classifier."""
        from scanner.models import DeployStatus

        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.FAILURE)
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        result = report.results[0]
        assert result.status == DeployStatus.FAILURE
        assert result.failure_category is not None

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_does_not_set_category_for_success(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        """SUCCESS results must not have failure_category set."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        assert report.results[0].failure_category is None

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_calls_cleanup_after_deploy(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        mock_deployer.cleanup.assert_called_once()

    # -----------------------------------------------------------------------
    # Verification tests
    # -----------------------------------------------------------------------

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_sets_partial_when_verification_fails(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """Deploy SUCCESS + verify FAIL → PARTIAL status."""
        from scanner.script_detector import ScriptOutcome
        from scanner.verifier import VerifyOutcome

        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer

        # Verifier: Lambda fails
        mock_verifier_cls.return_value.verify.return_value = VerifyOutcome(
            passed=False, summary="Lambda fn: FAILED", details=["Lambda fn: FAILED (error)"]
        )
        mock_detector_cls.return_value.detect.return_value = []
        mock_detector_cls.return_value.run.return_value = ScriptOutcome(
            passed=True, summary="No test scripts found"
        )

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        result = report.results[0]
        assert result.status == DeployStatus.PARTIAL
        assert result.verification_status == "FAILED"

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_keeps_success_when_verification_passes(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """Deploy SUCCESS + verify PASS → stays SUCCESS."""
        from scanner.script_detector import ScriptOutcome
        from scanner.verifier import VerifyOutcome

        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer

        mock_verifier_cls.return_value.verify.return_value = VerifyOutcome(
            passed=True, summary="All passed", details=["Lambda fn: OK"]
        )
        mock_detector_cls.return_value.detect.return_value = []
        mock_detector_cls.return_value.run.return_value = ScriptOutcome(
            passed=True, summary="No test scripts found"
        )

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        result = report.results[0]
        assert result.status == DeployStatus.SUCCESS
        assert result.verification_status == "PASSED"

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_does_not_verify_failed_deploys(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """Verification only runs for SUCCESS deploys."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.FAILURE)
        mock_get_deployer.return_value = mock_deployer

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        # ResourceVerifier.verify() must NOT be called for failed deploys
        mock_verifier_cls.return_value.verify.assert_not_called()

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_does_not_crash_when_verification_raises(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """Verification exception must not crash the scan."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls.return_value.verify.side_effect = RuntimeError("awslocal crashed")

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)  # must not raise

        assert len(report.results) == 1

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_skips_verification_when_disabled(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """Config.enable_verification=False must skip verification entirely."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer

        from scanner.config import Config
        from scanner.runner.orchestrator import ScanOrchestrator

        config = Config()
        config.enable_verification = False
        orch = ScanOrchestrator(config, sandbox=mock_sandbox)
        orch.run(samples, ls_manager)

        mock_verifier_cls.return_value.verify.assert_not_called()

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_does_not_set_category_for_partial(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """PARTIAL results must not have failure_category assigned."""
        from scanner.script_detector import ScriptOutcome
        from scanner.verifier import VerifyOutcome

        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer

        mock_verifier_cls.return_value.verify.return_value = VerifyOutcome(
            passed=False, summary="Lambda failed", details=["Lambda fn: FAILED"]
        )
        mock_detector_cls.return_value.detect.return_value = []
        mock_detector_cls.return_value.run.return_value = ScriptOutcome(
            passed=True, summary="No test scripts found"
        )

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        result = report.results[0]
        assert result.status == DeployStatus.PARTIAL
        assert result.failure_category is None

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_partial_status_stored_in_results(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """PARTIAL status must be stored in self._results (not just local variable)."""
        from scanner.script_detector import ScriptOutcome
        from scanner.verifier import VerifyOutcome

        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer

        mock_verifier_cls.return_value.verify.return_value = VerifyOutcome(
            passed=False, summary="Lambda failed", details=["Lambda fn: FAILED"]
        )
        mock_detector_cls.return_value.detect.return_value = []
        mock_detector_cls.return_value.run.return_value = ScriptOutcome(
            passed=True, summary="No test scripts found"
        )

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        # Verify the result in the report (stored reference) has PARTIAL
        assert report.results[0].status == DeployStatus.PARTIAL

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_sets_skipped_when_awslocal_unavailable(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """When awslocal is not available, verification_status must be SKIPPED."""
        from scanner.script_detector import ScriptOutcome
        from scanner.verifier import VerifyOutcome

        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer

        # ResourceVerifier returns the SKIPPED outcome (awslocal not found)
        mock_verifier_cls.return_value.verify.return_value = VerifyOutcome(
            passed=True,
            summary="Verification SKIPPED — awslocal not available",
            details=[],
        )
        mock_detector_cls.return_value.detect.return_value = []
        mock_detector_cls.return_value.run.return_value = ScriptOutcome(
            passed=True, summary="No test scripts found"
        )

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        result = report.results[0]
        assert result.status == DeployStatus.SUCCESS
        assert result.verification_status == "SKIPPED"

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_calls_cleanup_after_verification_crash(
        self, mock_get_deployer, mock_sleep, _, mock_detector_cls, mock_verifier_cls
    ):
        """deployer.cleanup must be called even when verification crashes."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result(status=DeployStatus.SUCCESS)
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls.return_value.verify.side_effect = RuntimeError("awslocal crashed")

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        mock_deployer.cleanup.assert_called_once()

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_captures_localstack_logs_after_deploy(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        """After each deploy, orchestrator calls get_recent_logs() and stores the result."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        ls_manager.get_recent_logs.return_value = "INFO: LocalStack ready\n"
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        ls_manager.get_recent_logs.assert_called_once()
        assert report.results[0].localstack_logs == "INFO: LocalStack ready\n"

    # -----------------------------------------------------------------------
    # Retry logic tests
    # -----------------------------------------------------------------------

    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_transient_failure_is_retried(
        self, mock_get_deployer, mock_sleep, _, mock_detector, mock_verifier
    ):
        """A deploy result with 'connection refused' in error_message triggers a retry."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True

        transient = _make_result(status=DeployStatus.FAILURE)
        transient.error_message = "dial tcp: connection refused to localstack:4566"
        success = _make_result(status=DeployStatus.SUCCESS)
        mock_deployer.deploy.side_effect = [transient, success]
        mock_get_deployer.return_value = mock_deployer
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        config = Config()
        config.max_retries = 1
        config.retry_delay = 0
        from scanner.runner.orchestrator import ScanOrchestrator
        orch = ScanOrchestrator(config, sandbox=mock_sandbox)
        report = orch.run(samples, ls_manager)

        assert mock_deployer.deploy.call_count == 2
        assert report.results[0].status == DeployStatus.SUCCESS

    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_non_transient_failure_is_not_retried(self, mock_get_deployer, mock_sleep, _):
        """A deploy failure without transient signals is not retried."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        failure = _make_result(status=DeployStatus.FAILURE)
        failure.error_message = "Error: No value for required variable: vpc_id"
        mock_deployer.deploy.return_value = failure
        mock_get_deployer.return_value = mock_deployer

        config = Config()
        config.max_retries = 2
        config.retry_delay = 0
        from scanner.runner.orchestrator import ScanOrchestrator
        orch = ScanOrchestrator(config, sandbox=mock_sandbox)
        orch.run(samples, ls_manager)

        assert mock_deployer.deploy.call_count == 1

    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_retry_exhausted_returns_last_result(self, mock_get_deployer, mock_sleep, _):
        """When all retry attempts fail, the last result is stored."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        transient = _make_result(status=DeployStatus.FAILURE)
        transient.error_message = "connection refused"
        mock_deployer.deploy.return_value = transient
        mock_get_deployer.return_value = mock_deployer

        config = Config()
        config.max_retries = 2
        config.retry_delay = 0
        from scanner.runner.orchestrator import ScanOrchestrator
        orch = ScanOrchestrator(config, sandbox=mock_sandbox)
        report = orch.run(samples, ls_manager)

        assert mock_deployer.deploy.call_count == 3  # 1 initial + 2 retries
        assert report.results[0].status == DeployStatus.FAILURE


# ---------------------------------------------------------------------------
# Task 9: Service extraction + duration tracker integration
# ---------------------------------------------------------------------------


class TestServiceExtractionIntegration:
    @patch("scanner.runner.orchestrator.DurationTracker")
    @patch("scanner.runner.orchestrator.ServiceExtractor")
    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_extracts_services_and_sets_on_result(
        self,
        mock_get_deployer,
        mock_sleep,
        _,
        mock_detector,
        mock_verifier,
        mock_extractor_cls,
        mock_tracker_cls,
    ):
        """ServiceExtractor.extract() is called and result.services_used is populated."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        result = _make_result()
        result.services_used = []
        mock_deployer.deploy.return_value = result
        mock_get_deployer.return_value = mock_deployer
        mock_extractor_cls.return_value.extract.return_value = ["Lambda", "S3"]
        mock_tracker_instance = MagicMock()
        mock_tracker_instance.get_timeout.return_value = 600
        mock_tracker_cls.load.return_value = mock_tracker_instance
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        report = orch.run(samples, ls_manager)

        mock_extractor_cls.return_value.extract.assert_called_once()
        assert report.results[0].services_used == ["Lambda", "S3"]

    @patch("scanner.runner.orchestrator.DurationTracker")
    @patch("scanner.runner.orchestrator.ServiceExtractor")
    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_records_duration_after_deploy(
        self,
        mock_get_deployer,
        mock_sleep,
        _,
        mock_detector,
        mock_verifier,
        mock_extractor_cls,
        mock_tracker_cls,
    ):
        """DurationTracker.record() is called after each successful deploy."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer
        mock_extractor_cls.return_value.extract.return_value = []
        mock_tracker_instance = MagicMock()
        mock_tracker_instance.get_timeout.return_value = 600
        mock_tracker_cls.load.return_value = mock_tracker_instance
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        mock_tracker_instance.record.assert_called_once()

    @patch("scanner.runner.orchestrator.DurationTracker")
    @patch("scanner.runner.orchestrator.ServiceExtractor")
    @patch("scanner.runner.orchestrator.ResourceVerifier")
    @patch("scanner.runner.orchestrator.ScriptDetector")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_saves_duration_tracker_at_end(
        self,
        mock_get_deployer,
        mock_sleep,
        _,
        mock_detector,
        mock_verifier,
        mock_extractor_cls,
        mock_tracker_cls,
    ):
        """DurationTracker.save() is called once at the end of run()."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer
        mock_extractor_cls.return_value.extract.return_value = []
        mock_tracker_instance = MagicMock()
        mock_tracker_instance.get_timeout.return_value = 600
        mock_tracker_cls.load.return_value = mock_tracker_instance
        mock_verifier_cls, mock_detector_cls = _make_verify_mocks()
        mock_verifier.return_value = mock_verifier_cls.return_value
        mock_detector.return_value = mock_detector_cls.return_value

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        mock_tracker_instance.save.assert_called_once()

    @patch("scanner.runner.orchestrator.DurationTracker")
    @patch("scanner.runner.orchestrator.ServiceExtractor")
    @patch("scanner.runner.orchestrator._capture_tool_versions", return_value={})
    @patch("scanner.runner.orchestrator.time.sleep")
    @patch("scanner.runner.orchestrator.get_deployer")
    def test_run_uses_adaptive_timeout_from_tracker(
        self,
        mock_get_deployer,
        mock_sleep,
        _,
        mock_extractor_cls,
        mock_tracker_cls,
    ):
        """Deployer.deploy() is called with the timeout returned by DurationTracker."""
        samples = [_make_sample()]
        ls_manager = MagicMock()
        mock_sandbox = MagicMock()
        mock_sandbox.clone_sample.return_value = Path("/tmp/test")
        mock_deployer = MagicMock()
        mock_deployer.prepare.return_value = True
        mock_deployer.deploy.return_value = _make_result()
        mock_get_deployer.return_value = mock_deployer
        mock_extractor_cls.return_value.extract.return_value = []

        mock_tracker_instance = MagicMock()
        mock_tracker_instance.get_timeout.return_value = 999  # distinctive value
        mock_tracker_cls.load.return_value = mock_tracker_instance

        orch, _ = _make_orchestrator(mock_sandbox)
        orch.run(samples, ls_manager)

        _, kwargs = mock_deployer.deploy.call_args
        assert kwargs.get("timeout") == 999


# ---------------------------------------------------------------------------
# Sandbox tests
# ---------------------------------------------------------------------------


class TestSandbox:
    @patch("scanner.runner.sandbox.subprocess.run")
    @patch("scanner.runner.sandbox.tempfile.mkdtemp")
    def test_clone_sample_calls_git_clone(self, mock_mkdtemp, mock_run, tmp_path):
        from scanner.runner.sandbox import Sandbox

        mock_mkdtemp.return_value = str(tmp_path)
        mock_run.return_value = MagicMock(returncode=0)
        sandbox = Sandbox()
        sample = _make_sample()
        sandbox.clone_sample(sample)
        cmd = mock_run.call_args[0][0]
        assert "git" in cmd
        assert "clone" in cmd
        assert "--depth" in cmd
        assert sample.url in cmd

    @patch("scanner.runner.sandbox.shutil.rmtree")
    def test_cleanup_removes_directory(self, mock_rmtree, tmp_path):
        from scanner.runner.sandbox import Sandbox

        sandbox = Sandbox()
        sandbox.cleanup(tmp_path)
        mock_rmtree.assert_called_once_with(tmp_path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Data retention pruning
# ---------------------------------------------------------------------------


class TestPruneOldResults:
    def test_prune_keeps_most_recent(self, tmp_path):
        from scanner.runner.orchestrator import _prune_old_results

        for i in range(5):
            f = tmp_path / f"2026-0{i + 1}-01.json"
            f.write_text("{}")
            os.utime(f, (i * 1000, i * 1000))

        _prune_old_results(tmp_path, keep=3)
        assert len(list(tmp_path.glob("*.json"))) == 3

    def test_prune_does_nothing_when_under_limit(self, tmp_path):
        from scanner.runner.orchestrator import _prune_old_results

        (tmp_path / "2026-01-01.json").write_text("{}")
        _prune_old_results(tmp_path, keep=12)
        assert len(list(tmp_path.glob("*.json"))) == 1
