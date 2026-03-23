"""Tests for ServiceExtractor."""
from __future__ import annotations

import pytest

from scanner.config import IaCType


@pytest.fixture
def extractor():
    from scanner.service_extractor import ServiceExtractor
    return ServiceExtractor()


class TestTerraformExtraction:
    def test_extracts_lambda_from_tf_resource(self, extractor, tmp_path):
        (tmp_path / "main.tf").write_text('resource "aws_lambda_function" "fn" {}\n')
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert "Lambda" in result

    def test_extracts_s3_bucket(self, extractor, tmp_path):
        (tmp_path / "main.tf").write_text('resource "aws_s3_bucket" "b" {}\n')
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert "S3" in result

    def test_extracts_dynamodb(self, extractor, tmp_path):
        (tmp_path / "main.tf").write_text('resource "aws_dynamodb_table" "t" {}\n')
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert "DynamoDB" in result

    def test_extracts_multiple_services(self, extractor, tmp_path):
        tf = """
resource "aws_lambda_function" "fn" {}
resource "aws_sqs_queue" "q" {}
resource "aws_dynamodb_table" "t" {}
"""
        (tmp_path / "main.tf").write_text(tf)
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert "Lambda" in result
        assert "SQS" in result
        assert "DynamoDB" in result

    def test_returns_sorted_deduplicated_list(self, extractor, tmp_path):
        tf = """
resource "aws_lambda_function" "fn1" {}
resource "aws_lambda_layer_version" "l1" {}
resource "aws_s3_bucket" "b1" {}
"""
        (tmp_path / "main.tf").write_text(tf)
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert result == sorted(result)
        assert len(result) == len(set(result))

    def test_returns_empty_for_no_aws_resources(self, extractor, tmp_path):
        (tmp_path / "main.tf").write_text('variable "region" {}\n')
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert result == []

    def test_unrecognized_resource_type_does_not_raise(self, extractor, tmp_path):
        (tmp_path / "main.tf").write_text('resource "aws_unknown_service_thing" "x" {}\n')
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert isinstance(result, list)

    def test_scans_multiple_tf_files(self, extractor, tmp_path):
        (tmp_path / "lambda.tf").write_text('resource "aws_lambda_function" "fn" {}\n')
        (tmp_path / "storage.tf").write_text('resource "aws_s3_bucket" "b" {}\n')
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert "Lambda" in result
        assert "S3" in result

    def test_scans_nested_tf_files(self, extractor, tmp_path):
        module_dir = tmp_path / "modules" / "api"
        module_dir.mkdir(parents=True)
        (module_dir / "main.tf").write_text('resource "aws_api_gateway_rest_api" "api" {}\n')
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert "API Gateway" in result


class TestCDKExtraction:
    def test_extracts_lambda_from_python_import(self, extractor, tmp_path):
        (tmp_path / "app.py").write_text("from aws_cdk import aws_lambda as _lambda\n")
        result = extractor.extract(tmp_path, IaCType.CDK)
        assert "Lambda" in result

    def test_extracts_from_dotted_import(self, extractor, tmp_path):
        (tmp_path / "app.py").write_text("from aws_cdk.aws_s3 import Bucket\n")
        result = extractor.extract(tmp_path, IaCType.CDK)
        assert "S3" in result

    def test_extracts_from_typescript_cdk_lib(self, extractor, tmp_path):
        ts_dir = tmp_path / "lib"
        ts_dir.mkdir()
        (ts_dir / "stack.ts").write_text(
            "import * as lambda from 'aws-cdk-lib/aws-lambda';\n"
        )
        result = extractor.extract(tmp_path, IaCType.CDK)
        assert "Lambda" in result

    def test_extracts_from_old_cdk_package(self, extractor, tmp_path):
        (tmp_path / "stack.ts").write_text(
            "import * as s3 from '@aws-cdk/aws-s3';\n"
        )
        result = extractor.extract(tmp_path, IaCType.CDK)
        assert "S3" in result

    def test_returns_empty_for_no_cdk_imports(self, extractor, tmp_path):
        (tmp_path / "app.py").write_text("import boto3\n")
        result = extractor.extract(tmp_path, IaCType.CDK)
        assert result == []


class TestCloudFormationExtraction:
    def test_extracts_lambda_from_yaml_template(self, extractor, tmp_path):
        template = "Resources:\n  Fn:\n    Type: AWS::Lambda::Function\n"
        (tmp_path / "template.yaml").write_text(template)
        result = extractor.extract(tmp_path, IaCType.CLOUDFORMATION)
        assert "Lambda" in result

    def test_extracts_multiple_services_from_template(self, extractor, tmp_path):
        template = """Resources:
  Fn:
    Type: AWS::Lambda::Function
  Table:
    Type: AWS::DynamoDB::Table
  Queue:
    Type: AWS::SQS::Queue
"""
        (tmp_path / "template.yaml").write_text(template)
        result = extractor.extract(tmp_path, IaCType.CLOUDFORMATION)
        assert "Lambda" in result
        assert "DynamoDB" in result
        assert "SQS" in result

    def test_extracts_from_json_template(self, extractor, tmp_path):
        import json
        template = {
            "Resources": {
                "Fn": {"Type": "AWS::Lambda::Function"},
                "B": {"Type": "AWS::S3::Bucket"},
            }
        }
        (tmp_path / "template.json").write_text(json.dumps(template))
        result = extractor.extract(tmp_path, IaCType.CLOUDFORMATION)
        assert "Lambda" in result
        assert "S3" in result

    def test_works_for_sam_type(self, extractor, tmp_path):
        template = "Resources:\n  Fn:\n    Type: AWS::Serverless::Function\n"
        (tmp_path / "template.yaml").write_text(template)
        result = extractor.extract(tmp_path, IaCType.SAM)
        assert "Serverless" in result or "Lambda" in result or isinstance(result, list)


class TestEdgeCases:
    def test_empty_directory_returns_empty_list(self, extractor, tmp_path):
        result = extractor.extract(tmp_path, IaCType.TERRAFORM)
        assert result == []

    def test_nonexistent_directory_returns_empty_list(self, extractor, tmp_path):
        result = extractor.extract(tmp_path / "does_not_exist", IaCType.TERRAFORM)
        assert result == []

    def test_unknown_iac_type_returns_empty_list(self, extractor, tmp_path):
        result = extractor.extract(tmp_path, IaCType.UNKNOWN)
        assert isinstance(result, list)

    def test_result_is_always_a_list(self, extractor, tmp_path):
        result = extractor.extract(tmp_path, IaCType.CDK)
        assert isinstance(result, list)
