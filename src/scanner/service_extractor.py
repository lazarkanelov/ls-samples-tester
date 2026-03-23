"""AWS service extractor — parses IaC files to identify services used."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from scanner.config import IaCType

logger = logging.getLogger(__name__)

# Maps Terraform resource type prefix → display name.
# Uses longest-prefix matching: "aws_api_gateway" wins over "aws_api".
_TF_PREFIX_MAP: dict[str, str] = {
    "aws_lambda": "Lambda",
    "aws_s3": "S3",
    "aws_dynamodb": "DynamoDB",
    "aws_sqs": "SQS",
    "aws_sns": "SNS",
    "aws_iam": "IAM",
    "aws_api_gateway": "API Gateway",
    "aws_apigatewayv2": "API Gateway",
    "aws_cloudwatch": "CloudWatch",
    "aws_logs": "CloudWatch Logs",
    "aws_kinesis": "Kinesis",
    "aws_kms": "KMS",
    "aws_secretsmanager": "Secrets Manager",
    "aws_ssm": "SSM",
    "aws_ecs": "ECS",
    "aws_eks": "EKS",
    "aws_ec2": "EC2",
    "aws_rds": "RDS",
    "aws_elasticache": "ElastiCache",
    "aws_elb": "Elastic Load Balancing",
    "aws_alb": "Elastic Load Balancing",
    "aws_lb": "Elastic Load Balancing",
    "aws_autoscaling": "Auto Scaling",
    "aws_cloudfront": "CloudFront",
    "aws_route53": "Route 53",
    "aws_ses": "SES",
    "aws_cognito": "Cognito",
    "aws_opensearch": "OpenSearch",
    "aws_elasticsearch": "Elasticsearch",
    "aws_glue": "Glue",
    "aws_athena": "Athena",
    "aws_redshift": "Redshift",
    "aws_emr": "EMR",
    "aws_batch": "Batch",
    "aws_sfn": "Step Functions",
    "aws_step_functions": "Step Functions",
    "aws_codecommit": "CodeCommit",
    "aws_codebuild": "CodeBuild",
    "aws_codepipeline": "CodePipeline",
    "aws_codedeploy": "CodeDeploy",
    "aws_ecr": "ECR",
    "aws_msk": "MSK",
    "aws_mq": "Amazon MQ",
    "aws_waf": "WAF",
    "aws_wafv2": "WAF",
    "aws_cloudtrail": "CloudTrail",
    "aws_config": "Config",
    "aws_xray": "X-Ray",
    "aws_backup": "Backup",
    "aws_transfer": "Transfer Family",
    "aws_dax": "DynamoDB Accelerator",
    "aws_neptune": "Neptune",
    "aws_docdb": "DocumentDB",
    "aws_timestream": "Timestream",
    "aws_qldb": "QLDB",
    "aws_iot": "IoT",
    "aws_pinpoint": "Pinpoint",
    "aws_efs": "EFS",
    "aws_acm": "ACM",
    "aws_firehose": "Kinesis Firehose",
    "aws_cloudformation": "CloudFormation",
    "aws_bedrock": "Bedrock",
    "aws_eventbridge": "EventBridge",
}

# Maps CDK module name (normalised with underscores) → display name.
_CDK_MODULE_MAP: dict[str, str] = {
    "aws_lambda": "Lambda",
    "aws_s3": "S3",
    "aws_dynamodb": "DynamoDB",
    "aws_sqs": "SQS",
    "aws_sns": "SNS",
    "aws_iam": "IAM",
    "aws_apigateway": "API Gateway",
    "aws_apigatewayv2": "API Gateway",
    "aws_cloudwatch": "CloudWatch",
    "aws_logs": "CloudWatch Logs",
    "aws_kinesis": "Kinesis",
    "aws_kms": "KMS",
    "aws_secretsmanager": "Secrets Manager",
    "aws_ssm": "SSM",
    "aws_ecs": "ECS",
    "aws_eks": "EKS",
    "aws_ec2": "EC2",
    "aws_rds": "RDS",
    "aws_elasticache": "ElastiCache",
    "aws_elasticloadbalancingv2": "Elastic Load Balancing",
    "aws_autoscaling": "Auto Scaling",
    "aws_cloudfront": "CloudFront",
    "aws_route53": "Route 53",
    "aws_ses": "SES",
    "aws_cognito": "Cognito",
    "aws_opensearchservice": "OpenSearch",
    "aws_elasticsearch": "Elasticsearch",
    "aws_glue": "Glue",
    "aws_athena": "Athena",
    "aws_redshift": "Redshift",
    "aws_emr": "EMR",
    "aws_batch": "Batch",
    "aws_stepfunctions": "Step Functions",
    "aws_codecommit": "CodeCommit",
    "aws_codebuild": "CodeBuild",
    "aws_codepipeline": "CodePipeline",
    "aws_codedeploy": "CodeDeploy",
    "aws_ecr": "ECR",
    "aws_msk": "MSK",
    "aws_waf": "WAF",
    "aws_wafv2": "WAF",
    "aws_cloudtrail": "CloudTrail",
    "aws_xray": "X-Ray",
    "aws_backup": "Backup",
    "aws_neptune": "Neptune",
    "aws_docdb": "DocumentDB",
    "aws_iot": "IoT",
    "aws_efs": "EFS",
    "aws_certificatemanager": "ACM",
    "aws_kinesis_firehose": "Kinesis Firehose",
    "aws_events": "EventBridge",
    "aws_bedrock": "Bedrock",
}

# Maps CloudFormation/SAM service segment (from AWS::<Service>::<Resource>) → display name.
_CFN_SERVICE_MAP: dict[str, str] = {
    "Lambda": "Lambda",
    "S3": "S3",
    "DynamoDB": "DynamoDB",
    "SQS": "SQS",
    "SNS": "SNS",
    "IAM": "IAM",
    "ApiGateway": "API Gateway",
    "ApiGatewayV2": "API Gateway",
    "CloudWatch": "CloudWatch",
    "Logs": "CloudWatch Logs",
    "Kinesis": "Kinesis",
    "KinesisFirehose": "Kinesis Firehose",
    "KMS": "KMS",
    "SecretsManager": "Secrets Manager",
    "SSM": "SSM",
    "ECS": "ECS",
    "EKS": "EKS",
    "EC2": "EC2",
    "RDS": "RDS",
    "ElastiCache": "ElastiCache",
    "ElasticLoadBalancingV2": "Elastic Load Balancing",
    "AutoScaling": "Auto Scaling",
    "CloudFront": "CloudFront",
    "Route53": "Route 53",
    "SES": "SES",
    "Cognito": "Cognito",
    "OpenSearchService": "OpenSearch",
    "Elasticsearch": "Elasticsearch",
    "Glue": "Glue",
    "Athena": "Athena",
    "Redshift": "Redshift",
    "EMR": "EMR",
    "Batch": "Batch",
    "StepFunctions": "Step Functions",
    "CodeCommit": "CodeCommit",
    "CodeBuild": "CodeBuild",
    "CodePipeline": "CodePipeline",
    "CodeDeploy": "CodeDeploy",
    "ECR": "ECR",
    "MSK": "MSK",
    "WAF": "WAF",
    "WAFv2": "WAF",
    "CloudTrail": "CloudTrail",
    "Config": "Config",
    "XRay": "X-Ray",
    "Backup": "Backup",
    "Transfer": "Transfer Family",
    "Neptune": "Neptune",
    "DocDB": "DocumentDB",
    "IoT": "IoT",
    "EFS": "EFS",
    "CertificateManager": "ACM",
    "Events": "EventBridge",
    "Serverless": "Serverless",
    "Bedrock": "Bedrock",
}

# Terraform resource type regex
_TF_RESOURCE_RE = re.compile(r'resource\s+"(aws_[a-z0-9_]+)"', re.MULTILINE)

# CDK Python import patterns
_CDK_PY_IMPORT1_RE = re.compile(r"from\s+aws_cdk\s+import\s+([a-z0-9_,\s]+)", re.MULTILINE)
_CDK_PY_IMPORT2_RE = re.compile(r"from\s+aws_cdk\.(aws_[a-z0-9_]+)", re.MULTILINE)
_CDK_PY_MODULE_RE = re.compile(r"\b(aws_[a-z0-9_]+)\b")

# CDK TypeScript import patterns
_CDK_TS_NEW_RE = re.compile(r"['\"]aws-cdk-lib/(aws-[a-z0-9-]+)['\"]")
_CDK_TS_OLD_RE = re.compile(r"['\"]@aws-cdk/(aws-[a-z0-9-]+)['\"]")

# CloudFormation/SAM type patterns
_CFN_YAML_TYPE_RE = re.compile(r"Type:\s*AWS::([A-Za-z0-9]+)::[A-Za-z0-9]+")
_CFN_JSON_TYPE_RE = re.compile(r'"Type"\s*:\s*"AWS::([A-Za-z0-9]+)::[A-Za-z0-9]+"')


def _tf_prefix_to_service(resource_type: str) -> str | None:
    """Longest-prefix match for Terraform resource type → service name."""
    best_key: str | None = None
    for key in _TF_PREFIX_MAP:
        if resource_type == key or resource_type.startswith(key + "_"):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    if best_key:
        return _TF_PREFIX_MAP[best_key]
    logger.debug("Unrecognized Terraform resource prefix: %s", resource_type)
    return None


def _cdk_module_to_service(module_name: str) -> str | None:
    """Map a CDK module name (hyphens or underscores) to a display name."""
    normalised = module_name.replace("-", "_")
    service = _CDK_MODULE_MAP.get(normalised)
    if service is None:
        logger.debug("Unrecognized CDK module: %s", module_name)
    return service


class ServiceExtractor:
    """Extracts AWS service names from IaC source files without deploying."""

    def extract(self, sample_dir: Path, iac_type: IaCType) -> list[str]:
        """Return a sorted, deduplicated list of AWS service display names."""
        if not sample_dir.exists():
            return []
        try:
            if iac_type == IaCType.TERRAFORM:
                services = self._from_terraform(sample_dir)
            elif iac_type == IaCType.CDK:
                services = self._from_cdk(sample_dir)
            elif iac_type in (IaCType.CLOUDFORMATION, IaCType.SAM):
                services = self._from_cfn(sample_dir)
            else:
                return []
            return sorted(services)
        except Exception as exc:  # pragma: no cover
            logger.debug("ServiceExtractor failed for %s: %s", sample_dir, exc)
            return []

    # ------------------------------------------------------------------
    # Terraform
    # ------------------------------------------------------------------

    def _from_terraform(self, sample_dir: Path) -> set[str]:
        services: set[str] = set()
        for tf_file in sample_dir.rglob("*.tf"):
            try:
                text = tf_file.read_text(errors="replace")
            except OSError:
                continue
            for m in _TF_RESOURCE_RE.finditer(text):
                service = _tf_prefix_to_service(m.group(1))
                if service:
                    services.add(service)
        return services

    # ------------------------------------------------------------------
    # CDK (Python + TypeScript)
    # ------------------------------------------------------------------

    def _from_cdk(self, sample_dir: Path) -> set[str]:
        services: set[str] = set()
        for py_file in sample_dir.rglob("*.py"):
            try:
                services.update(self._parse_cdk_python(py_file.read_text(errors="replace")))
            except OSError:
                continue
        for ts_file in sample_dir.rglob("*.ts"):
            try:
                services.update(self._parse_cdk_typescript(ts_file.read_text(errors="replace")))
            except OSError:
                continue
        return services

    def _parse_cdk_python(self, text: str) -> set[str]:
        services: set[str] = set()
        # from aws_cdk import aws_lambda, aws_s3
        for m in _CDK_PY_IMPORT1_RE.finditer(text):
            for part in _CDK_PY_MODULE_RE.finditer(m.group(1)):
                module = part.group(1)
                if module.startswith("aws_"):
                    svc = _cdk_module_to_service(module)
                    if svc:
                        services.add(svc)
        # from aws_cdk.aws_lambda import ...
        for m in _CDK_PY_IMPORT2_RE.finditer(text):
            svc = _cdk_module_to_service(m.group(1))
            if svc:
                services.add(svc)
        return services

    def _parse_cdk_typescript(self, text: str) -> set[str]:
        services: set[str] = set()
        for pattern in (_CDK_TS_NEW_RE, _CDK_TS_OLD_RE):
            for m in pattern.finditer(text):
                svc = _cdk_module_to_service(m.group(1))
                if svc:
                    services.add(svc)
        return services

    # ------------------------------------------------------------------
    # CloudFormation / SAM
    # ------------------------------------------------------------------

    def _from_cfn(self, sample_dir: Path) -> set[str]:
        services: set[str] = set()
        for tmpl_name in ("template.yaml", "template.yml", "template.json"):
            path = sample_dir / tmpl_name
            if not path.exists():
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            pattern = _CFN_JSON_TYPE_RE if tmpl_name.endswith(".json") else _CFN_YAML_TYPE_RE
            for m in pattern.finditer(text):
                svc = _CFN_SERVICE_MAP.get(m.group(1))
                if svc:
                    services.add(svc)
        return services
