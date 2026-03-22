"""Tests for FailureClassifier."""
from __future__ import annotations

from unittest.mock import patch

from scanner.models import DeployResult, DeployStatus, FailureCategory


def _make_result(
    status: DeployStatus = DeployStatus.FAILURE,
    error_message: str | None = "some error",
    stdout: str = "",
    stderr: str = "",
) -> DeployResult:
    return DeployResult(
        sample_name="test",
        org="aws-samples",
        status=status,
        duration=5.0,
        stdout=stdout,
        stderr=stderr,
        error_message=error_message,
        services_used=[],
        deployer_command="tflocal apply",
    )


class TestFailureClassifier:
    def setup_method(self):
        from scanner.classifier import FailureClassifier

        self.classifier = FailureClassifier()

    def test_timeout_status_classified_as_timeout(self):
        result = _make_result(status=DeployStatus.TIMEOUT)
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.TIMEOUT

    def test_not_implemented_in_error_message_is_localstack_bug(self):
        result = _make_result(error_message="Operation is not yet implemented")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.LOCALSTACK_BUG

    def test_unsupported_operation_is_localstack_bug(self):
        result = _make_result(error_message="UnsupportedOperation: ListTagsForResource")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.LOCALSTACK_BUG

    def test_501_in_error_message_is_localstack_bug(self):
        result = _make_result(error_message="HTTP 501: not implemented")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.LOCALSTACK_BUG

    def test_not_implemented_error_class_is_localstack_bug(self):
        result = _make_result(error_message="NotImplementedError raised by handler")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.LOCALSTACK_BUG

    def test_prepare_failed_is_deployer_error(self):
        result = _make_result(error_message="prepare() failed — dependency installation error")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.DEPLOYER_ERROR

    def test_bootstrap_failed_is_deployer_error(self):
        result = _make_result(error_message="CDK bootstrap failed")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.DEPLOYER_ERROR

    def test_command_not_found_is_deployer_error(self):
        result = _make_result(error_message="/usr/bin/tflocal: command not found")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.DEPLOYER_ERROR

    def test_config_profile_is_sample_error(self):
        result = _make_result(error_message="config profile 'prod' not found")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.SAMPLE_ERROR

    def test_no_pattern_match_returns_not_classified(self):
        result = _make_result(error_message="Something completely generic happened")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.NOT_CLASSIFIED

    def test_internal_error_is_not_classified(self):
        """InternalError is ambiguous — could be LS or sample config issue."""
        result = _make_result(error_message="InternalError: something went wrong")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.NOT_CLASSIFIED

    def test_service_exception_is_not_classified(self):
        """ServiceException is ambiguous — could be LS or sample config issue."""
        result = _make_result(error_message="ServiceException: invalid parameter")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.NOT_CLASSIFIED

    def test_pattern_matched_in_stdout_when_error_message_empty(self):
        """Classifier falls back to stdout/stderr when error_message is empty."""
        result = _make_result(
            error_message="Non-zero exit code",
            stdout="Error: not yet implemented: CreateFunction",
        )
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.LOCALSTACK_BUG

    @patch("scanner.classifier.requests.get")
    def test_diagnose_endpoint_supplementary_localstack_bug(self, mock_get):
        """If error_message has no pattern but /diagnose has LS bug pattern, use it."""
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.text = "ERROR: not yet implemented: some service"
        result = _make_result(error_message="Non-zero exit code", stdout="", stderr="")
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.LOCALSTACK_BUG

    @patch("scanner.classifier.requests.get")
    def test_diagnose_endpoint_failure_falls_back_gracefully(self, mock_get):
        """Connection error to /diagnose endpoint must not crash classification."""
        import requests

        mock_get.side_effect = requests.ConnectionError("refused")
        result = _make_result(error_message="Non-zero exit code")
        # Must not raise — returns NOT_CLASSIFIED
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.NOT_CLASSIFIED

    def test_success_status_returns_none(self):
        """SUCCESS results should not be classified."""
        result = _make_result(status=DeployStatus.SUCCESS, error_message=None)
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category is None
