#!/usr/bin/env python3
"""Generate review-only ShareBite IAM/bootstrap artifacts; never mutates AWS or GitHub."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REGION = "ap-south-1"
REPOSITORY = "bharathselvas/sharebite"
STACK_NAME = "smart-food-demo"
DEFAULT_PLAN_DIRECTORY = ".sharebite-bootstrap-plan"


def _policy(statements: list[dict]) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": statements,
    }


def _statement(sid: str, actions: list[str], resource, **extra) -> dict:
    return {
        "Sid": sid,
        "Effect": "Allow",
        "Action": actions,
        "Resource": resource,
        **extra,
    }


def _role_arn(account_id: str, name: str) -> str:
    return f"arn:aws:iam::{account_id}:role/{name}"


def _trusted_web_identity(account_id: str, environment: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "GitHubActionsOnlyForExactRepositoryEnvironment",
                "Effect": "Allow",
                "Principal": {
                    "Federated": (
                        f"arn:aws:iam::{account_id}:oidc-provider/"
                        "token.actions.githubusercontent.com"
                    )
                },
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                        "token.actions.githubusercontent.com:sub": (
                            f"repo:{REPOSITORY}:environment:{environment}"
                        ),
                    }
                },
            }
        ],
    }


def _cloudformation_trust(account_id: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudFormationForShareBiteStackOnly",
                "Effect": "Allow",
                "Principal": {"Service": "cloudformation.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:aws:cloudformation:{REGION}:{account_id}:"
                            f"stack/{STACK_NAME}/*"
                        )
                    },
                },
            }
        ],
    }


def _required_role_trust(account_id: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "LambdaServiceOnly",
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }


def _cloudformation_execution_policy(
    account_id: str,
    artifact_bucket: str,
    boundary_policy_name: str,
) -> dict:
    table_arn = (
        f"arn:aws:dynamodb:{REGION}:{account_id}:table/{STACK_NAME}-donations"
    )
    bucket_arns = [
        f"arn:aws:s3:::sharebite-{account_id}-{REGION}-frontend",
        f"arn:aws:s3:::sharebite-{account_id}-{REGION}-analytics",
    ]
    runtime_roles = [
        _role_arn(account_id, f"{STACK_NAME}-lambda-role"),
        _role_arn(account_id, f"{STACK_NAME}-etl-role"),
    ]
    function_arns = [
        f"arn:aws:lambda:{REGION}:{account_id}:function:{STACK_NAME}-api",
        f"arn:aws:lambda:{REGION}:{account_id}:function:{STACK_NAME}-etl",
    ]
    user_pool_arn = f"arn:aws:cognito-idp:{REGION}:{account_id}:userpool/*"
    api_gateway_arn = f"arn:aws:apigateway:{REGION}::/apis/*"
    distribution_arn = f"arn:aws:cloudfront::{account_id}:distribution/*"
    origin_access_control_arn = (
        f"arn:aws:cloudfront::{account_id}:origin-access-control/*"
    )
    log_group_arn = (
        f"arn:aws:logs:{REGION}:{account_id}:"
        f"log-group:/aws/lambda/{STACK_NAME}-*"
    )
    boundary_arn = f"arn:aws:iam::{account_id}:policy/{boundary_policy_name}"

    return _policy(
        [
            _statement(
                "ReadPackagedSamArtifacts",
                ["s3:GetObject"],
                f"arn:aws:s3:::{artifact_bucket}/sharebite/artifacts/*",
            ),
            _statement(
                "ManageShareBiteDonationTable",
                [
                    "dynamodb:CreateTable",
                    "dynamodb:DeleteTable",
                    "dynamodb:DescribeTable",
                    "dynamodb:ListTagsOfResource",
                    "dynamodb:TagResource",
                    "dynamodb:UntagResource",
                    "dynamodb:UpdateTable",
                ],
                table_arn,
            ),
            _statement(
                "CreateCognitoUserPool",
                ["cognito-idp:CreateUserPool"],
                "*",
            ),
            _statement(
                "ManageShareBiteUserPoolResources",
                [
                    "cognito-idp:CreateGroup",
                    "cognito-idp:CreateUserPoolClient",
                    "cognito-idp:CreateUserPoolDomain",
                    "cognito-idp:DeleteGroup",
                    "cognito-idp:DeleteUserPool",
                    "cognito-idp:DeleteUserPoolClient",
                    "cognito-idp:DeleteUserPoolDomain",
                    "cognito-idp:DescribeUserPool",
                    "cognito-idp:DescribeUserPoolClient",
                    "cognito-idp:GetGroup",
                    "cognito-idp:ListTagsForResource",
                    "cognito-idp:TagResource",
                    "cognito-idp:UntagResource",
                    "cognito-idp:UpdateGroup",
                    "cognito-idp:UpdateUserPool",
                    "cognito-idp:UpdateUserPoolClient",
                ],
                user_pool_arn,
            ),
            _statement(
                "DescribeCognitoManagedLoginDomain",
                ["cognito-idp:DescribeUserPoolDomain"],
                "*",
            ),
            _statement(
                "ManageShareBiteHttpApi",
                [
                    "apigateway:DELETE",
                    "apigateway:GET",
                    "apigateway:PATCH",
                    "apigateway:POST",
                ],
                [f"arn:aws:apigateway:{REGION}::/apis", api_gateway_arn],
            ),
            _statement(
                "CreateCloudFrontResources",
                ["cloudfront:CreateDistribution", "cloudfront:CreateOriginAccessControl"],
                "*",
            ),
            _statement(
                "ManageShareBiteCloudFrontDistribution",
                [
                    "cloudfront:DeleteDistribution",
                    "cloudfront:GetDistribution",
                    "cloudfront:GetDistributionConfig",
                    "cloudfront:ListTagsForResource",
                    "cloudfront:TagResource",
                    "cloudfront:UntagResource",
                    "cloudfront:UpdateDistribution",
                ],
                distribution_arn,
            ),
            _statement(
                "ManageShareBiteOriginAccessControl",
                [
                    "cloudfront:DeleteOriginAccessControl",
                    "cloudfront:GetOriginAccessControl",
                    "cloudfront:ListTagsForResource",
                    "cloudfront:TagResource",
                    "cloudfront:UntagResource",
                    "cloudfront:UpdateOriginAccessControl",
                ],
                origin_access_control_arn,
            ),
            _statement(
                "ManageShareBiteLambdaFunctions",
                [
                    "lambda:CreateFunction",
                    "lambda:DeleteFunction",
                    "lambda:GetFunction",
                    "lambda:GetFunctionConfiguration",
                    "lambda:GetPolicy",
                    "lambda:RemovePermission",
                    "lambda:TagResource",
                    "lambda:UntagResource",
                    "lambda:UpdateFunctionCode",
                    "lambda:UpdateFunctionConfiguration",
                ],
                function_arns,
            ),
            _statement(
                "ManageShareBiteApiLambdaPermissions",
                [
                    "lambda:AddPermission",
                ],
                function_arns,
                Condition={
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": (
                            f"arn:aws:execute-api:{REGION}:{account_id}:"
                            "*/*/*/api/*"
                        )
                    },
                },
            ),
            _statement(
                "ManageOnlyShareBiteLambdaRoles",
                [
                    "iam:DeleteRole",
                    "iam:DeleteRolePolicy",
                    "iam:GetRole",
                    "iam:ListRolePolicies",
                    "iam:PutRolePolicy",
                    "iam:TagRole",
                    "iam:UntagRole",
                ],
                runtime_roles,
            ),
            _statement(
                "CreateShareBiteLambdaRolesWithApprovedBoundary",
                ["iam:CreateRole", "iam:PutRolePermissionsBoundary"],
                runtime_roles,
                Condition={"StringEquals": {"iam:PermissionsBoundary": boundary_arn}},
            ),
            _statement(
                "PassOnlyShareBiteRuntimeRolesToLambda",
                ["iam:PassRole"],
                runtime_roles,
                Condition={
                    "StringEquals": {"iam:PassedToService": "lambda.amazonaws.com"}
                },
            ),
            _statement(
                "ManageShareBiteLambdaLogGroups",
                [
                    "logs:CreateLogGroup",
                    "logs:DeleteLogGroup",
                    "logs:ListTagsForResource",
                    "logs:PutRetentionPolicy",
                    "logs:TagResource",
                    "logs:UntagResource",
                ],
                log_group_arn,
            ),
            _statement(
                "CreateAndConfigureShareBiteBuckets",
                [
                    "s3:CreateBucket",
                    "s3:DeleteBucket",
                    "s3:DeleteBucketPolicy",
                    "s3:GetBucketLocation",
                    "s3:GetBucketPolicy",
                    "s3:GetBucketPolicyStatus",
                    "s3:GetBucketPublicAccessBlock",
                    "s3:GetBucketOwnershipControls",
                    "s3:GetBucketTagging",
                    "s3:GetEncryptionConfiguration",
                    "s3:GetLifecycleConfiguration",
                    "s3:PutBucketPolicy",
                    "s3:PutBucketPublicAccessBlock",
                    "s3:PutBucketOwnershipControls",
                    "s3:PutBucketTagging",
                    "s3:PutEncryptionConfiguration",
                    "s3:PutLifecycleConfiguration",
                ],
                bucket_arns,
            ),
        ]
    )


def build_artifacts(
    account_id: str,
    artifact_bucket: str,
    *,
    deploy_role_name: str,
    review_role_name: str,
    execution_role_name: str,
    boundary_policy_name: str,
    template_text: str,
    workflow_text: str,
) -> dict[str, dict | str]:
    if not re.fullmatch(r"\d{12}", account_id):
        raise ValueError("Account ID must be exactly 12 digits.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", artifact_bucket):
        raise ValueError("Artifact bucket name is not valid S3 DNS syntax.")
    for role_name in (deploy_role_name, review_role_name, execution_role_name, boundary_policy_name):
        if not re.fullmatch(r"[A-Za-z0-9+=,.@_-]{1,64}", role_name):
            raise ValueError(f"Invalid proposed IAM role or policy name: {role_name!r}.")

    account_stack_arn = (
        f"arn:aws:cloudformation:{REGION}:{account_id}:stack/{STACK_NAME}/*"
    )
    change_set_arn = (
        f"arn:aws:cloudformation:{REGION}:{account_id}:"
        f"changeSet/{STACK_NAME}-*/*"
    )
    artifact_arn = f"arn:aws:s3:::{artifact_bucket}"
    artifact_objects = f"{artifact_arn}/sharebite/artifacts/*"
    frontend_bucket = f"sharebite-{account_id}-{REGION}-frontend"
    frontend_arn = f"arn:aws:s3:::{frontend_bucket}"
    frontend_objects = f"{frontend_arn}/*"
    table_arn = f"arn:aws:dynamodb:{REGION}:{account_id}:table/{STACK_NAME}-donations"
    analytics_arn = f"arn:aws:s3:::sharebite-{account_id}-{REGION}-analytics"
    api_log_arn = (
        f"arn:aws:logs:{REGION}:{account_id}:"
        f"log-group:/aws/lambda/{STACK_NAME}-api:*"
    )
    etl_log_arn = (
        f"arn:aws:logs:{REGION}:{account_id}:"
        f"log-group:/aws/lambda/{STACK_NAME}-etl:*"
    )

    deploy_policy = _policy(
        [
            _statement(
                "InspectTargetAccount",
                ["sts:GetCallerIdentity"],
                "*",
            ),
            _statement(
                "CreateAndTagShareBiteChangeSets",
                ["cloudformation:CreateChangeSet", "cloudformation:TagResource"],
                account_stack_arn,
            ),
            _statement(
                "InspectAndExecuteShareBiteChangeSets",
                ["cloudformation:DescribeChangeSet", "cloudformation:ExecuteChangeSet"],
                change_set_arn,
            ),
            _statement(
                "InspectAndProtectShareBiteStack",
                [
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStacks",
                    "cloudformation:ListStackResources",
                    "cloudformation:UpdateTerminationProtection",
                ],
                account_stack_arn,
            ),
            _statement(
                "PassOnlyShareBiteCloudFormationExecutionRole",
                ["iam:PassRole"],
                _role_arn(account_id, execution_role_name),
                Condition={
                    "StringEquals": {
                        "iam:PassedToService": "cloudformation.amazonaws.com"
                    }
                },
            ),
            _statement(
                "InspectArtifactBucket",
                [
                    "s3:GetEncryptionConfiguration",
                    "s3:GetBucketLocation",
                    "s3:GetBucketOwnershipControls",
                    "s3:GetBucketPublicAccessBlock",
                ],
                artifact_arn,
            ),
            _statement(
                "ListArtifactPrefix",
                ["s3:ListBucket"],
                artifact_arn,
                Condition={
                    "StringLike": {
                        "s3:prefix": ["sharebite/artifacts", "sharebite/artifacts/*"]
                    }
                },
            ),
            _statement(
                "WritePackagedArtifactsOnly",
                ["s3:AbortMultipartUpload", "s3:ListMultipartUploadParts", "s3:PutObject"],
                artifact_objects,
            ),
            _statement(
                "ListFrontendAssets",
                ["s3:GetBucketLocation", "s3:ListBucket"],
                frontend_arn,
            ),
            _statement(
                "UploadAndCompareFrontendAssets",
                ["s3:AbortMultipartUpload", "s3:GetObject", "s3:ListMultipartUploadParts", "s3:PutObject"],
                frontend_objects,
            ),
            _statement(
                "InvalidateShareBiteDistribution",
                ["cloudfront:CreateInvalidation"],
                f"arn:aws:cloudfront::{account_id}:distribution/*",
            ),
        ]
    )
    review_policy = _policy(
        [
            _statement(
                "ReadShareBiteChangeSetsOnly",
                ["cloudformation:DescribeChangeSet"],
                change_set_arn,
            ),
            _statement(
                "ReadShareBiteStackOnly",
                [
                    "cloudformation:DescribeStackEvents",
                    "cloudformation:DescribeStacks",
                    "cloudformation:ListStackResources",
                ],
                account_stack_arn,
            ),
        ]
    )

    app_runtime_policy = _policy(
        [
            _statement(
                "AccessDonationRecords",
                [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                ],
                table_arn,
            ),
            _statement(
                "QueryDonationIndexes",
                ["dynamodb:Query"],
                f"{table_arn}/index/*",
            ),
            _statement(
                "WriteApiFunctionLogs",
                ["logs:CreateLogStream", "logs:PutLogEvents"],
                api_log_arn,
            ),
        ]
    )
    etl_runtime_policy = _policy(
        [
            _statement("ScanDonationRecords", ["dynamodb:Scan"], table_arn),
            _statement(
                "WriteETLReportsOnly",
                ["s3:PutObject"],
                f"{analytics_arn}/etl/*",
            ),
            _statement(
                "WriteETLFunctionLogs",
                ["logs:CreateLogStream", "logs:PutLogEvents"],
                etl_log_arn,
            ),
        ]
    )
    runtime_boundary = _policy(
        [
            {
                **statement,
                "Condition": {
                    "ArnEquals": {
                        "aws:PrincipalArn": _role_arn(
                            account_id, f"{STACK_NAME}-lambda-role"
                        )
                    }
                },
            }
            for statement in app_runtime_policy["Statement"]
        ]
        + [
            {
                **statement,
                "Condition": {
                    "ArnEquals": {
                        "aws:PrincipalArn": _role_arn(
                            account_id, f"{STACK_NAME}-etl-role"
                        )
                    }
                },
            }
            for statement in etl_runtime_policy["Statement"]
        ]
    )
    cloudformation_execution_policy = _cloudformation_execution_policy(
        account_id,
        artifact_bucket,
        boundary_policy_name,
    )

    resources_match = re.search(
        r"(?ms)^Resources:\n(.*?)(?=^Outputs:\n|\Z)",
        template_text,
    )
    if resources_match is None:
        raise ValueError("Could not find a Resources section in template.yaml.")
    resource_inventory = [
        {"logical_id": logical_id, "declared_type": resource_type}
        for logical_id, resource_type in re.findall(
            r"(?m)^  ([A-Za-z][A-Za-z0-9]+):\n    Type: ([A-Za-z0-9:]+)$",
            resources_match.group(1),
        )
    ]
    if not resource_inventory:
        raise ValueError("Could not extract CloudFormation resources from template.yaml.")

    unresolved = [
        "The generated CloudFormation execution policy is a constrained draft, not an AWS-validated or approved policy. Validate every action/resource combination with IAM Access Analyzer and a non-production change set in the target account before attaching it.",
        "The CloudFormation execution policy uses exact fixed resource names where possible. Cognito user-pool and CloudFront identifiers are generated, while API Gateway ARNs omit the account ID. Resource '*' is limited to create/domain-description actions whose target is not yet addressable; trust remains scoped to the account and ShareBite stack.",
        "The execution-role draft includes exact-name delete actions for failed-stack rollback. These remain destructive capabilities and must be reviewed together with DeletionPolicy/UpdateReplacePolicy, termination protection, and the cleanup plan.",
        "The deploy policy scopes CloudFront invalidation to distributions in this account because the stack creates a distribution ID dynamically. After deployment, narrow this statement to the exact FrontendDistribution ARN if the workflow remains functional.",
        "Confirm whether first-time Cognito domain setup requires an administrator-created service-linked role; do not broaden the CloudFormation execution role to create arbitrary service-linked roles.",
    ]
    plan = {
        "classification": "review-only proposal; not live configuration",
        "account_id": account_id,
        "region": REGION,
        "repository": REPOSITORY,
        "stack_name": STACK_NAME,
        "artifact_bucket": {
            "name": artifact_bucket,
            "verified": False,
            "note": "Candidate name only unless explicitly supplied and independently verified.",
        },
        "proposed_identities": {
            "github_deploy_role": _role_arn(account_id, deploy_role_name),
            "github_review_role": _role_arn(account_id, review_role_name),
            "cloudformation_execution_role": _role_arn(account_id, execution_role_name),
            "runtime_boundary_arn": f"arn:aws:iam::{account_id}:policy/{boundary_policy_name}",
            "artifact_bucket": artifact_bucket,
        },
        "github_environment_variables": {
            "aws-demo": {
                "AWS_REGION": REGION,
                "AWS_ACCOUNT_ID": account_id,
                "AWS_DEPLOY_ROLE_ARN": _role_arn(account_id, deploy_role_name),
                "CFN_EXECUTION_ROLE_ARN": _role_arn(account_id, execution_role_name),
                "RUNTIME_PERMISSIONS_BOUNDARY_ARN": f"arn:aws:iam::{account_id}:policy/{boundary_policy_name}",
                "SAM_ARTIFACT_BUCKET": artifact_bucket,
            },
            "aws-demo-review": {
                "AWS_REGION": REGION,
                "AWS_ACCOUNT_ID": account_id,
                "AWS_REVIEW_ROLE_ARN": _role_arn(account_id, review_role_name),
            },
        },
        "template_resources": resource_inventory,
        "known_sam_generated_resource_families": [
            "AWS::ApiGatewayV2::Api",
            "AWS::ApiGatewayV2::Authorizer",
            "AWS::ApiGatewayV2::Integration",
            "AWS::ApiGatewayV2::Route",
            "AWS::ApiGatewayV2::Stage",
            "AWS::Lambda::Permission",
        ],
        "administrator_bootstrap_action_families": {
            "GitHub OIDC provider": [
                "iam:CreateOpenIDConnectProvider (only if absent after a successful read)",
                "iam:TagOpenIDConnectProvider (optional project tags)",
            ],
            "OIDC and CloudFormation roles": [
                "iam:CreateRole",
                "iam:UpdateAssumeRolePolicy",
                "iam:PutRolePolicy or iam:AttachRolePolicy",
                "iam:PutRolePermissionsBoundary for the two Lambda runtime roles, restricted to the approved boundary ARN",
                "iam:PassRole only to the intended service and exact target role",
            ],
            "Dedicated artifact bucket": [
                "s3:CreateBucket",
                "s3:PutEncryptionConfiguration",
                "s3:PutBucketPublicAccessBlock",
                "s3:PutBucketOwnershipControls",
                "s3:PutLifecycleConfiguration",
                "s3:PutBucketTagging",
            ],
            "GitHub settings": [
                "Configure environments, branch restrictions, reviewers, and Actions variables in GitHub; no AWS IAM action performs this step.",
            ],
        },
        "deployment_workflow_has_oidc": (
            "aws-actions/configure-aws-credentials" in workflow_text
            and "id-token: write" in workflow_text
        ),
        "unresolved_security_review": unresolved,
        "aws_mutations_performed": False,
        "deployment_performed": False,
    }

    cfn_requirements = {
        "classification": "generated constrained policy draft plus requirements manifest; not AWS-validated or approved; DO NOT attach without administrator review",
        "role_name": execution_role_name,
        "candidate_policy_file": "policies/cloudformation-execution-role-candidate.json",
        "candidate_policy_validation": {
            "local_json_shape_checked": True,
            "wildcard_actions": False,
            "resource_scoping": "Exact fixed names where available; account/region-scoped patterns for generated resources.",
            "aws_iam_access_analyzer_run": False,
            "target_account_simulation_run": False,
            "approval_status": "not approved for attachment",
        },
        "trust_policy_file": "trust/cloudformation-execution-trust.json",
        "resource_types_in_template": sorted({item["declared_type"] for item in resource_inventory}),
        "offline_sam_transform_observed": {
            "sam_cli_version": "1.170.0",
            "sam_translator_version": "1.115.0",
            "note": "Locally translated with inert s3://example-artifacts/placeholder.zip CodeUri values; no AWS calls or resource operations. Revalidate after SAM/template changes.",
            "generated_resources": [
                {"logical_id": "DonationsFunction", "type": "AWS::Lambda::Function"},
                {"logical_id": "DonationsFunctionHealthPermission", "type": "AWS::Lambda::Permission"},
                {"logical_id": "DonationsFunctionApiProxyPermission", "type": "AWS::Lambda::Permission"},
                {"logical_id": "ETLFunction", "type": "AWS::Lambda::Function"},
                {"logical_id": "DonationsApi", "type": "AWS::ApiGatewayV2::Api"},
                {"logical_id": "DonationsApiStage", "type": "AWS::ApiGatewayV2::Stage"},
            ],
        },
        "service_action_families_to_validate": {
            "AWS::ApiGatewayV2::Api/AWS::ApiGatewayV2::Stage": [
                "apigateway:POST",
                "apigateway:GET",
                "apigateway:PATCH",
                "apigateway:DELETE",
            ],
            "AWS::CloudFront::Distribution/AWS::CloudFront::OriginAccessControl": [
                "cloudfront:CreateDistribution",
                "cloudfront:GetDistribution",
                "cloudfront:UpdateDistribution",
                "cloudfront:DeleteDistribution (rollback only where required)",
                "cloudfront:CreateOriginAccessControl",
                "cloudfront:GetOriginAccessControl",
                "cloudfront:UpdateOriginAccessControl",
                "cloudfront:DeleteOriginAccessControl (rollback only where required)",
                "cloudfront:TagResource",
                "cloudfront:UntagResource",
                "cloudfront:ListTagsForResource",
            ],
            "AWS::Cognito::*": [
                "cognito-idp:CreateUserPool",
                "cognito-idp:DescribeUserPool",
                "cognito-idp:UpdateUserPool",
                "cognito-idp:DeleteUserPool (rollback only where required)",
                "cognito-idp:CreateUserPoolClient",
                "cognito-idp:DescribeUserPoolClient",
                "cognito-idp:UpdateUserPoolClient",
                "cognito-idp:DeleteUserPoolClient (rollback only where required)",
                "cognito-idp:CreateUserPoolDomain",
                "cognito-idp:DescribeUserPoolDomain",
                "cognito-idp:DeleteUserPoolDomain (rollback only where required)",
                "cognito-idp:CreateGroup",
                "cognito-idp:GetGroup",
                "cognito-idp:UpdateGroup",
                "cognito-idp:DeleteGroup (rollback only where required)",
                "cognito-idp:TagResource",
                "cognito-idp:UntagResource",
            ],
            "AWS::DynamoDB::Table": [
                "dynamodb:CreateTable",
                "dynamodb:DescribeTable",
                "dynamodb:UpdateTable",
                "dynamodb:TagResource",
                "dynamodb:UntagResource",
                "dynamodb:DeleteTable (rollback only where required)",
            ],
            "AWS::IAM::Role": [
                "iam:CreateRole",
                "iam:GetRole",
                "iam:TagRole",
                "iam:UntagRole",
                "iam:PutRolePolicy",
                "iam:DeleteRolePolicy",
                "iam:PutRolePermissionsBoundary",
                "iam:PassRole restricted to the two exact Lambda roles and lambda.amazonaws.com",
                "iam:DeleteRole (rollback only where required)",
            ],
            "AWS::Lambda::Function/AWS::Lambda::Permission": [
                "lambda:CreateFunction",
                "lambda:GetFunction",
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:GetPolicy",
                "lambda:AddPermission",
                "lambda:RemovePermission",
                "lambda:DeleteFunction (rollback only where required)",
            ],
            "AWS::Logs::LogGroup": [
                "logs:CreateLogGroup",
                "logs:PutRetentionPolicy",
                "logs:TagResource",
                "logs:UntagResource",
                "logs:DeleteLogGroup (rollback only where required)",
            ],
            "AWS::S3::*": [
                "s3:CreateBucket",
                "s3:GetBucketLocation",
                "s3:GetBucketPolicy",
                "s3:GetEncryptionConfiguration",
                "s3:GetBucketPublicAccessBlock",
                "s3:GetBucketOwnershipControls",
                "s3:GetLifecycleConfiguration",
                "s3:PutEncryptionConfiguration",
                "s3:PutBucketPublicAccessBlock",
                "s3:PutBucketOwnershipControls",
                "s3:PutLifecycleConfiguration",
                "s3:PutBucketPolicy",
                "s3:PutBucketTagging",
                "s3:DeleteBucketPolicy (rollback only where required)",
                "s3:DeleteBucket (rollback only; retained buckets should not be deleted)",
            ],
        },
        "service_families_requiring_action_mapping": [
            "AWS::ApiGatewayV2::*",
            "AWS::CloudFront::*",
            "AWS::Cognito::*",
            "AWS::DynamoDB::Table",
            "AWS::IAM::Role",
            "AWS::Lambda::*",
            "AWS::Logs::LogGroup",
            "AWS::S3::*",
            "AWS::Serverless::* (transform to concrete resources before mapping)",
        ],
        "required_review": unresolved,
        "additional_required_access": [
            {
                "service": "Amazon S3",
                "actions": ["s3:GetObject"],
                "resource": f"arn:aws:s3:::{artifact_bucket}/sharebite/artifacts/*",
                "purpose": "CloudFormation must fetch packaged SAM artifacts during stack create/update and rollback.",
            },
            {
                "service": "Lambda",
                "actions": ["lambda:PassRole"],
                "resource": [
                    f"arn:aws:iam::{account_id}:role/{STACK_NAME}-lambda-role",
                    f"arn:aws:iam::{account_id}:role/{STACK_NAME}-etl-role",
                ],
                "condition": {"iam:PassedToService": "lambda.amazonaws.com"},
                "purpose": "CloudFormation attaches the two pre-scoped runtime roles to Lambda functions.",
            },
        ],
    }

    return {
        "plan.json": plan,
        "report.md": _render_report(plan, cfn_requirements),
        "trust/github-deploy-trust.json": _trusted_web_identity(account_id, "aws-demo"),
        "trust/github-review-trust.json": _trusted_web_identity(account_id, "aws-demo-review"),
        "trust/cloudformation-execution-trust.json": _cloudformation_trust(account_id),
        "trust/lambda-runtime-trust.json": _required_role_trust(account_id),
        "policies/github-deploy-role.json": deploy_policy,
        "policies/github-review-role.json": review_policy,
        "policies/lambda-api-runtime-role.json": app_runtime_policy,
        "policies/lambda-etl-runtime-role.json": etl_runtime_policy,
        "policies/lambda-runtime-permissions-boundary.json": runtime_boundary,
        "policies/cloudformation-execution-role-candidate.json": cloudformation_execution_policy,
        "policies/cloudformation-execution-role-requirements.json": cfn_requirements,
    }


def _render_report(plan: dict, cfn_requirements: dict) -> str:
    resources = "\n".join(
        f"| `{item['logical_id']}` | `{item['declared_type']}` |"
        for item in plan["template_resources"]
    )
    env_values = "\n".join(
        f"- **{environment}:** " + ", ".join(f"`{key}`=`{value}`" for key, value in values.items())
        for environment, values in plan["github_environment_variables"].items()
    )
    open_items = "\n".join(f"- {item}" for item in plan["unresolved_security_review"])
    transform = cfn_requirements["offline_sam_transform_observed"]
    generated_resources = "\n".join(
        f"| `{item['logical_id']}` | `{item['type']}` |"
        for item in transform["generated_resources"]
    )
    action_families = "\n".join(
        f"| `{resource_type}` | {', '.join(f'`{action}`' for action in actions)} |"
        for resource_type, actions in cfn_requirements[
            "service_action_families_to_validate"
        ].items()
    )
    admin_steps = "\n".join(
        f"- **{category}:** " + ", ".join(f"`{action}`" for action in actions)
        for category, actions in plan["administrator_bootstrap_action_families"].items()
    )
    return f"""# ShareBite AWS bootstrap plan

**Review-only proposal.** This report was generated from local repository files and the supplied account ID. It does not confirm that an AWS resource, role, bucket, permission, or GitHub environment exists. No AWS/GitHub mutation or application deployment was performed.

- Account: `{plan['account_id']}`
- Region: `{plan['region']}`
- Stack: `{plan['stack_name']}`
- Candidate artifact bucket: `{plan['artifact_bucket']['name']}` (unverified)
- Deployment workflow uses OIDC: `{str(plan['deployment_workflow_has_oidc']).lower()}`

## Template resource inventory

| Logical ID | Declared type |
|---|---|
{resources}

The source inventory includes SAM types. The requirements manifest includes an offline transform observed with its recorded SAM CLI/SAM Translator versions; generated permissions and rollback scope still require review against the exact deployed transform.

## Offline SAM-generated resources

Observed using SAM CLI `{transform['sam_cli_version']}` and SAM Translator `{transform['sam_translator_version']}`; local CodeUri values were replaced in memory with inert artifact URIs. No AWS request or stack operation was made.

| Generated logical ID | Transformed type |
|---|---|
{generated_resources}

## CloudFormation execution-role action map for administrator validation

The following action families are a starting map derived from the source/transformed resource inventory, not a complete or attachable policy. CloudFormation create/update/rollback paths and service-specific resource ARN support must be validated before role policy design.

| Resource family | Candidate actions to validate |
|---|---|
{action_families}

## Proposed GitHub environment variables

Values below are derived proposals, not live settings:

{env_values}

Configure `aws-demo` for `main` only with independent required reviewers. Configure `aws-demo-review` for `main` with no write-capable role. Do not store AWS keys in GitHub secrets.

## Administrator bootstrap action families (not executed)

{admin_steps}

## Generated review artifacts

- GitHub OIDC deployment and review trust policies are restricted to `repo:{REPOSITORY}:environment:aws-demo` and `aws-demo-review`.
- The CloudFormation execution trust policy is scoped to the account, region, and stack ARN.
- GitHub deployment/review and both Lambda runtime role permission candidates are resource-scoped where practical.
- The runtime permissions boundary candidate carries the API and ETL permissions in separate statements conditioned on each exact runtime role ARN, preventing either role from inheriting the other role's boundary allowance.
- `policies/cloudformation-execution-role-candidate.json` is a constrained draft covering the declared template and recorded SAM transform. It scopes fixed names and account/region patterns, limits `iam:PassRole` to the two runtime roles, and requires the configured Lambda permissions boundary.
- The candidate contains a few `Resource: "*"` statements for create/domain-description calls with identifiers unavailable before creation. Exact scopes and all actions, especially rollback deletes, still require IAM Access Analyzer and target-account change-set validation; no policy is attached by this tool.
- `{cfn_requirements['classification']}`. The companion requirements manifest preserves the transform inventory and action rationale.

## Unresolved review items

{open_items}

**Do not attach these candidate policies solely because they were generated.** IAM resource-level authorization, GitHub protection rules, actual resource ownership, regional price/eligibility, and final transformed-template actions require independent verification.

The CloudFormation requirements manifest records an offline SAM transform observed with SAM CLI 1.170.0 / SAM Translator 1.115.0. This is local structural validation, not IAM Access Analyzer validation. Rebuild and revalidate both files whenever SAM CLI, template, or deployment workflow changes.
"""


def write_artifacts(
    output_dir: Path,
    artifacts: dict[str, dict | str],
    *,
    overwrite: bool = False,
) -> None:
    existing = [
        output_dir / relative
        for relative in artifacts
        if (output_dir / relative).exists()
    ]
    if existing and not overwrite:
        raise FileExistsError(
            "Refusing to overwrite existing plan artifacts; inspect them and rerun with --force: "
            + ", ".join(str(path) for path in existing)
        )
    for relative, value in sorted(artifacts.items()):
        destination = output_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            destination.write_text(value, encoding="utf-8")
        else:
            destination.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("plan", "check", "apply"), default="plan")
    parser.add_argument("--account-id")
    parser.add_argument("--artifact-bucket")
    parser.add_argument("--output-dir", type=Path, default=Path(DEFAULT_PLAN_DIRECTORY))
    parser.add_argument("--force", action="store_true", help="Overwrite plan files in --output-dir after reviewing them.")
    parser.add_argument("--profile", default="sharebite")
    parser.add_argument("--expected-account-id")
    parser.add_argument("--boundary-arn")
    parser.add_argument("--deploy-role-name", default="sharebite-github-deploy")
    parser.add_argument("--review-role-name", default="sharebite-github-review")
    parser.add_argument("--execution-role-name", default="sharebite-cloudformation-execution")
    parser.add_argument("--boundary-policy-name", default="sharebite-lambda-runtime-boundary")
    parser.add_argument("--skip-github", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "apply":
        print(
            "Apply mode is intentionally unavailable. This tool never creates or modifies "
            "AWS resources, IAM policies/roles, OIDC providers, buckets, GitHub settings, "
            "or application stacks. Use the generated plan and an administrator-reviewed "
            "change process.",
            file=sys.stderr,
        )
        return 3
    if args.mode == "check":
        if __package__:
            from .aws_preflight import main as preflight_main
        else:
            from aws_preflight import main as preflight_main

        preflight_args = [
            "--profile", args.profile,
        ]
        if args.expected_account_id:
            preflight_args.extend(["--expected-account-id", args.expected_account_id])
        if args.artifact_bucket:
            preflight_args.extend(["--artifact-bucket", args.artifact_bucket])
        if args.boundary_arn:
            preflight_args.extend(["--boundary-arn", args.boundary_arn])
        preflight_args.extend(
            [
                "--deploy-role-name", args.deploy_role_name,
                "--review-role-name", args.review_role_name,
                "--execution-role-name", args.execution_role_name,
            ]
        )
        if args.skip_github:
            preflight_args.append("--skip-github")
        return preflight_main(preflight_args)

    if not args.account_id:
        print("Plan mode requires --account-id; obtain it from aws sts get-caller-identity.", file=sys.stderr)
        return 3
    root = Path(__file__).resolve().parents[1]
    template_path = root / "template.yaml"
    workflow_path = root / ".github/workflows/deploy-aws.yml"
    try:
        template_text = template_path.read_text(encoding="utf-8")
        workflow_text = workflow_path.read_text(encoding="utf-8")
        account_id = args.account_id
        bucket = args.artifact_bucket or f"sharebite-{account_id}-{REGION}-artifacts"
        artifacts = build_artifacts(
            account_id,
            bucket,
            deploy_role_name=args.deploy_role_name,
            review_role_name=args.review_role_name,
            execution_role_name=args.execution_role_name,
            boundary_policy_name=args.boundary_policy_name,
            template_text=template_text,
            workflow_text=workflow_text,
        )
        write_artifacts(args.output_dir, artifacts, overwrite=args.force)
    except (OSError, ValueError) as error:
        print(f"Could not generate bootstrap plan: {error}", file=sys.stderr)
        return 3
    print(f"Generated {len(artifacts)} review-only artifacts under {args.output_dir}.")
    print("No AWS or GitHub API calls or mutations were made.")
    print(
        "Review every artifact. The CloudFormation execution policy is a constrained "
        "draft and must pass IAM Access Analyzer and target-account review before attachment."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
