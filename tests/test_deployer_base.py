"""Tests for deployer base class and factory."""
from __future__ import annotations

from pathlib import Path

from scanner.config import IaCType
from scanner.models import DeployStatus


class TestDeployerFactory:
    def test_factory_returns_cdk_deployer(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.cdk import CdkDeployer
        deployer = get_deployer(IaCType.CDK)
        assert isinstance(deployer, CdkDeployer)

    def test_factory_returns_sam_deployer(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.sam import SamDeployer
        deployer = get_deployer(IaCType.SAM)
        assert isinstance(deployer, SamDeployer)

    def test_factory_returns_cloudformation_deployer(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.cloudformation import CloudFormationDeployer
        deployer = get_deployer(IaCType.CLOUDFORMATION)
        assert isinstance(deployer, CloudFormationDeployer)

    def test_factory_returns_terraform_deployer(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.terraform import TerraformDeployer
        deployer = get_deployer(IaCType.TERRAFORM)
        assert isinstance(deployer, TerraformDeployer)

    def test_factory_returns_pulumi_deployer(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.pulumi import PulumiDeployer
        deployer = get_deployer(IaCType.PULUMI)
        assert isinstance(deployer, PulumiDeployer)

    def test_factory_returns_serverless_deployer(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.serverless import ServerlessDeployer
        deployer = get_deployer(IaCType.SERVERLESS)
        assert isinstance(deployer, ServerlessDeployer)

    def test_factory_returns_azure_deployer_for_arm(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.azure import AzureDeployer
        deployer = get_deployer(IaCType.AZURE_ARM)
        assert isinstance(deployer, AzureDeployer)

    def test_factory_returns_azure_deployer_for_bicep(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.azure import AzureDeployer
        deployer = get_deployer(IaCType.AZURE_BICEP)
        assert isinstance(deployer, AzureDeployer)

    def test_factory_returns_azure_deployer_for_unknown(self):
        from scanner.deployer import get_deployer
        from scanner.deployer.azure import AzureDeployer
        deployer = get_deployer(IaCType.UNKNOWN)
        assert isinstance(deployer, AzureDeployer)


class TestBaseDeployer:
    def test_base_bootstrap_returns_true(self):
        from scanner.deployer.base import Deployer
        # Concrete subclass for testing
        class ConcreteDeployer(Deployer):
            def prepare(self, sample_dir):
                return True
            def deploy(self, sample_dir, timeout):
                from scanner.models import DeployResult
                return DeployResult("t","o",DeployStatus.SUCCESS,0.0,"","",None,[],""  )
            def cleanup(self, sample_dir):
                pass
        d = ConcreteDeployer()
        success, error = d.bootstrap(timeout=30)
        assert success is True
        assert error == ""

    def test_base_detect_services_returns_list(self):
        from scanner.deployer.base import Deployer
        class ConcreteDeployer(Deployer):
            def prepare(self, sample_dir): return True
            def deploy(self, sample_dir, timeout):
                from scanner.models import DeployResult
                return DeployResult("t","o",DeployStatus.SUCCESS,0.0,"","",None,[],""  )
            def cleanup(self, sample_dir): pass
        d = ConcreteDeployer()
        result = d.detect_services(Path("/tmp"))
        assert isinstance(result, list)
