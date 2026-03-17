"""Tests for priority-based sample sorting."""
from __future__ import annotations

from datetime import UTC, datetime

from scanner.config import CloudProvider, IaCType
from scanner.models import Sample
from scanner.priority import sort_samples_by_priority


def _make_sample(name: str, iac_type: IaCType, updated_at: datetime | None = None) -> Sample:
    return Sample(
        name=name,
        org="test-org",
        url=f"https://github.com/test-org/{name}",
        iac_type=iac_type,
        cloud_provider=CloudProvider.AWS,
        description="",
        topics=[],
        language="HCL",
        default_branch="main",
        updated_at=updated_at or datetime(2024, 1, 1, tzinfo=UTC),
    )


DEFAULT_PRIORITY = [
    IaCType.TERRAFORM,
    IaCType.AZURE_BICEP,
    IaCType.CDK,
    IaCType.SAM,
    IaCType.CLOUDFORMATION,
    IaCType.PULUMI,
    IaCType.SERVERLESS,
    IaCType.AZURE_ARM,
]


class TestSortSamplesByPriority:
    def test_terraform_sorted_first(self):
        samples = [
            _make_sample("cdk-app", IaCType.CDK),
            _make_sample("tf-app", IaCType.TERRAFORM),
            _make_sample("cfn-app", IaCType.CLOUDFORMATION),
        ]
        result = sort_samples_by_priority(samples, DEFAULT_PRIORITY)
        assert result[0].iac_type == IaCType.TERRAFORM

    def test_full_default_priority_order(self):
        samples = [
            _make_sample("arm-app", IaCType.AZURE_ARM),
            _make_sample("sls-app", IaCType.SERVERLESS),
            _make_sample("pulumi-app", IaCType.PULUMI),
            _make_sample("cfn-app", IaCType.CLOUDFORMATION),
            _make_sample("sam-app", IaCType.SAM),
            _make_sample("cdk-app", IaCType.CDK),
            _make_sample("bicep-app", IaCType.AZURE_BICEP),
            _make_sample("tf-app", IaCType.TERRAFORM),
        ]
        result = sort_samples_by_priority(samples, DEFAULT_PRIORITY)
        types = [s.iac_type for s in result]
        assert types == [
            IaCType.TERRAFORM,
            IaCType.AZURE_BICEP,
            IaCType.CDK,
            IaCType.SAM,
            IaCType.CLOUDFORMATION,
            IaCType.PULUMI,
            IaCType.SERVERLESS,
            IaCType.AZURE_ARM,
        ]

    def test_sam_before_cloudformation(self):
        """SAM must sort before CloudFormation to prevent misclassification."""
        samples = [
            _make_sample("cfn-app", IaCType.CLOUDFORMATION),
            _make_sample("sam-app", IaCType.SAM),
        ]
        result = sort_samples_by_priority(samples, DEFAULT_PRIORITY)
        assert result[0].iac_type == IaCType.SAM
        assert result[1].iac_type == IaCType.CLOUDFORMATION

    def test_iac_types_not_in_priority_sort_last(self):
        samples = [
            _make_sample("unknown-app", IaCType.UNKNOWN),
            _make_sample("tf-app", IaCType.TERRAFORM),
        ]
        result = sort_samples_by_priority(samples, DEFAULT_PRIORITY)
        assert result[0].iac_type == IaCType.TERRAFORM
        assert result[1].iac_type == IaCType.UNKNOWN

    def test_stable_sort_preserves_order_within_same_type(self):
        """Samples of the same type must remain in their original relative order."""
        t1 = datetime(2024, 3, 1, tzinfo=UTC)
        t2 = datetime(2024, 2, 1, tzinfo=UTC)
        t3 = datetime(2024, 1, 1, tzinfo=UTC)
        samples = [
            _make_sample("tf-a", IaCType.TERRAFORM, t1),
            _make_sample("tf-b", IaCType.TERRAFORM, t2),
            _make_sample("tf-c", IaCType.TERRAFORM, t3),
        ]
        result = sort_samples_by_priority(samples, DEFAULT_PRIORITY)
        assert [s.name for s in result] == ["tf-a", "tf-b", "tf-c"]

    def test_empty_samples_returns_empty(self):
        result = sort_samples_by_priority([], DEFAULT_PRIORITY)
        assert result == []

    def test_empty_priority_sorts_all_types_last(self):
        samples = [_make_sample("tf-app", IaCType.TERRAFORM)]
        result = sort_samples_by_priority(samples, [])
        assert len(result) == 1

    def test_custom_priority_order_respected(self):
        """User can reverse priority — Azure Bicep first."""
        custom_priority = [IaCType.AZURE_BICEP, IaCType.TERRAFORM]
        samples = [
            _make_sample("tf-app", IaCType.TERRAFORM),
            _make_sample("bicep-app", IaCType.AZURE_BICEP),
        ]
        result = sort_samples_by_priority(samples, custom_priority)
        assert result[0].iac_type == IaCType.AZURE_BICEP
        assert result[1].iac_type == IaCType.TERRAFORM

    def test_multiple_samples_per_type_stable(self):
        samples = [
            _make_sample("cdk-1", IaCType.CDK),
            _make_sample("tf-1", IaCType.TERRAFORM),
            _make_sample("cdk-2", IaCType.CDK),
            _make_sample("tf-2", IaCType.TERRAFORM),
        ]
        result = sort_samples_by_priority(samples, DEFAULT_PRIORITY)
        names = [s.name for s in result]
        assert names == ["tf-1", "tf-2", "cdk-1", "cdk-2"]


class TestConfigScanPriority:
    def test_config_has_scan_priority_field(self):
        from scanner.config import Config
        cfg = Config()
        assert hasattr(cfg, "scan_priority")
        assert isinstance(cfg.scan_priority, list)
        assert len(cfg.scan_priority) > 0

    def test_default_scan_priority_starts_with_terraform(self):
        from scanner.config import Config
        cfg = Config()
        assert cfg.scan_priority[0] == IaCType.TERRAFORM

    def test_default_priority_sam_before_cloudformation(self):
        from scanner.config import Config
        cfg = Config()
        sam_idx = cfg.scan_priority.index(IaCType.SAM)
        cfn_idx = cfg.scan_priority.index(IaCType.CLOUDFORMATION)
        assert sam_idx < cfn_idx, "SAM must come before CloudFormation to prevent misclassification"

    def test_config_has_cache_ttl_hours(self):
        from scanner.config import Config
        cfg = Config()
        assert hasattr(cfg, "cache_ttl_hours")
        assert cfg.cache_ttl_hours == 24

    def test_config_to_dict_includes_scan_priority(self):
        from scanner.config import Config
        cfg = Config()
        d = cfg.to_dict()
        assert "scan_priority" in d
        assert isinstance(d["scan_priority"], list)
        assert d["scan_priority"][0] == "TERRAFORM"

    def test_config_to_dict_includes_cache_ttl_hours(self):
        from scanner.config import Config
        cfg = Config()
        d = cfg.to_dict()
        assert "cache_ttl_hours" in d
        assert d["cache_ttl_hours"] == 24
