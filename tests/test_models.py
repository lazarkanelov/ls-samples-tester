"""Tests for scanner data models."""
import json
from datetime import UTC, datetime

from scanner.models import (
    CloudProvider,
    DeployResult,
    DeployStatus,
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
