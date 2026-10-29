from pathlib import Path

from scripts.aws_preflight import (
    CommandResult,
    Report,
    _call,
    _check_trust,
    aws_error_code,
    profile_sso_status,
    run_preflight,
    status_for_error,
)
from scripts import aws_preflight


class FakeRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, args, region, profile):
        self.calls.append((args, region, profile))
        return self.result


class ReadyRunner:
    account = "123456789012"
    boundary = f"arn:aws:iam::{account}:policy/sharebite-lambda-runtime-boundary"
    provider = f"arn:aws:iam::{account}:oidc-provider/token.actions.githubusercontent.com"
    summaries = [
        {
            "LogicalResourceId": "LambdaExecutionRole",
            "PhysicalResourceId": "smart-food-demo-lambda-role",
            "ResourceStatus": "CREATE_COMPLETE",
        },
        {
            "LogicalResourceId": "ETLExecutionRole",
            "PhysicalResourceId": "smart-food-demo-etl-role",
            "ResourceStatus": "CREATE_COMPLETE",
        },
    ]
    outputs = [
        {"OutputKey": key, "OutputValue": value}
        for key, value in {
            "ApiBaseUrl": "https://apiid.execute-api.ap-south-1.amazonaws.com/demo",
            "FrontendUrl": "https://example.cloudfront.net",
            "FrontendDistributionId": "E123456789",
            "FrontendBucketName": f"sharebite-{account}-ap-south-1-frontend",
            "DonationsTableName": "smart-food-demo-donations",
            "AnalyticsBucketName": f"sharebite-{account}-ap-south-1-analytics",
            "LambdaFunctionName": "smart-food-demo-api",
            "ETLFunctionName": "smart-food-demo-etl",
            "CognitoUserPoolId": "ap-south-1_example",
            "CognitoAppClientId": "client-id",
            "CognitoIssuer": "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_example",
            "CognitoHostedUi": "https://sharebite-demo.auth.ap-south-1.amazoncognito.com",
        }.items()
    ]

    def __init__(self):
        self.calls = []

    def run(self, args, region, profile):
        self.calls.append((args, region, profile))
        service, operation = args[:2]
        if (service, operation) == ("sts", "get-caller-identity"):
            return CommandResult(
                True,
                {
                    "Account": self.account,
                    "Arn": f"arn:aws:sts::{self.account}:assumed-role/Developer/session",
                },
            )
        if (service, operation) == ("iam", "list-open-id-connect-providers"):
            return CommandResult(True, {"OpenIDConnectProviderList": [{"Arn": self.provider}]})
        if (service, operation) == ("iam", "get-open-id-connect-provider"):
            return CommandResult(True, {"Url": "token.actions.githubusercontent.com", "ClientIDList": ["sts.amazonaws.com"]})
        if (service, operation) == ("iam", "get-role"):
            name = args[args.index("--role-name") + 1]
            if name in {"sharebite-github-deploy", "sharebite-github-review"}:
                environment = "aws-demo" if "deploy" in name else "aws-demo-review"
                trust = {
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"Federated": self.provider},
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                "token.actions.githubusercontent.com:sub": f"repo:bharathselvas/sharebite:environment:{environment}",
                            }
                        },
                    }]
                }
            elif name == "sharebite-cloudformation-execution":
                trust = {
                    "Statement": [{
                        "Effect": "Allow",
                        "Principal": {"Service": "cloudformation.amazonaws.com"},
                        "Action": "sts:AssumeRole",
                        "Condition": {
                            "StringEquals": {"aws:SourceAccount": self.account},
                            "ArnLike": {
                                "aws:SourceArn": f"arn:aws:cloudformation:ap-south-1:{self.account}:stack/smart-food-demo/*"
                            },
                        },
                    }]
                }
            else:
                trust = {"Statement": []}
            role = {"Role": {"AssumeRolePolicyDocument": trust}}
            if name in {"smart-food-demo-lambda-role", "smart-food-demo-etl-role"}:
                role["Role"]["PermissionsBoundary"] = {"PermissionsBoundaryArn": self.boundary}
            return CommandResult(True, role)
        if (service, operation) == ("iam", "get-policy"):
            return CommandResult(True, {"Policy": {"Arn": self.boundary}})
        if (service, operation) == ("s3api", "get-bucket-location"):
            return CommandResult(True, {"LocationConstraint": "ap-south-1"})
        if (service, operation) == ("s3api", "get-public-access-block"):
            return CommandResult(True, {"PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            }})
        if (service, operation) == ("s3api", "get-bucket-encryption"):
            return CommandResult(True, {"ServerSideEncryptionConfiguration": {
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            }})
        if (service, operation) == ("s3api", "get-bucket-ownership-controls"):
            return CommandResult(True, {"OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]}})
        if (service, operation) == ("s3api", "get-bucket-lifecycle-configuration"):
            return CommandResult(True, {"Rules": [{
                "Status": "Enabled",
                "Filter": {"Prefix": "sharebite/artifacts/"},
                "Expiration": {"Days": 30},
            }]})
        if (service, operation) == ("cloudformation", "describe-stacks"):
            return CommandResult(True, {"Stacks": [{
                "StackName": "smart-food-demo",
                "StackStatus": "UPDATE_COMPLETE",
                "EnableTerminationProtection": True,
                "Outputs": self.outputs,
            }]})
        if (service, operation) == ("cloudformation", "list-stack-resources"):
            return CommandResult(True, {"StackResourceSummaries": self.summaries})
        if (service, operation) == ("dynamodb", "describe-table"):
            return CommandResult(True, {"Table": {
                "TableStatus": "ACTIVE",
                "GlobalSecondaryIndexes": [
                    {"IndexName": name}
                    for name in ("status-index", "donor-index", "recipient-index", "entity-index", "expiry-index")
                ],
            }})
        if (service, operation) == ("dynamodb", "describe-continuous-backups"):
            return CommandResult(True, {"ContinuousBackupsDescription": {
                "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "DISABLED"}
            }})
        if (service, operation) == ("lambda", "get-function-configuration"):
            return CommandResult(True, {"State": "Active", "Runtime": "python3.12"})
        if (service, operation) == ("cognito-idp", "list-user-pools"):
            return CommandResult(True, {"UserPools": [{"Name": "smart-food-demo-users", "Id": "ap-south-1_example"}]})
        if (service, operation) == ("cognito-idp", "list-groups"):
            return CommandResult(True, {"Groups": [{"GroupName": name} for name in ("food-donors", "food-ngos", "food-admins")]})
        if (service, operation) == ("apigatewayv2", "get-api"):
            return CommandResult(True, {"ProtocolType": "HTTP"})
        if (service, operation) == ("cloudfront", "get-distribution"):
            return CommandResult(True, {"Distribution": {"DistributionConfig": {
                "Enabled": True,
                "DefaultCacheBehavior": {"ViewerProtocolPolicy": "redirect-to-https"},
                "Origins": {"Items": [{"OriginAccessControlId": "oac-id"}]},
            }}})
        raise AssertionError(f"Unexpected read-only API call: {args}")


def test_access_denied_and_unknown_errors_are_never_treated_as_missing():
    assert status_for_error("AccessDenied") == "denied"
    assert status_for_error("UnauthorizedOperation") == "denied"
    assert status_for_error("ValidationError") == "uncertain"
    assert status_for_error("NoSuchEntity") == "missing"


def test_stack_validation_error_is_missing_only_for_explicit_absence_message():
    runner = FakeRunner(
        CommandResult(
            False,
            code="ValidationError",
            message="Stack with id smart-food-demo does not exist",
        )
    )
    report = Report()
    value = _call(
        report,
        runner,
        "CloudFormation stack",
        ["cloudformation", "describe-stacks"],
        "sharebite",
        missing_validation_error=True,
    )
    assert value is None
    assert report.checks[0].status == "missing"


def test_unrecognized_validation_error_is_uncertain():
    runner = FakeRunner(
        CommandResult(False, code="ValidationError", message="Invalid request parameter")
    )
    report = Report()
    _call(
        report,
        runner,
        "CloudFormation stack",
        ["cloudformation", "describe-stacks"],
        "sharebite",
        missing_validation_error=True,
    )
    assert report.checks[0].status == "uncertain"
    assert report.exit_code == 2


def test_role_trust_requires_exact_github_subject_and_audience():
    account = "123456789012"
    provider = f"arn:aws:iam::{account}:oidc-provider/token.actions.githubusercontent.com"
    role = {
        "AssumeRolePolicyDocument": {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Federated": provider},
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                            "token.actions.githubusercontent.com:sub": (
                                "repo:bharathselvas/sharebite:environment:aws-demo"
                            ),
                        }
                    },
                }
            ]
        }
    }
    assert _check_trust(role, provider, "aws-demo", account)[0]
    assert not _check_trust(role, provider, "aws-demo-review", account)[0]
    role["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["StringEquals"][
        "token.actions.githubusercontent.com:aud"
    ] = "wrong-audience"
    assert not _check_trust(role, provider, "aws-demo", account)[0]


def test_cloudformation_trust_requires_stack_and_account_conditions():
    account = "123456789012"
    arn = f"arn:aws:cloudformation:ap-south-1:{account}:stack/smart-food-demo/*"
    role = {
        "AssumeRolePolicyDocument": {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "cloudformation.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {"aws:SourceAccount": account},
                        "ArnLike": {"aws:SourceArn": arn},
                    },
                }
            ]
        }
    }
    assert _check_trust(role, "", None, account)[0]
    role["AssumeRolePolicyDocument"]["Statement"][0]["Condition"]["ArnLike"][
        "aws:SourceArn"
    ] = "*"
    assert not _check_trust(role, "", None, account)[0]


def test_sts_auth_failure_stops_and_returns_permission_exit_code():
    runner = FakeRunner(CommandResult(False, code="ExpiredToken"))
    report = run_preflight(
        runner,
        profile="sharebite",
        expected_account_id=None,
        artifact_bucket=None,
        check_github=False,
    )
    assert report.exit_code == 2
    assert report.auth_or_permission_errors
    assert len(runner.calls) == 1


def test_complete_mocked_preflight_passes_without_github_api_calls():
    runner = ReadyRunner()
    report = run_preflight(
        runner,
        profile="sharebite",
        expected_account_id=runner.account,
        artifact_bucket=f"sharebite-{runner.account}-ap-south-1-artifacts",
        boundary_arn=runner.boundary,
        check_github=False,
    )
    assert report.exit_code == 0
    assert report.account_id == runner.account
    assert all(check.status == "passed" for check in report.checks)
    assert report.as_dict()["remaining_checklist"] == report.manual_reviews
    assert all(region == "ap-south-1" and profile == "sharebite" for _, region, profile in runner.calls)


def test_preflight_flags_enabled_pitr_for_explicit_cost_review():
    class PitrEnabledRunner(ReadyRunner):
        def run(self, args, region, profile):
            if args[:2] == ["dynamodb", "describe-continuous-backups"]:
                self.calls.append((args, region, profile))
                return CommandResult(True, {"ContinuousBackupsDescription": {
                    "PointInTimeRecoveryDescription": {
                        "PointInTimeRecoveryStatus": "ENABLED"
                    }
                }})
            return super().run(args, region, profile)

    runner = PitrEnabledRunner()
    report = run_preflight(
        runner,
        profile="sharebite",
        expected_account_id=runner.account,
        artifact_bucket=f"sharebite-{runner.account}-ap-south-1-artifacts",
        boundary_arn=runner.boundary,
        check_github=False,
    )
    table_check = next(
        check for check in report.checks
        if check.name == "DynamoDB table readiness smart-food-demo-donations"
    )
    assert table_check.status == "configuration"
    assert any("backup-storage charges" in item for item in report.manual_reviews)


def test_cli_error_parser_does_not_emit_credentials():
    assert aws_error_code("An error occurred (AccessDenied) when calling GetRole: denied") == "AccessDenied"
    assert aws_error_code("generic failure") == "AwsCliError"


def test_sso_profile_guard_rejects_non_sso_or_static_credentials(tmp_path, monkeypatch):
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ROLE_ARN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ):
        monkeypatch.delenv(key, raising=False)
    config = tmp_path / "config"
    credentials = tmp_path / "credentials"
    config.write_text(
        "[profile sharebite]\n"
        "sso_session = college\n"
        "sso_account_id = 123456789012\n"
        "sso_role_name = ShareBiteDeploy\n"
        "region = ap-south-1\n"
        "\n[sso-session college]\n"
        "sso_start_url = https://example.awsapps.com/start\n"
        "sso_region = ap-south-1\n",
        encoding="utf-8",
    )
    credentials.write_text("", encoding="utf-8")
    assert profile_sso_status(
        "sharebite",
        config_path=config,
        credentials_path=credentials,
        expected_account_id="123456789012",
    )[0]
    valid, detail = profile_sso_status(
        "sharebite",
        config_path=config,
        credentials_path=credentials,
        expected_account_id="210987654321",
    )
    assert not valid
    assert "does not match" in detail
    credentials.write_text(
        "[sharebite]\naws_access_key_id = hidden\naws_secret_access_key = hidden\n",
        encoding="utf-8",
    )
    valid, detail = profile_sso_status(
        "sharebite", config_path=config, credentials_path=credentials
    )
    assert not valid
    assert "Static credentials" in detail
    assert "hidden" not in detail


def test_sso_profile_guard_rejects_missing_profile_and_environment_credentials(
    tmp_path, monkeypatch
):
    config = tmp_path / "config"
    credentials = tmp_path / "credentials"
    config.write_text("[profile unrelated]\nregion = ap-south-1\n", encoding="utf-8")
    credentials.write_text("", encoding="utf-8")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    valid, detail = profile_sso_status(
        "sharebite", config_path=config, credentials_path=credentials
    )
    assert not valid
    assert "not configured" in detail

    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-print")
    valid, detail = profile_sso_status(
        "sharebite", config_path=config, credentials_path=credentials
    )
    assert not valid
    assert "environment variables" in detail
    assert "do-not-print" not in detail


def test_sso_profile_guard_rejects_default_profile_and_endpoint_override(
    tmp_path, monkeypatch
):
    config = tmp_path / "config"
    credentials = tmp_path / "credentials"
    config.write_text("", encoding="utf-8")
    credentials.write_text("", encoding="utf-8")
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_STS", raising=False)
    valid, detail = profile_sso_status(
        "default", config_path=config, credentials_path=credentials
    )
    assert not valid
    assert "named AWS" in detail

    monkeypatch.setenv("AWS_ENDPOINT_URL_STS", "https://example.invalid")
    valid, detail = profile_sso_status(
        "sharebite", config_path=config, credentials_path=credentials
    )
    assert not valid
    assert "endpoint override" in detail


def test_main_stops_before_aws_api_calls_without_sso_profile(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config"
    credentials = tmp_path / "credentials"
    config.write_text("[profile sharebite]\nregion = ap-south-1\n", encoding="utf-8")
    credentials.write_text("", encoding="utf-8")
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ROLE_ARN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setattr(
        aws_preflight.shutil,
        "which",
        lambda name: f"/usr/bin/{name}" if name in {"aws", "sam"} else None,
    )
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command == ["sam", "--version"]:
            return aws_preflight.subprocess.CompletedProcess(
                command, 0, stdout="SAM CLI, version 1.170.0", stderr=""
            )
        return aws_preflight.subprocess.CompletedProcess(
            command, 0, stdout="aws-cli/2.39.1 Python/3.12", stderr=""
        )

    monkeypatch.setattr(aws_preflight.subprocess, "run", fake_run)
    assert aws_preflight.main([
        "--expected-account-id", "123456789012", "--skip-github"
    ]) == 3
    assert commands == [["aws", "--version"], ["sam", "--version"]]
    assert "Refusing AWS calls" in capsys.readouterr().err


def test_main_requires_explicit_target_account_before_tools_or_aws(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        aws_preflight.shutil,
        "which",
        lambda name: calls.append(name) or f"/usr/bin/{name}",
    )
    assert aws_preflight.main(["--skip-github"]) == 3
    assert calls == []
    assert "explicit --expected-account-id" in capsys.readouterr().err


def test_main_requires_sam_cli_before_any_aws_api_call(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config"
    credentials = tmp_path / "credentials"
    config.write_text("[profile sharebite]\nregion = ap-south-1\n", encoding="utf-8")
    credentials.write_text("", encoding="utf-8")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    for key in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ROLE_ARN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        aws_preflight.shutil,
        "which",
        lambda name: "/usr/bin/aws" if name == "aws" else None,
    )
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return aws_preflight.subprocess.CompletedProcess(
            command, 0, stdout="aws-cli/2.39.1 Python/3.12", stderr=""
        )

    monkeypatch.setattr(aws_preflight.subprocess, "run", fake_run)
    assert aws_preflight.main([
        "--expected-account-id", "123456789012", "--skip-github"
    ]) == 3
    assert commands == [["aws", "--version"]]
    assert "AWS SAM CLI is required" in capsys.readouterr().err


def test_github_environment_check_requires_reviewer_and_exact_main_branch(monkeypatch):
    class Process:
        def __init__(self, returncode, stdout=""):
            self.returncode = returncode
            self.stdout = stdout

    def fake_run(command, **_kwargs):
        if command[1:3] == ["auth", "status"]:
            return Process(0)
        if command[1:3] == ["api", "repos/bharathselvas/sharebite/environments"]:
            return Process(0, json.dumps([
                {
                    "name": "aws-demo",
                    "protection_rules": [{
                        "type": "required_reviewers",
                        "reviewers": [{"type": "User", "id": 1}],
                    }],
                },
                {"name": "aws-demo-review", "protection_rules": []},
            ]))
        if command[1:3] == ["api", "repos/bharathselvas/sharebite/environments/aws-demo/variables"]:
            return Process(0, json.dumps({"variables": [
            {"name": "AWS_REGION", "value": "ap-south-1"},
            {"name": "AWS_ACCOUNT_ID", "value": "123456789012"},
            {"name": "AWS_DEPLOY_ROLE_ARN", "value": "arn:aws:iam::123456789012:role/sharebite-github-deploy"},
            {"name": "CFN_EXECUTION_ROLE_ARN", "value": "arn:aws:iam::123456789012:role/sharebite-cloudformation-execution"},
            {"name": "RUNTIME_PERMISSIONS_BOUNDARY_ARN", "value": "arn:aws:iam::123456789012:policy/sharebite-lambda-runtime-boundary"},
            {"name": "SAM_ARTIFACT_BUCKET", "value": "sharebite-123456789012-ap-south-1-artifacts"},
            ]}))
        if command[1:3] == ["api", "repos/bharathselvas/sharebite/environments/aws-demo-review/variables"]:
            return Process(0, json.dumps({"variables": [
            {"name": "AWS_REGION", "value": "ap-south-1"},
            {"name": "AWS_ACCOUNT_ID", "value": "123456789012"},
            {"name": "AWS_REVIEW_ROLE_ARN", "value": "arn:aws:iam::123456789012:role/sharebite-github-review"},
            ]}))
        environment = command[2].split("/")[4]
        return Process(0, json.dumps({
            "branch_policies": [{"name": "main", "type": "branch"}]
        }))

    import json

    monkeypatch.setattr(aws_preflight.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(aws_preflight.subprocess, "run", fake_run)
    report = Report(account_id="123456789012")
    aws_preflight._check_github_environments(
        report,
        expected_artifact_bucket="sharebite-123456789012-ap-south-1-artifacts",
        boundary_arn="arn:aws:iam::123456789012:policy/sharebite-lambda-runtime-boundary",
        deploy_role_name="sharebite-github-deploy",
        review_role_name="sharebite-github-review",
        execution_role_name="sharebite-cloudformation-execution",
    )
    assert report.exit_code == 0
    assert any(check.name == "GitHub environment aws-demo reviewers" and check.status == "passed" for check in report.checks)
    branch_checks = [check for check in report.checks if "branch policy" in check.name]
    assert len(branch_checks) == 2
    assert all(check.status == "passed" for check in branch_checks)
    variable_checks = [check for check in report.checks if "variables" in check.name]
    assert len(variable_checks) == 2
    assert all(check.status == "passed" for check in variable_checks)
