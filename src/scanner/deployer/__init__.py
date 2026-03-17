"""Deployer package — IaC deployer factory."""
from __future__ import annotations

from scanner.config import IaCType
from scanner.deployer.base import Deployer


def get_deployer(iac_type: IaCType) -> Deployer:
    """Return the appropriate deployer for the given IaC type."""
    if iac_type == IaCType.CDK:
        from scanner.deployer.cdk import CdkDeployer

        return CdkDeployer()
    if iac_type == IaCType.SAM:
        from scanner.deployer.sam import SamDeployer

        return SamDeployer()
    if iac_type == IaCType.CLOUDFORMATION:
        from scanner.deployer.cloudformation import CloudFormationDeployer

        return CloudFormationDeployer()
    if iac_type == IaCType.TERRAFORM:
        from scanner.deployer.terraform import TerraformDeployer

        return TerraformDeployer()
    if iac_type == IaCType.PULUMI:
        from scanner.deployer.pulumi import PulumiDeployer

        return PulumiDeployer()
    if iac_type == IaCType.SERVERLESS:
        from scanner.deployer.serverless import ServerlessDeployer

        return ServerlessDeployer()
    # AZURE_ARM, AZURE_BICEP, UNKNOWN → AzureDeployer
    from scanner.deployer.azure import AzureDeployer

    return AzureDeployer()
