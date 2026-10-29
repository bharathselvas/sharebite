import json
from pathlib import Path

import pytest

from scripts.aws_bootstrap_plan import build_artifacts, main, write_artifacts

ROOT = Path(__file__).resolve().parents[2]


def artifacts():
    return build_artifacts(
        "123456789012",
        "sharebite-123456789012-ap-south-1-artifacts",
        deploy_role_name="sharebite-github-deploy",
        review_role_name="sharebite-github-review",
        execution_role_name="sharebite-cloudformation-execution",
        boundary_policy_name="sharebite-lambda-runtime-boundary",
        template_text=(ROOT / "template.yaml").read_text(),
        workflow_text=(ROOT / ".github/workflows/deploy-aws.yml").read_text(),
    )


def test_plan_artifacts_are_deterministic_and_include_real_template_inventory(tmp_path):
    first = artifacts()
    second = artifacts()
    assert first == second
    write_artifacts(tmp_path, first)
    assert (tmp_path / "report.md").exists()
    plan = json.loads((tmp_path / "plan.json").read_text())
    logical_ids = {item["logical_id"] for item in plan["template_resources"]}
    assert {"DonationsTable", "FrontendDistribution", "ETLFunction"} <= logical_ids
    assert "ProjectName" not in logical_ids
    assert "String" not in {item["declared_type"] for item in plan["template_resources"]}
    assert len(logical_ids) == 19
    assert plan["aws_mutations_performed"] is False
    assert plan["deployment_performed"] is False
    assert plan["artifact_bucket"]["verified"] is False


def test_oidc_trust_is_restricted_to_repo_and_each_environment():
    generated = artifacts()
    deploy = generated["trust/github-deploy-trust.json"]["Statement"][0]
    review = generated["trust/github-review-trust.json"]["Statement"][0]
    assert deploy["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"] == (
        "repo:bharathselvas/sharebite:environment:aws-demo"
    )
    assert review["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"] == (
        "repo:bharathselvas/sharebite:environment:aws-demo-review"
    )
    assert deploy["Principal"]["Federated"].endswith(
        "oidc-provider/token.actions.githubusercontent.com"
    )


def test_candidate_runtime_policies_and_permissions_boundary_are_role_scoped():
    generated = artifacts()
    for key in (
        "policies/lambda-api-runtime-role.json",
        "policies/lambda-etl-runtime-role.json",
        "policies/lambda-runtime-permissions-boundary.json",
    ):
        policy = generated[key]
        assert all(statement["Resource"] != "*" for statement in policy["Statement"])
    etl = generated["policies/lambda-etl-runtime-role.json"]
    assert etl["Statement"][1]["Resource"] == (
        "arn:aws:s3:::sharebite-123456789012-ap-south-1-analytics/etl/*"
    )
    cfn = generated["policies/cloudformation-execution-role-requirements.json"]
    assert cfn["classification"].startswith("generated constrained policy draft")
    assert "DO NOT attach" in cfn["classification"]
    boundary = generated["policies/lambda-runtime-permissions-boundary.json"]
    role_arns = {
        statement["Condition"]["ArnEquals"]["aws:PrincipalArn"]
        for statement in boundary["Statement"]
    }
    assert role_arns == {
        "arn:aws:iam::123456789012:role/smart-food-demo-lambda-role",
        "arn:aws:iam::123456789012:role/smart-food-demo-etl-role",
    }
    api_access = next(
        statement for statement in boundary["Statement"]
        if statement["Sid"] == "AccessDonationRecords"
    )
    assert api_access["Action"] == [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
    ]
    assert api_access["Condition"]["ArnEquals"]["aws:PrincipalArn"].endswith(
        "smart-food-demo-lambda-role"
    )
    etl_access = next(
        statement for statement in boundary["Statement"]
        if statement["Sid"] == "WriteETLReportsOnly"
    )
    assert etl_access["Condition"]["ArnEquals"]["aws:PrincipalArn"].endswith(
        "smart-food-demo-etl-role"
    )


def test_candidate_deploy_policy_limits_passrole_and_marks_cloudfront_scope():
    policy = artifacts()["policies/github-deploy-role.json"]
    pass_role = next(
        statement for statement in policy["Statement"]
        if statement["Sid"] == "PassOnlyShareBiteCloudFormationExecutionRole"
    )
    assert pass_role["Resource"] == (
        "arn:aws:iam::123456789012:role/sharebite-cloudformation-execution"
    )
    assert pass_role["Condition"]["StringEquals"]["iam:PassedToService"] == (
        "cloudformation.amazonaws.com"
    )
    invalidation = next(
        statement for statement in policy["Statement"]
        if statement["Sid"] == "InvalidateShareBiteDistribution"
    )
    assert invalidation["Resource"] == (
        "arn:aws:cloudfront::123456789012:distribution/*"
    )
    assert invalidation["Condition"]["StringEquals"] == {
        "aws:ResourceTag/Project": "ShareBite"
    }


def test_cloudformation_policy_draft_is_account_scoped_and_has_no_wildcard_actions():
    generated = artifacts()
    policy = generated["policies/cloudformation-execution-role-candidate.json"]
    statements = policy["Statement"]
    api_permissions = next(
        statement
        for statement in statements
        if statement["Sid"] == "ManageShareBiteApiLambdaPermissions"
    )
    assert api_permissions["Condition"] == {
        "StringEquals": {"aws:SourceAccount": "123456789012"},
        "ArnLike": {
            "aws:SourceArn": (
                "arn:aws:execute-api:ap-south-1:123456789012:"
                "*/*/*/api/*"
            )
        },
    }
    actions = {
        action
        for statement in statements
        for action in (
            statement["Action"]
            if isinstance(statement["Action"], list)
            else [statement["Action"]]
        )
    }
    assert "*" not in actions
    assert all(
        statement.get("Effect") == "Allow"
        and statement.get("Resource")
        for statement in statements
    )
    role_creation = next(
        statement
        for statement in statements
        if statement["Sid"] == "CreateShareBiteLambdaRolesWithApprovedBoundary"
    )
    assert role_creation["Resource"] == [
        "arn:aws:iam::123456789012:role/smart-food-demo-lambda-role",
        "arn:aws:iam::123456789012:role/smart-food-demo-etl-role",
    ]
    assert role_creation["Condition"]["StringEquals"]["iam:PermissionsBoundary"] == (
        "arn:aws:iam::123456789012:policy/sharebite-lambda-runtime-boundary"
    )
    pass_role = next(
        statement
        for statement in statements
        if statement["Sid"] == "PassOnlyShareBiteRuntimeRolesToLambda"
    )
    assert pass_role["Condition"]["StringEquals"]["iam:PassedToService"] == (
        "lambda.amazonaws.com"
    )
    wildcard_resource_actions = {
        action
        for statement in statements
        if statement["Resource"] == "*"
        for action in (
            statement["Action"]
            if isinstance(statement["Action"], list)
            else [statement["Action"]]
        )
    }
    assert wildcard_resource_actions <= {
        "cognito-idp:CreateUserPool",
        "cognito-idp:DescribeUserPoolDomain",
        "cloudfront:CreateDistribution",
        "cloudfront:CreateOriginAccessControl",
    }
    manifest = generated[
        "policies/cloudformation-execution-role-requirements.json"
    ]
    assert manifest["candidate_policy_validation"]["wildcard_actions"] is False
    assert manifest["candidate_policy_validation"]["aws_iam_access_analyzer_run"] is False
    assert manifest["candidate_policy_validation"]["approval_status"] == (
        "not approved for attachment"
    )


def test_execution_manifest_records_offline_transform_and_action_families():
    manifest = artifacts()["policies/cloudformation-execution-role-requirements.json"]
    transformed = manifest["offline_sam_transform_observed"]
    assert transformed["sam_cli_version"] == "1.170.0"
    assert transformed["sam_translator_version"] == "1.115.0"
    generated = {
        (item["logical_id"], item["type"])
        for item in transformed["generated_resources"]
    }
    assert ("DonationsFunctionApiProxyPermission", "AWS::Lambda::Permission") in generated
    actions = manifest["service_action_families_to_validate"]
    assert "s3:PutBucketPublicAccessBlock" in actions["AWS::S3::*"]
    assert "s3:PutLifecycleConfiguration" in actions["AWS::S3::*"]
    assert "s3:PutPublicAccessBlock" not in actions["AWS::S3::*"]


def test_invalid_account_or_artifact_bucket_is_rejected():
    try:
        build_artifacts(
            "not-an-account",
            "invalid bucket",
            deploy_role_name="deploy",
            review_role_name="review",
            execution_role_name="cfn",
            boundary_policy_name="boundary",
            template_text="Resources:\n",
            workflow_text="",
        )
    except ValueError as error:
        assert "Account ID" in str(error)
    else:
        raise AssertionError("Invalid account ID was accepted")


def test_apply_mode_fails_closed_without_creating_anything(tmp_path, capsys):
    assert main(["apply", "--output-dir", str(tmp_path)]) == 3
    assert list(tmp_path.iterdir()) == []
    assert "intentionally unavailable" in capsys.readouterr().err


def test_check_mode_delegates_to_preflight_without_changing_arguments(monkeypatch):
    from scripts import aws_preflight

    captured = []
    monkeypatch.setattr(
        aws_preflight,
        "main",
        lambda values: captured.append(values) or 2,
    )
    assert main([
        "check",
        "--profile", "sharebite",
        "--expected-account-id", "123456789012",
        "--artifact-bucket", "sharebite-123456789012-ap-south-1-artifacts",
        "--boundary-arn", "arn:aws:iam::123456789012:policy/boundary",
        "--skip-github",
    ]) == 2
    assert captured == [[
        "--profile", "sharebite",
        "--expected-account-id", "123456789012",
        "--artifact-bucket", "sharebite-123456789012-ap-south-1-artifacts",
        "--boundary-arn", "arn:aws:iam::123456789012:policy/boundary",
        "--deploy-role-name", "sharebite-github-deploy",
        "--review-role-name", "sharebite-github-review",
        "--execution-role-name", "sharebite-cloudformation-execution",
        "--skip-github",
    ]]


def test_plan_refuses_to_overwrite_existing_review_artifacts(tmp_path):
    generated = artifacts()
    write_artifacts(tmp_path, generated)
    original = (tmp_path / "plan.json").read_text()
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        write_artifacts(tmp_path, generated)
    assert (tmp_path / "plan.json").read_text() == original
    write_artifacts(tmp_path, generated, overwrite=True)
