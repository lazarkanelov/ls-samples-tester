"""Scanner configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IaCType(str, Enum):
    CDK = "CDK"
    SAM = "SAM"
    CLOUDFORMATION = "CLOUDFORMATION"
    TERRAFORM = "TERRAFORM"
    PULUMI = "PULUMI"
    SERVERLESS = "SERVERLESS"
    AZURE_ARM = "AZURE_ARM"
    AZURE_BICEP = "AZURE_BICEP"
    UNKNOWN = "UNKNOWN"


class CloudProvider(str, Enum):
    AWS = "AWS"
    AZURE = "AZURE"


# Map IaC type → cloud provider
IAC_CLOUD_MAP: dict[IaCType, CloudProvider] = {
    IaCType.CDK: CloudProvider.AWS,
    IaCType.SAM: CloudProvider.AWS,
    IaCType.CLOUDFORMATION: CloudProvider.AWS,
    IaCType.TERRAFORM: CloudProvider.AWS,
    IaCType.PULUMI: CloudProvider.AWS,
    IaCType.SERVERLESS: CloudProvider.AWS,
    IaCType.AZURE_ARM: CloudProvider.AZURE,
    IaCType.AZURE_BICEP: CloudProvider.AZURE,
    IaCType.UNKNOWN: CloudProvider.AWS,
}


@dataclass
class Config:
    """Global scanner configuration."""

    # LocalStack
    localstack_endpoint: str = "http://localhost:4566"
    localstack_image: str = "localstack/localstack-pro:latest"
    localstack_container_name: str = "scanner-localstack"

    # GitHub
    target_orgs: list[str] = field(
        default_factory=lambda: [
            "aws-samples",
            "awsdocs",
            "aws-cloudformation",
            "Azure-Samples",
        ]
    )
    max_repos_per_org: int = 500

    # Timeouts (seconds)
    per_sample_timeout: int = 600
    overall_scan_timeout: int = 18000  # 5 hours
    localstack_ready_timeout: int = 120
    localstack_reset_timeout: int = 10
    verification_timeout: int = 120

    # Retry
    max_retries: int = 2
    retry_delay: int = 10

    # Adaptive timeouts
    per_sample_timeout_min: int = 120
    per_sample_timeout_max: int = 1200
    durations_path: str = "data/durations.json"

    # Verification
    enable_verification: bool = True

    # Data
    data_retention_weeks: int = 12
    registry_path: str = "data/registry.json"
    results_dir: str = "data/results"
    trends_path: str = "data/trends.json"
    reports_dir: str = "reports"

    # Discovery: IaC type scan order for priority-based orchestration.
    # SAM must come before CLOUDFORMATION — SAM repos contain both samconfig.toml
    # and template.yaml; if CFN runs first, SAM repos are misclassified.
    scan_priority: list[IaCType] = field(
        default_factory=lambda: [
            IaCType.TERRAFORM,
            IaCType.AZURE_BICEP,
            IaCType.CDK,
            IaCType.SAM,
            IaCType.CLOUDFORMATION,
            IaCType.PULUMI,
            IaCType.SERVERLESS,
            IaCType.AZURE_ARM,
        ]
    )

    # TTL for the local search-result cache (hours). After this period, results
    # are considered stale and the GitHub Code Search API is re-queried.
    cache_ttl_hours: int = 24
    cache_path: str = "data/etag_cache.json"

    # IaC file markers for file-tree-only detection
    # Value: set of filename patterns that indicate this IaC type
    iac_markers: dict[IaCType, list[str]] = field(
        default_factory=lambda: {
            IaCType.CDK: ["cdk.json"],
            # SAM requires template.yaml/yml AND samconfig markers
            IaCType.SAM: ["samconfig.toml", "samconfig.yaml"],
            IaCType.CLOUDFORMATION: [
                "template.yaml",
                "template.yml",
                "template.json",
            ],
            IaCType.TERRAFORM: [".tf"],  # suffix match
            IaCType.PULUMI: ["Pulumi.yaml", "Pulumi.yml"],
            IaCType.SERVERLESS: ["serverless.yml", "serverless.yaml"],
            IaCType.AZURE_ARM: ["azuredeploy.json"],
            IaCType.AZURE_BICEP: [".bicep"],  # suffix match
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "localstack_endpoint": self.localstack_endpoint,
            "localstack_image": self.localstack_image,
            "target_orgs": self.target_orgs,
            "max_repos_per_org": self.max_repos_per_org,
            "per_sample_timeout": self.per_sample_timeout,
            "overall_scan_timeout": self.overall_scan_timeout,
            "data_retention_weeks": self.data_retention_weeks,
            "registry_path": self.registry_path,
            "results_dir": self.results_dir,
            "trends_path": self.trends_path,
            "reports_dir": self.reports_dir,
            "scan_priority": [t.value for t in self.scan_priority],
            "cache_ttl_hours": self.cache_ttl_hours,
            "cache_path": self.cache_path,
        }
