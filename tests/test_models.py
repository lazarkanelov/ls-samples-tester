"""Tests for scanner data models."""
import json
from datetime import UTC, datetime

from scanner.models import (
    CloudProvider,
    DeployResult,
    DeployStatus,
    FailureCategory,
    IaCType,
    Sample,
    ScanReport,
)


def test_deploy_status_has_all_five_values():
    statuses = {s.value for s in DeployStatus}
    assert "SUCCESS" in statuses
    assert "FAILURE" in statuses
    assert "TIMEOUT" in statuses
    assert "SKIPPED" in statuses
    assert "UNSUPPORTED" in statuses


def test_iac_type_has_all_types():
    types = {t.value for t in IaCType}
    assert "CDK" in types
    assert "SAM" in types
    assert "CLOUDFORMATION" in types
    assert "TERRAFORM" in types
    assert "PULUMI" in types
    assert "SERVERLESS" in types
    assert "AZURE_ARM" in types
    assert "AZURE_BICEP" in types
    assert "UNKNOWN" in types


def test_sample_creation():
    sample = Sample(
        name="my-cdk-app",
        org="aws-samples",
        url="https://github.com/aws-samples/my-cdk-app",
        iac_type=IaCType.CDK,
        cloud_provider=CloudProvider.AWS,
        description="A sample CDK app",
        topics=["cdk", "aws"],
        language="TypeScript",
        default_branch="main",
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    assert sample.name == "my-cdk-app"
    assert sample.org == "aws-samples"
    assert sample.iac_type == IaCType.CDK
    assert sample.cloud_provider == CloudProvider.AWS


def test_sample_serialization_round_trips():
    sample = Sample(
        name="test-repo",
        org="aws-samples",
        url="https://github.com/aws-samples/test-repo",
        iac_type=IaCType.TERRAFORM,
        cloud_provider=CloudProvider.AWS,
        description="Test",
        topics=[],
        language="HCL",
        default_branch="main",
        updated_at=datetime(2024, 6, 15, tzinfo=UTC),
    )
    data = sample.to_dict()
    assert isinstance(data, dict)
    assert data["name"] == "test-repo"
    assert data["iac_type"] == "TERRAFORM"
    assert data["cloud_provider"] == "AWS"

    # Round-trip via JSON
    json_str = json.dumps(data)
    parsed = json.loads(json_str)
    restored = Sample.from_dict(parsed)
    assert restored.name == sample.name
    assert restored.iac_type == sample.iac_type


def test_deploy_result_creation():
    result = DeployResult(
        sample_name="test-repo",
        org="aws-samples",
        status=DeployStatus.SUCCESS,
        duration=45.2,
        stdout="Deployment complete",
        stderr="",
        error_message=None,
        services_used=["S3", "Lambda"],
        deployer_command="cdklocal deploy --all",
    )
    assert result.status == DeployStatus.SUCCESS
    assert result.duration == 45.2
    assert "S3" in result.services_used


def test_deploy_result_serialization():
    result = DeployResult(
        sample_name="test-repo",
        org="aws-samples",
        status=DeployStatus.FAILURE,
        duration=12.0,
        stdout="",
        stderr="Error: service not found",
        error_message="service not found",
        services_used=[],
        deployer_command="tflocal apply",
    )
    data = result.to_dict()
    assert data["status"] == "FAILURE"
    assert data["error_message"] == "service not found"

    restored = DeployResult.from_dict(data)
    assert restored.status == DeployStatus.FAILURE


def test_failure_category_has_all_values():
    values = {c.value for c in FailureCategory}
    assert "LOCALSTACK_BUG" in values
    assert "DEPLOYER_ERROR" in values
    assert "SAMPLE_ERROR" in values
    assert "TIMEOUT" in values
    assert "NOT_CLASSIFIED" in values


def test_deploy_result_failure_category_defaults_to_none():
    result = DeployResult(
        sample_name="test",
        org="aws-samples",
        status=DeployStatus.FAILURE,
        duration=5.0,
        stdout="",
        stderr="error",
        error_message="error",
        services_used=[],
        deployer_command="tflocal apply",
    )
    assert result.failure_category is None


def test_deploy_result_failure_category_serialization():
    result = DeployResult(
        sample_name="test",
        org="aws-samples",
        status=DeployStatus.FAILURE,
        duration=5.0,
        stdout="",
        stderr="not yet implemented",
        error_message="not yet implemented",
        services_used=[],
        deployer_command="tflocal apply",
        failure_category=FailureCategory.LOCALSTACK_BUG,
    )
    data = result.to_dict()
    assert data["failure_category"] == "LOCALSTACK_BUG"

    restored = DeployResult.from_dict(data)
    assert restored.failure_category == FailureCategory.LOCALSTACK_BUG


def test_deploy_result_from_dict_without_failure_category():
    """Old JSON without failure_category loads without error."""
    data = {
        "sample_name": "test",
        "org": "aws-samples",
        "status": "FAILURE",
        "duration": 5.0,
        "stdout": "",
        "stderr": "error",
        "error_message": "error",
        "services_used": [],
        "deployer_command": "tflocal apply",
    }
    result = DeployResult.from_dict(data)
    assert result.failure_category is None


def test_deploy_result_failure_category_none_serializes_to_null():
    result = DeployResult(
        sample_name="test",
        org="aws-samples",
        status=DeployStatus.SUCCESS,
        duration=5.0,
        stdout="ok",
        stderr="",
        error_message=None,
        services_used=[],
        deployer_command="tflocal apply",
        failure_category=None,
    )
    data = result.to_dict()
    assert data["failure_category"] is None


def test_scan_report_category_counts():
    results = [
        DeployResult(
            sample_name="a",
            org="org",
            status=DeployStatus.FAILURE,
            duration=1.0,
            stdout="",
            stderr="",
            error_message="",
            services_used=[],
            deployer_command="",
            failure_category=FailureCategory.LOCALSTACK_BUG,
        ),
        DeployResult(
            sample_name="b",
            org="org",
            status=DeployStatus.FAILURE,
            duration=1.0,
            stdout="",
            stderr="",
            error_message="",
            services_used=[],
            deployer_command="",
            failure_category=FailureCategory.DEPLOYER_ERROR,
        ),
        DeployResult(
            sample_name="c",
            org="org",
            status=DeployStatus.SUCCESS,
            duration=1.0,
            stdout="",
            stderr="",
            error_message=None,
            services_used=[],
            deployer_command="",
            failure_category=None,
        ),
        DeployResult(
            sample_name="d",
            org="org",
            status=DeployStatus.FAILURE,
            duration=1.0,
            stdout="",
            stderr="",
            error_message="",
            services_used=[],
            deployer_command="",
            failure_category=FailureCategory.LOCALSTACK_BUG,
        ),
    ]
    report = ScanReport(results=results, scan_date="2024-01-01", total_samples=4)
    counts = report.category_counts
    assert counts["LOCALSTACK_BUG"] == 2
    assert counts["DEPLOYER_ERROR"] == 1
    assert "NOT_CLASSIFIED" not in counts or counts.get("NOT_CLASSIFIED", 0) == 0


def test_deploy_status_has_partial():
    """PARTIAL status exists in DeployStatus."""
    assert hasattr(DeployStatus, "PARTIAL")
    assert DeployStatus.PARTIAL.value == "PARTIAL"


def test_deploy_result_has_verification_fields():
    """DeployResult has verification_status and verification_details fields."""
    result = DeployResult(
        sample_name="test",
        org="aws-samples",
        status=DeployStatus.SUCCESS,
        duration=5.0,
        stdout="ok",
        stderr="",
        error_message=None,
        services_used=[],
        deployer_command="cdklocal deploy",
    )
    assert result.verification_status is None
    assert result.verification_details is None


def test_deploy_result_verification_fields_serialize():
    """verification_status and verification_details round-trip through to_dict/from_dict."""
    result = DeployResult(
        sample_name="test",
        org="aws-samples",
        status=DeployStatus.PARTIAL,
        duration=5.0,
        stdout="ok",
        stderr="",
        error_message=None,
        services_used=[],
        deployer_command="cdklocal deploy",
        verification_status="FAILED",
        verification_details="Lambda my-fn: FAILED (Function error)",
    )
    data = result.to_dict()
    assert data["verification_status"] == "FAILED"
    assert data["verification_details"] == "Lambda my-fn: FAILED (Function error)"

    restored = DeployResult.from_dict(data)
    assert restored.status == DeployStatus.PARTIAL
    assert restored.verification_status == "FAILED"
    assert restored.verification_details == "Lambda my-fn: FAILED (Function error)"


def test_deploy_result_from_dict_without_verification_fields():
    """Old JSON without verification fields loads without error."""
    data = {
        "sample_name": "test",
        "org": "aws-samples",
        "status": "SUCCESS",
        "duration": 5.0,
        "stdout": "ok",
        "stderr": "",
        "error_message": None,
        "services_used": [],
        "deployer_command": "cdklocal deploy",
    }
    result = DeployResult.from_dict(data)
    assert result.verification_status is None
    assert result.verification_details is None


def test_scan_report_partial_count():
    """ScanReport.partial_count returns the count of PARTIAL results."""
    results = [
        DeployResult(
            sample_name="a", org="o", status=DeployStatus.SUCCESS,
            duration=1.0, stdout="", stderr="", error_message=None,
            services_used=[], deployer_command="",
        ),
        DeployResult(
            sample_name="b", org="o", status=DeployStatus.PARTIAL,
            duration=1.0, stdout="", stderr="", error_message=None,
            services_used=[], deployer_command="",
        ),
        DeployResult(
            sample_name="c", org="o", status=DeployStatus.PARTIAL,
            duration=1.0, stdout="", stderr="", error_message=None,
            services_used=[], deployer_command="",
        ),
    ]
    report = ScanReport(results=results, scan_date="2024-01-01", total_samples=3)
    assert report.partial_count == 2


def test_scan_report_to_dict_includes_partial_in_summary():
    """ScanReport.to_dict() summary block includes 'partial' key."""
    result = DeployResult(
        sample_name="a", org="o", status=DeployStatus.PARTIAL,
        duration=1.0, stdout="", stderr="", error_message=None,
        services_used=[], deployer_command="",
    )
    report = ScanReport(results=[result], scan_date="2024-01-01", total_samples=1)
    data = report.to_dict()
    assert "partial" in data["summary"]
    assert data["summary"]["partial"] == 1


def test_scan_report_creation():
    results = [
        DeployResult(
            sample_name="app-a",
            org="aws-samples",
            status=DeployStatus.SUCCESS,
            duration=30.0,
            stdout="ok",
            stderr="",
            error_message=None,
            services_used=["S3"],
            deployer_command="cdklocal deploy",
        ),
        DeployResult(
            sample_name="app-b",
            org="aws-samples",
            status=DeployStatus.FAILURE,
            duration=10.0,
            stdout="",
            stderr="Error",
            error_message="Error",
            services_used=[],
            deployer_command="tflocal apply",
        ),
    ]
    report = ScanReport(
        results=results,
        scan_date="2024-01-15",
        total_samples=2,
        tool_versions={"cdklocal": "2.0.0"},
    )
    assert report.total_samples == 2
    assert len(report.results) == 2
    data = report.to_dict()
    assert data["total_samples"] == 2
    assert len(data["results"]) == 2
