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

    # ------------------------------------------------------------------
    # ANSI stripping
    # ------------------------------------------------------------------

    def test_ansi_codes_stripped_before_classification(self):
        """ANSI escape codes in error output must be stripped before matching."""
        ansi_error = "\x1b[31mError: No value for required variable\x1b[0m"
        result = _make_result(error_message=ansi_error)
        from scanner.models import FailureCategory
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.MISSING_VARIABLE

    def test_ansi_codes_stripped_from_stdout(self):
        """ANSI stripping applies to stdout as well."""
        result = _make_result(
            error_message=None,
            stdout="\x1b[33mWarning\x1b[0m\x1b[31m connection refused\x1b[0m",
        )
        from scanner.models import FailureCategory
        category = self.classifier.classify(result, "http://localhost:4566")
        assert category == FailureCategory.NETWORK_ERROR

    # ------------------------------------------------------------------
    # New categories
    # ------------------------------------------------------------------

    def test_missing_variable_error(self):
        from scanner.models import FailureCategory
        result = _make_result(error_message="Error: No value for required variable")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.MISSING_VARIABLE

    def test_missing_variable_required_variable_phrase(self):
        from scanner.models import FailureCategory
        result = _make_result(stderr='Error: Input required for variable "db_password"')
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.MISSING_VARIABLE

    def test_provider_error_init_failure(self):
        from scanner.models import FailureCategory
        result = _make_result(stderr="Error: Failed to initialize provider")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.PROVIDER_ERROR

    def test_provider_error_could_not_load(self):
        from scanner.models import FailureCategory
        result = _make_result(stderr="Could not load provider: hashicorp/aws")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.PROVIDER_ERROR

    def test_provider_error_plugin_requirements(self):
        from scanner.models import FailureCategory
        result = _make_result(stderr="Error: Could not satisfy plugin requirements")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.PROVIDER_ERROR

    def test_resource_not_supported_error(self):
        from scanner.models import FailureCategory
        result = _make_result(error_message="Error: resource type not supported: aws_wafv2_web_acl")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.RESOURCE_NOT_SUPPORTED

    def test_resource_not_supported_type_not_found(self):
        from scanner.models import FailureCategory
        result = _make_result(stderr="UnknownResourceTypeException: resource type was not found")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.RESOURCE_NOT_SUPPORTED

    def test_auth_error_invalid_token(self):
        from scanner.models import FailureCategory
        result = _make_result(error_message="AuthFailure: InvalidClientTokenId provided")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.AUTH_ERROR

    def test_auth_error_no_credentials(self):
        from scanner.models import FailureCategory
        result = _make_result(stderr="Error: No valid credential sources found")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.AUTH_ERROR

    def test_network_error_connection_refused(self):
        from scanner.models import FailureCategory
        result = _make_result(error_message="Error: dial tcp 127.0.0.1:4566: connection refused")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.NETWORK_ERROR

    def test_network_error_dns_failure(self):
        from scanner.models import FailureCategory
        result = _make_result(stderr="Error: could not resolve host: s3.amazonaws.com")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.NETWORK_ERROR

    def test_localstack_500_is_localstack_bug(self):
        from scanner.models import FailureCategory
        result = _make_result(stderr="500 Internal Server Error")
        assert self.classifier.classify(result, "http://localhost:4566") == FailureCategory.LOCALSTACK_BUG

    # ------------------------------------------------------------------
    # Real failure message fixture (>= 20 messages) — verify NOT_CLASSIFIED < 30%
    # ------------------------------------------------------------------

    def test_not_classified_rate_below_30_percent_on_real_messages(self):
        """When tested against a representative sample of real failure messages,
        NOT_CLASSIFIED rate must be < 30%.
        """
        from scanner.models import FailureCategory

        real_failure_messages = [
            "Error: No value for required variable",
            "Error: Input required for variable \"cluster_name\". Call: var.cluster_name",
            "Error: Input required for variable \"db_password\"",
            "Error: Failed to initialize provider \"hashicorp/aws\"",
            "Error: Could not load provider registry.terraform.io/hashicorp/aws",
            "Error: Could not satisfy plugin requirements",
            "Error: resource type not supported: aws_wafv2_web_acl",
            "UnknownResourceTypeException: The resource type was not found",
            "Error: dial tcp 127.0.0.1:4566: connection refused",
            "Error: could not resolve host: s3.amazonaws.com",
            "AuthFailure: InvalidClientTokenId",
            "Error: No valid credential sources found",
            "Operation is not yet implemented: CreateDistribution",
            "UnsupportedOperation: ListTagsForResource",
            "HTTP 501: not implemented",
            "prepare() failed — dependency installation error",
            "CDK bootstrap failed: account not resolved",
            "/usr/bin/tflocal: command not found",
            "Error: No value for required variable: vpc_id",
            "Error: Failed to instantiate provider: error calling Provider.Configure",
            "Error: resource type not found: aws_codecatalyst_dev_environment",
            "Error: dial tcp: connection refused to localstack:4566",
            "ExpiredTokenException: The security token included in the request is expired",
        ]

        not_classified_count = 0
        for msg in real_failure_messages:
            result = _make_result(error_message=msg)
            category = self.classifier.classify(result, "http://localhost:4566")
            if category == FailureCategory.NOT_CLASSIFIED:
                not_classified_count += 1

        rate = not_classified_count / len(real_failure_messages)
        assert rate < 0.30, (
            f"NOT_CLASSIFIED rate too high: {not_classified_count}/{len(real_failure_messages)} "
            f"= {rate:.0%} (must be < 30%)"
        )
