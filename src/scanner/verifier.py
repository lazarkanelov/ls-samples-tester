"""Resource verifier — discovers and smoke-tests deployed AWS resources via awslocal."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

_AWS_ENV = {
    **os.environ,
    "AWS_DEFAULT_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "test",
    "AWS_SECRET_ACCESS_KEY": "test",
}


@dataclass
class VerifyOutcome:
    """Result of resource verification."""

    passed: bool
    summary: str
    details: list[str] = field(default_factory=list)


class ResourceVerifier:
    """Discovers deployed AWS resources via awslocal and smoke-tests them."""

    def verify(self, ls_endpoint: str, timeout: int = 120) -> VerifyOutcome:
        """Discover and test Lambda, API GW, and S3 resources.

        Returns SKIPPED if awslocal is not available.
        Returns passed=True if no verifiable resources found.
        Returns passed=False if any resource test fails.
        """
        details: list[str] = []
        any_failed = False
        any_found = False

        try:
            lambda_details, lambda_failed, lambda_found = self._verify_lambdas(timeout)
        except FileNotFoundError:
            return VerifyOutcome(
                passed=True,
                summary="Verification SKIPPED — awslocal not available",
                details=[],
            )

        details.extend(lambda_details)
        if lambda_failed:
            any_failed = True
        if lambda_found:
            any_found = True

        apigw_details, apigw_failed, apigw_found = self._verify_api_gateway(ls_endpoint, timeout)
        details.extend(apigw_details)
        if apigw_failed:
            any_failed = True
        if apigw_found:
            any_found = True

        s3_details, s3_found = self._verify_s3(timeout)
        details.extend(s3_details)
        if s3_found:
            any_found = True

        if not any_found:
            return VerifyOutcome(
                passed=True,
                summary="No verifiable resources found (Lambda/API GW/S3)",
                details=details,
            )

        passed = not any_failed
        summary = "All resources passed verification" if passed else "Some resources failed verification"
        return VerifyOutcome(passed=passed, summary=summary, details=details)

    def _verify_lambdas(self, timeout: int) -> tuple[list[str], bool, bool]:
        """Discover and invoke Lambda functions. Returns (details, any_failed, any_found)."""
        details: list[str] = []
        any_failed = False
        any_found = False

        result = subprocess.run(
            ["awslocal", "lambda", "list-functions",
             "--region", "us-east-1",
             "--query", "Functions[].FunctionName",
             "--output", "text"],
            capture_output=True,
            text=True,
            env=_AWS_ENV,
            timeout=timeout,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return details, any_failed, any_found

        # Output is tab-separated function names on one line
        function_names = [n.strip() for n in result.stdout.split() if n.strip()]
        for name in function_names:
            any_found = True
            detail, failed = self._invoke_lambda(name, timeout)
            details.append(detail)
            if failed:
                any_failed = True

        return details, any_failed, any_found

    def _invoke_lambda(self, name: str, timeout: int) -> tuple[str, bool]:
        """Invoke a single Lambda function. Returns (detail_message, failed)."""
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_path = tmp.name

            result = subprocess.run(
                ["awslocal", "lambda", "invoke",
                 "--function-name", name,
                 "--region", "us-east-1",
                 "--payload", "{}",
                 tmp_path],
                capture_output=True,
                text=True,
                env=_AWS_ENV,
                timeout=timeout,
            )

            if result.returncode != 0:
                return f"Lambda {name}: FAILED (exit {result.returncode})", True

            # Read output file and check for FunctionError
            try:
                with open(tmp_path) as f:
                    output = json.load(f)
                if "FunctionError" in output:
                    error_type = output.get("FunctionError", "Unknown")
                    return f"Lambda {name}: FAILED ({error_type})", True
                return f"Lambda {name}: OK", False
            except (json.JSONDecodeError, OSError):
                return f"Lambda {name}: OK (output unreadable)", False
        except subprocess.TimeoutExpired:
            return f"Lambda {name}: FAILED (timeout)", True
        except Exception as exc:
            return f"Lambda {name}: FAILED ({exc})", True
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _verify_api_gateway(self, ls_endpoint: str, timeout: int) -> tuple[list[str], bool, bool]:
        """Discover REST API GW endpoints and make test requests. Returns (details, any_failed, any_found)."""
        details: list[str] = []
        any_failed = False
        any_found = False

        try:
            result = subprocess.run(
                ["awslocal", "apigateway", "get-rest-apis",
                 "--region", "us-east-1",
                 "--query", "items[].id",
                 "--output", "text"],
                capture_output=True,
                text=True,
                env=_AWS_ENV,
                timeout=timeout,
            )
        except FileNotFoundError:
            return details, any_failed, any_found

        if result.returncode != 0 or not result.stdout.strip():
            return details, any_failed, any_found

        api_ids = [i.strip() for i in result.stdout.split() if i.strip()]
        for api_id in api_ids:
            stage_details, stage_failed, stage_found = self._test_api_stages(
                api_id, ls_endpoint, timeout
            )
            details.extend(stage_details)
            if stage_failed:
                any_failed = True
            if stage_found:
                any_found = True

        return details, any_failed, any_found

    def _test_api_stages(
        self, api_id: str, ls_endpoint: str, timeout: int
    ) -> tuple[list[str], bool, bool]:
        """Test all stages for a given API GW REST API. Returns (details, any_failed, any_found)."""
        details: list[str] = []
        any_failed = False
        any_found = False

        try:
            result = subprocess.run(
                ["awslocal", "apigateway", "get-stages",
                 "--rest-api-id", api_id,
                 "--region", "us-east-1"],
                capture_output=True,
                text=True,
                env=_AWS_ENV,
                timeout=timeout,
            )
        except Exception:
            return details, any_failed, any_found

        try:
            stages_data = json.loads(result.stdout)
            stage_names = [s["stageName"] for s in stages_data.get("item", [])]
        except (json.JSONDecodeError, KeyError):
            return details, any_failed, any_found

        base = ls_endpoint.rstrip("/")
        for stage in stage_names:
            any_found = True
            url = f"{base}/restapis/{api_id}/{stage}/_user_request_/"
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code >= 500:
                    details.append(f"API GW {api_id}/{stage}: FAILED (HTTP {resp.status_code})")
                    any_failed = True
                else:
                    details.append(f"API GW {api_id}/{stage}: OK (HTTP {resp.status_code})")
            except Exception as exc:
                details.append(f"API GW {api_id}/{stage}: FAILED ({exc})")
                any_failed = True

        return details, any_failed, any_found

    def _verify_s3(self, timeout: int) -> tuple[list[str], bool]:
        """List S3 buckets. Returns (details, any_found)."""
        details: list[str] = []

        try:
            result = subprocess.run(
                ["awslocal", "s3", "ls", "--region", "us-east-1"],
                capture_output=True,
                text=True,
                env=_AWS_ENV,
                timeout=timeout,
            )
        except FileNotFoundError:
            return details, False

        if result.returncode != 0 or not result.stdout.strip():
            return details, False

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        bucket_count = len(lines)
        details.append(f"S3: {bucket_count} bucket(s) found")
        return details, True
