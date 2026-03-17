"""Tests for scanner configuration."""
from scanner.config import Config, IaCType


def test_config_loads_with_defaults():
    config = Config()
    assert config.localstack_endpoint == "http://localhost:4566"
    assert config.per_sample_timeout == 600
    assert config.data_retention_weeks == 12
    assert config.max_repos_per_org == 500
    assert len(config.target_orgs) > 0


def test_iac_marker_map_contains_all_types():
    config = Config()
    markers = config.iac_markers
    expected_types = {
        IaCType.CDK,
        IaCType.SAM,
        IaCType.CLOUDFORMATION,
        IaCType.TERRAFORM,
        IaCType.PULUMI,
        IaCType.SERVERLESS,
        IaCType.AZURE_ARM,
        IaCType.AZURE_BICEP,
    }
    assert set(markers.keys()) == expected_types


def test_max_repos_per_org_defaults_to_500():
    config = Config()
    assert config.max_repos_per_org == 500


def test_config_serializable_to_dict():
    config = Config()
    d = config.to_dict()
    assert isinstance(d, dict)
    assert "localstack_endpoint" in d
    assert "max_repos_per_org" in d
    assert d["max_repos_per_org"] == 500


def test_target_orgs_includes_aws_and_azure():
    config = Config()
    orgs_str = " ".join(config.target_orgs)
    assert "aws-samples" in orgs_str
    assert "Azure-Samples" in orgs_str


def test_config_custom_values():
    config = Config(max_repos_per_org=100, per_sample_timeout=300)
    assert config.max_repos_per_org == 100
    assert config.per_sample_timeout == 300
