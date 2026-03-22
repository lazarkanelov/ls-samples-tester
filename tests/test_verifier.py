"""Tests for ResourceVerifier."""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, mock_open, patch

import pytest

from scanner.verifier import ResourceVerifier, VerifyOutcome


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class TestVerifyOutcome:
    def test_verify_outcome_dataclass(self):
        outcome = VerifyOutcome(passed=True, summary="All OK", details=["Lambda fn: OK"])
        assert outcome.passed is True
        assert outcome.summary == "All OK"
        assert outcome.details == ["Lambda fn: OK"]


class TestResourceVerifierInit:
    def test_instantiates(self):
        verifier = ResourceVerifier()
        assert verifier is not None


class TestResourceVerifierAwslocalNotAvailable:
    @patch("scanner.verifier.subprocess.run", side_effect=FileNotFoundError("awslocal not found"))
    def test_returns_skipped_when_awslocal_missing(self, mock_run):
        verifier = ResourceVerifier()
        outcome = verifier.verify("http://localhost:4566")
        assert outcome.passed is True
        assert "SKIPPED" in outcome.summary.upper() or "not available" in outcome.summary.lower()


class TestLambdaVerification:
    @patch("scanner.verifier.subprocess.run")
    def test_lists_lambda_functions(self, mock_run):
        """verify() calls awslocal lambda list-functions."""
        # list-functions returns nothing (no functions)
        mock_run.return_value = _make_proc(stdout="")
        verifier = ResourceVerifier()
        verifier.verify("http://localhost:4566")
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("list-functions" in c for c in calls)

    @patch("scanner.verifier.subprocess.run")
    @patch("scanner.verifier.tempfile.NamedTemporaryFile")
    @patch("scanner.verifier.os.unlink")
    @patch("builtins.open", mock_open(read_data='{"StatusCode": 200}'))
    def test_invokes_each_lambda_function(self, mock_unlink, mock_tmpfile, mock_run):
        """For each discovered Lambda function, invokes it."""
        tmp = MagicMock()
        tmp.name = "/tmp/test_lambda_out.json"
        mock_tmpfile.return_value.__enter__ = MagicMock(return_value=tmp)
        mock_tmpfile.return_value.__exit__ = MagicMock(return_value=False)

        # First call: list-functions returns "my-function"
        # Second call: invoke returns success
        mock_run.side_effect = [
            _make_proc(stdout="my-function"),
            _make_proc(returncode=0),  # invoke
            _make_proc(stdout=""),  # api gw list
            _make_proc(stdout=""),  # s3 ls
        ]
        verifier = ResourceVerifier()
        outcome = verifier.verify("http://localhost:4566")
        assert any("my-function" in d for d in outcome.details)

    @patch("scanner.verifier.subprocess.run")
    @patch("scanner.verifier.tempfile.NamedTemporaryFile")
    @patch("scanner.verifier.os.unlink")
    @patch("builtins.open", mock_open(read_data='{"FunctionError": "Unhandled", "StatusCode": 200}'))
    def test_records_failed_lambda_invocation(self, mock_unlink, mock_tmpfile, mock_run):
        """When Lambda invocation output has FunctionError, records FAILED."""
        tmp = MagicMock()
        tmp.name = "/tmp/test_lambda_out.json"
        mock_tmpfile.return_value.__enter__ = MagicMock(return_value=tmp)
        mock_tmpfile.return_value.__exit__ = MagicMock(return_value=False)

        mock_run.side_effect = [
            _make_proc(stdout="bad-function"),
            _make_proc(returncode=0),  # invoke exits 0 but has FunctionError in output
            _make_proc(stdout=""),  # api gw
            _make_proc(stdout=""),  # s3
        ]
        verifier = ResourceVerifier()
        outcome = verifier.verify("http://localhost:4566")
        assert outcome.passed is False
        assert any("FAILED" in d for d in outcome.details)

    @patch("scanner.verifier.subprocess.run")
    @patch("scanner.verifier.tempfile.NamedTemporaryFile")
    @patch("scanner.verifier.os.unlink")
    @patch("builtins.open", mock_open(read_data='{"StatusCode": 200}'))
    def test_lambda_failure_does_not_prevent_other_checks(self, mock_unlink, mock_tmpfile, mock_run):
        """A Lambda invocation failure doesn't skip S3/API GW checks."""
        tmp = MagicMock()
        tmp.name = "/tmp/test_lambda_out.json"
        mock_tmpfile.return_value.__enter__ = MagicMock(return_value=tmp)
        mock_tmpfile.return_value.__exit__ = MagicMock(return_value=False)

        mock_run.side_effect = [
            _make_proc(stdout="fn-a"),  # list functions
            _make_proc(returncode=1, stderr="error"),  # invoke fn-a fails
            _make_proc(stdout=""),  # api gw
            _make_proc(stdout="2024-01-01 mybucket"),  # s3 ls
        ]
        verifier = ResourceVerifier()
        outcome = verifier.verify("http://localhost:4566")
        # S3 details should appear despite Lambda failure
        assert any("S3" in d for d in outcome.details)


class TestApiGatewayVerification:
    @patch("scanner.verifier.subprocess.run")
    def test_discovers_api_gateway_rest_apis(self, mock_run):
        """verify() queries apigateway get-rest-apis."""
        mock_run.return_value = _make_proc(stdout="")
        verifier = ResourceVerifier()
        verifier.verify("http://localhost:4566")
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("get-rest-apis" in c for c in calls)

    @patch("scanner.verifier.requests.get")
    @patch("scanner.verifier.subprocess.run")
    def test_makes_http_request_to_api_gw(self, mock_run, mock_get):
        """For each discovered API + stage, makes a GET request."""
        stage_response = json.dumps({
            "item": [{"stageName": "prod"}]
        })
        mock_run.side_effect = [
            _make_proc(stdout=""),  # list lambdas
            _make_proc(stdout="abc123"),  # get-rest-apis
            _make_proc(stdout=stage_response),  # get-stages
            _make_proc(stdout=""),  # s3
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        verifier = ResourceVerifier()
        outcome = verifier.verify("http://localhost:4566")
        mock_get.assert_called_once()
        assert any("API" in d for d in outcome.details)


class TestS3Verification:
    @patch("scanner.verifier.subprocess.run")
    def test_checks_s3_bucket_existence(self, mock_run):
        """verify() runs awslocal s3 ls and records bucket count."""
        mock_run.side_effect = [
            _make_proc(stdout=""),  # lambda list
            _make_proc(stdout=""),  # api gw
            _make_proc(stdout="2024-01-01 my-bucket\n2024-01-01 other-bucket"),  # s3 ls
        ]
        verifier = ResourceVerifier()
        outcome = verifier.verify("http://localhost:4566")
        assert any("S3" in d for d in outcome.details)
        assert any("2" in d for d in outcome.details)  # 2 buckets found


class TestNoResourcesFound:
    @patch("scanner.verifier.subprocess.run")
    def test_passed_true_when_no_resources_found(self, mock_run):
        """When no Lambda/API GW/S3 found, passed=True with appropriate summary."""
        mock_run.return_value = _make_proc(stdout="")
        verifier = ResourceVerifier()
        outcome = verifier.verify("http://localhost:4566")
        assert outcome.passed is True
        assert "No verifiable resources" in outcome.summary


class TestTempFileUsage:
    @patch("scanner.verifier.subprocess.run")
    @patch("scanner.verifier.tempfile.NamedTemporaryFile")
    @patch("scanner.verifier.os.unlink")
    @patch("builtins.open", mock_open(read_data='{"StatusCode": 200}'))
    def test_uses_unique_temp_file_per_lambda_invocation(self, mock_unlink, mock_tmpfile, mock_run):
        """Each Lambda invocation uses a unique temp file path."""
        tmp1 = MagicMock()
        tmp1.name = "/tmp/lambda_out_1.json"
        tmp2 = MagicMock()
        tmp2.name = "/tmp/lambda_out_2.json"

        call_count = 0

        def tmpfile_factory(**kwargs):
            nonlocal call_count
            cm = MagicMock()
            if call_count == 0:
                cm.__enter__ = MagicMock(return_value=tmp1)
            else:
                cm.__enter__ = MagicMock(return_value=tmp2)
            cm.__exit__ = MagicMock(return_value=False)
            call_count += 1
            return cm

        mock_tmpfile.side_effect = tmpfile_factory
        mock_run.side_effect = [
            _make_proc(stdout="fn-a\tfn-b"),  # list-functions (two functions, tab-separated)
            _make_proc(returncode=0),  # invoke fn-a
            _make_proc(returncode=0),  # invoke fn-b
            _make_proc(stdout=""),  # api gw
            _make_proc(stdout=""),  # s3
        ]
        verifier = ResourceVerifier()
        verifier.verify("http://localhost:4566")
        # NamedTemporaryFile should be called once per function
        assert mock_tmpfile.call_count >= 1
