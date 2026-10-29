#!/usr/bin/env python3
"""Read-only AWS and GitHub prerequisite checks for ShareBite."""

from __future__ import annotations

import argparse
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote

REGION = "ap-south-1"
REPOSITORY = "bharathselvas/sharebite"
STACK_NAME = "smart-food-demo"
PROJECT_NAME = "smart-food-demo"
DEPLOY_ROLE_NAME = "sharebite-github-deploy"
REVIEW_ROLE_NAME = "sharebite-github-review"
EXECUTION_ROLE_NAME = "sharebite-cloudformation-execution"
BOUNDARY_POLICY_NAME = "sharebite-lambda-runtime-boundary"
RUNTIME_RESOURCE_IDS = ("LambdaExecutionRole", "ETLExecutionRole")
REQUIRED_OUTPUTS = {
    "ApiBaseUrl",
    "FrontendUrl",
    "FrontendDistributionId",
    "FrontendBucketName",
    "DonationsTableName",
    "AnalyticsBucketName",
    "LambdaFunctionName",
    "ETLFunctionName",
    "CognitoUserPoolId",
    "CognitoAppClientId",
    "CognitoIssuer",
    "CognitoHostedUi",
}

MISSING_CODES = {
    "NoSuchEntity",
    "NoSuchBucket",
    "ResourceNotFoundException",
    "ResourceNotFound",
    "NoSuchPublicAccessBlockConfiguration",
    "ServerSideEncryptionConfigurationNotFoundError",
    "OwnershipControlsNotFoundError",
    "NoSuchLifecycleConfiguration",
}
AUTH_CODES = {
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "InvalidIdentityToken",
    "InvalidGrantException",
    "SSOProviderInvalidToken",
    "UnauthorizedSSOTokenError",
    "UnrecognizedClientException",
}
DENIED_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
    "NotAuthorizedException",
    "AuthorizationError",
}


@dataclass
class CommandResult:
    ok: bool
    data: dict = field(default_factory=dict)
    code: str = ""
    message: str = ""


class Runner(Protocol):
    def run(self, args: list[str], region: str, profile: str) -> CommandResult: ...


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    account_id: str | None = None
    region: str = REGION
    local_errors: list[str] = field(default_factory=list)
    auth_or_permission_errors: list[str] = field(default_factory=list)
    missing_prerequisites: list[str] = field(default_factory=list)
    uncertain_results: list[str] = field(default_factory=list)
    manual_reviews: list[str] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str) -> None:
        self.checks.append(Check(name, status, detail))
        if status in {"missing", "configuration"}:
            self.missing_prerequisites.append(f"{name}: {detail}")
        elif status == "denied":
            self.auth_or_permission_errors.append(f"{name}: {detail}")
        elif status == "uncertain":
            self.uncertain_results.append(f"{name}: {detail}")

    @property
    def exit_code(self) -> int:
        if self.local_errors:
            return 3
        if self.auth_or_permission_errors or self.uncertain_results:
            return 2
        if self.missing_prerequisites:
            return 1
        return 0

    def as_dict(self) -> dict:
        remaining_checklist = list(
            dict.fromkeys(
                [
                    *self.local_errors,
                    *self.missing_prerequisites,
                    *self.auth_or_permission_errors,
                    *self.uncertain_results,
                    *self.manual_reviews,
                ]
            )
        )
        return {
            "account_id": self.account_id,
            "region": self.region,
            "checks": [asdict(check) for check in self.checks],
            "missing_prerequisites": self.missing_prerequisites,
            "denied_permissions_or_authentication": self.auth_or_permission_errors,
            "uncertain_results": self.uncertain_results,
            "manual_reviews": self.manual_reviews,
            "remaining_checklist": remaining_checklist,
            "exit_code": self.exit_code,
        }


class AwsCli:
    def run(self, args: list[str], region: str, profile: str) -> CommandResult:
        command = ["aws"]
        if profile:
            command.extend(["--profile", profile])
        command_region = "us-east-1" if args and args[0] == "cloudfront" else region
        command.extend(["--region", command_region, "--no-cli-pager", "--output", "json"])
        command.extend(args)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError as error:
            raise RuntimeError("AWS CLI was not found on PATH.") from error
        except subprocess.TimeoutExpired:
            return CommandResult(False, code="ReadTimeout")
        if completed.returncode:
            return CommandResult(
                False,
                code=aws_error_code(completed.stderr),
                message=completed.stderr[:1000],
            )
        try:
            return CommandResult(True, data=json.loads(completed.stdout or "{}"))
        except json.JSONDecodeError:
            return CommandResult(False, code="InvalidJsonResponse")


def aws_error_code(stderr: str) -> str:
    match = re.search(r"\(([^)]+)\)\s+when calling", stderr)
    if match:
        return match.group(1)
    for code in sorted(AUTH_CODES | DENIED_CODES | MISSING_CODES, key=len, reverse=True):
        if code in stderr:
            return code
    return "AwsCliError"


def profile_sso_status(
    profile: str,
    *,
    config_path: Path | None = None,
    credentials_path: Path | None = None,
    expected_account_id: str | None = None,
) -> tuple[bool, str]:
    if not profile or profile == "default":
        return False, "Use a named AWS IAM Identity Center SSO profile, not the default chain."
    credential_environment = {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ROLE_ARN",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    }
    if credential_environment.intersection(os.environ):
        return False, "AWS credential environment variables are set; unset them and use the named SSO profile."
    if any(
        name == "AWS_ENDPOINT_URL" or name.startswith("AWS_ENDPOINT_URL_")
        for name in os.environ
    ):
        return False, "AWS endpoint override environment variables are set; unset them before preflight."
    config_file = config_path or Path(
        os.environ.get("AWS_CONFIG_FILE", Path.home() / ".aws" / "config")
    )
    credentials_file = credentials_path or Path(
        os.environ.get("AWS_SHARED_CREDENTIALS_FILE", Path.home() / ".aws" / "credentials")
    )
    config = configparser.RawConfigParser()
    credentials = configparser.RawConfigParser()
    try:
        if config_file.exists():
            config.read(config_file)
        if credentials_file.exists():
            credentials.read(credentials_file)
    except (configparser.Error, OSError):
        return False, "AWS profile files could not be parsed safely."

    section = "default" if profile == "default" else f"profile {profile}"
    if not config.has_section(section) and config.has_section(profile):
        section = profile
    if not config.has_section(section):
        return False, f"AWS profile {profile!r} is not configured in the AWS config file."

    static_keys = {"aws_access_key_id", "aws_secret_access_key", "aws_session_token"}
    if any(config.has_option(section, key) for key in static_keys):
        return False, "Static AWS credentials are configured in this profile; use IAM Identity Center SSO."
    if credentials.has_section(profile) and any(
        credentials.has_option(profile, key) for key in static_keys
    ):
        return False, "Static credentials are configured for this profile; use IAM Identity Center SSO."
    alternate_providers = {
        "credential_process",
        "credential_source",
        "role_arn",
        "source_profile",
    }
    if any(config.has_option(section, key) for key in alternate_providers):
        return False, "The profile uses a non-SSO or chained credential provider; use a direct IAM Identity Center SSO profile."

    has_start_url = (
        config.has_option(section, "sso_start_url")
        and config.has_option(section, "sso_region")
        and config.has_option(section, "sso_account_id")
        and config.has_option(section, "sso_role_name")
    )
    session_name = (
        config.get(section, "sso_session", fallback="")
        if config.has_option(section, "sso_session")
        else ""
    )
    if session_name:
        session_section = f"sso-session {session_name}"
        has_start_url = has_start_url or (
            config.has_section(session_section)
            and config.has_option(session_section, "sso_start_url")
            and config.has_option(session_section, "sso_region")
            and config.has_option(section, "sso_account_id")
            and config.has_option(section, "sso_role_name")
        )
    if not has_start_url:
        return False, f"AWS profile {profile!r} is not configured for IAM Identity Center SSO."
    profile_account_id = config.get(section, "sso_account_id", fallback="")
    if not re.fullmatch(r"\d{12}", profile_account_id):
        return False, f"AWS profile {profile!r} does not specify a valid SSO account ID."
    if expected_account_id and profile_account_id != expected_account_id:
        return False, "The profile's SSO account ID does not match --expected-account-id."
    return True, "Profile is configured for IAM Identity Center SSO without static credential fields."


def status_for_error(code: str, missing_codes: set[str] | None = None) -> str:
    if code in AUTH_CODES:
        return "denied"
    if code in DENIED_CODES:
        return "denied"
    if code in (missing_codes or MISSING_CODES):
        return "missing"
    return "uncertain"


def _call(
    report: Report,
    runner: Runner,
    name: str,
    args: list[str],
    profile: str,
    *,
    missing_codes: set[str] | None = None,
    missing_validation_error: bool = False,
) -> dict | None:
    try:
        result = runner.run(args, report.region, profile)
    except RuntimeError as error:
        report.local_errors.append(str(error))
        report.add(name, "configuration", str(error))
        return None
    if result.ok:
        report.add(name, "passed", "Read-only request succeeded.")
        return result.data
    if (
        missing_validation_error
        and result.code == "ValidationError"
        and "does not exist" in result.message.lower()
    ):
        status = "missing"
    else:
        status = status_for_error(result.code, missing_codes)
    detail = (
        f"AWS returned {result.code}; access was not inferred from this failed read."
    )
    report.add(name, status, detail)
    return None


def _check_trust(
    role: dict,
    expected_provider: str,
    environment: str | None,
    account_id: str,
) -> tuple[bool, str]:
    document = role.get("AssumeRolePolicyDocument")
    if isinstance(document, str):
        try:
            document = json.loads(unquote(document))
        except json.JSONDecodeError:
            return False, "Role trust policy could not be decoded."
    if not isinstance(document, dict):
        return False, "Role trust policy was not returned."
    statements = document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    for statement in statements:
        if statement.get("Effect") != "Allow":
            continue
        principal = statement.get("Principal", {})
        condition = statement.get("Condition", {})
        string_equals = condition.get("StringEquals", {})
        string_like = condition.get("StringLike", {})
        if environment:
            federated = principal.get("Federated")
            if (
                federated == expected_provider
                and "sts:AssumeRoleWithWebIdentity" in _as_list(statement.get("Action"))
                and string_equals.get("token.actions.githubusercontent.com:aud") == "sts.amazonaws.com"
                and (
                    string_equals.get("token.actions.githubusercontent.com:sub")
                    == f"repo:{REPOSITORY}:environment:{environment}"
                    or string_like.get("token.actions.githubusercontent.com:sub")
                    == f"repo:{REPOSITORY}:environment:{environment}"
                )
            ):
                return True, f"Trust is scoped to {REPOSITORY} / {environment}."
        elif (
            principal.get("Service") == "cloudformation.amazonaws.com"
            and "sts:AssumeRole" in _as_list(statement.get("Action"))
        ):
            source_arn = condition.get("ArnLike", {}).get("aws:SourceArn")
            source_account = string_equals.get("aws:SourceAccount")
            expected_source_arn = (
                f"arn:aws:cloudformation:{REGION}:{account_id}:"
                f"stack/{STACK_NAME}/*"
            )
            if source_arn == expected_source_arn and source_account == account_id:
                return True, "CloudFormation trust is scoped to the expected account and stack."
            return False, "CloudFormation trust must constrain aws:SourceAccount and the ShareBite stack ARN."
    return False, "Trust policy does not match the required principal, audience, and environment subject."


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value] if value is not None else []


def _check_role(
    report: Report,
    runner: Runner,
    profile: str,
    role_name: str,
    *,
    provider_arn: str = "",
    environment: str | None = None,
    account_id: str,
) -> dict | None:
    role_response = _call(
        report,
        runner,
        f"IAM role {role_name}",
        ["iam", "get-role", "--role-name", role_name],
        profile,
    )
    if not role_response:
        return None
    role = role_response.get("Role", {})
    trusted, detail = _check_trust(role, provider_arn, environment, account_id)
    report.add(f"IAM trust {role_name}", "passed" if trusted else "configuration", detail)
    return role


def _check_bucket(
    report: Report,
    runner: Runner,
    profile: str,
    bucket: str,
    *,
    expected_region: str,
    require_artifact_lifecycle: bool = False,
) -> None:
    location = _call(
        report,
        runner,
        f"S3 bucket {bucket} existence",
        ["s3api", "get-bucket-location", "--bucket", bucket],
        profile,
    )
    if location is None:
        return
    location_region = location.get("LocationConstraint") or "us-east-1"
    region_ok = location_region == expected_region
    report.add(
        f"S3 bucket {bucket} region",
        "passed" if region_ok else "configuration",
        f"Bucket is in {location_region}; expected {expected_region}.",
    )
    if not region_ok:
        report.missing_prerequisites.append(f"Bucket {bucket} is in the wrong region.")

    public = _call(
        report, runner, f"S3 bucket {bucket} public access block",
        ["s3api", "get-public-access-block", "--bucket", bucket], profile,
    )
    if public is not None:
        settings = public.get("PublicAccessBlockConfiguration", {})
        secure = all(
            settings.get(key) is True
            for key in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")
        )
        report.add(
            f"S3 bucket {bucket} public access",
            "passed" if secure else "configuration",
            "All four account-level bucket public-access blocks are enabled."
            if secure else "Enable all four S3 Block Public Access settings.",
        )
        if not secure:
            report.missing_prerequisites.append(f"S3 bucket {bucket} is not fully blocked from public access.")

    encryption = _call(
        report, runner, f"S3 bucket {bucket} encryption",
        ["s3api", "get-bucket-encryption", "--bucket", bucket], profile,
        missing_codes=MISSING_CODES | {"ServerSideEncryptionConfigurationNotFoundError"},
    )
    if encryption is not None:
        algorithms = {
            rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm")
            for rule in encryption.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
        }
        secure = "AES256" in algorithms
        report.add(
            f"S3 bucket {bucket} encryption",
            "passed" if secure else "configuration",
            "Default SSE-S3 encryption is enabled."
            if secure else "Deployment requires default SSE-S3 (AES256) encryption.",
        )
        if not secure:
            report.missing_prerequisites.append(f"S3 bucket {bucket} encryption is not deployment-compatible.")

    ownership = _call(
        report, runner, f"S3 bucket {bucket} ownership controls",
        ["s3api", "get-bucket-ownership-controls", "--bucket", bucket], profile,
    )
    if ownership is not None:
        owner_enforced = any(
            rule.get("ObjectOwnership") == "BucketOwnerEnforced"
            for rule in ownership.get("OwnershipControls", {}).get("Rules", [])
        )
        report.add(
            f"S3 bucket {bucket} ownership",
            "passed" if owner_enforced else "configuration",
            "BucketOwnerEnforced is configured."
            if owner_enforced else "Configure S3 Object Ownership as BucketOwnerEnforced.",
        )
        if not owner_enforced:
            report.missing_prerequisites.append(f"S3 bucket {bucket} ownership controls are not deployment-compatible.")

    if require_artifact_lifecycle:
        lifecycle = _call(
            report, runner, f"S3 bucket {bucket} lifecycle",
            ["s3api", "get-bucket-lifecycle-configuration", "--bucket", bucket], profile,
            missing_codes=MISSING_CODES | {"NoSuchLifecycleConfiguration"},
        )
    else:
        lifecycle = None
    if lifecycle is not None:
        has_expiry = any(
            rule.get("Status") == "Enabled"
            and rule.get("Expiration", {}).get("Days", 0) > 0
            and (
                rule.get("Filter", {}).get("Prefix") == "sharebite/artifacts/"
                or rule.get("Prefix") == "sharebite/artifacts/"
            )
            for rule in lifecycle.get("Rules", [])
        )
        report.add(
            f"S3 bucket {bucket} artifact lifecycle",
            "passed" if has_expiry else "configuration",
            "An enabled expiration rule covers sharebite/artifacts/."
            if has_expiry else "Add a reviewed expiration rule for sharebite/artifacts/.",
        )
        if not has_expiry:
            report.missing_prerequisites.append(
                f"Artifact bucket {bucket} has no scoped lifecycle expiry."
            )


def _check_github_environments(
    report: Report,
    *,
    expected_artifact_bucket: str | None,
    boundary_arn: str | None,
    deploy_role_name: str,
    review_role_name: str,
    execution_role_name: str,
) -> None:
    gh = shutil.which("gh")
    if not gh:
        report.add("GitHub environments", "uncertain", "GitHub CLI is not installed; environment protections were not checked.")
        return
    status = subprocess.run(
        [gh, "auth", "status"], capture_output=True, text=True, timeout=20, check=False
    )
    if status.returncode:
        report.add("GitHub environments", "uncertain", "GitHub CLI is not authenticated; environment protections were not checked.")
        return
    result = subprocess.run(
        [
            gh, "api", f"repos/{REPOSITORY}/environments",
            "--jq", ".environments",
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode:
        report.add("GitHub environments", "uncertain", "Could not read repository environments; verify GitHub Actions read access.")
        return
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        report.add("GitHub environments", "uncertain", "GitHub returned an unreadable environment list.")
        return
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        report.add("GitHub environments", "uncertain", "GitHub returned an unexpected environment-list shape.")
        return
    environments = {item.get("name"): item for item in data}
    expected_variables = {
        "aws-demo": {
            "AWS_REGION": REGION,
            "AWS_ACCOUNT_ID": report.account_id,
            "RUNTIME_PERMISSIONS_BOUNDARY_ARN": boundary_arn,
            "SAM_ARTIFACT_BUCKET": expected_artifact_bucket,
        },
        "aws-demo-review": {
            "AWS_REGION": REGION,
            "AWS_ACCOUNT_ID": report.account_id,
        },
    }
    role_variables = {
        "aws-demo": {
            "AWS_DEPLOY_ROLE_ARN": deploy_role_name,
            "CFN_EXECUTION_ROLE_ARN": execution_role_name,
        },
        "aws-demo-review": {"AWS_REVIEW_ROLE_ARN": review_role_name},
    }
    for environment in ("aws-demo", "aws-demo-review"):
        item = environments.get(environment)
        if item is None:
            report.add(f"GitHub environment {environment}", "missing", "Environment does not exist.")
            continue
        variable_result = subprocess.run(
            [
                gh,
                "api",
                f"repos/{REPOSITORY}/environments/{environment}/variables",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if variable_result.returncode:
            report.add(
                f"GitHub environment {environment} variables",
                "uncertain",
                "Could not read environment variables; verify GitHub Actions variable read access.",
            )
        else:
            try:
                variable_data = json.loads(variable_result.stdout)
                if not isinstance(variable_data, dict) or not isinstance(
                    variable_data.get("variables"), list
                ):
                    raise ValueError("Unexpected environment-variable response shape.")
                actual_variables = {
                    variable.get("name"): variable.get("value")
                    for variable in variable_data.get("variables", [])
                }
                expected = expected_variables[environment]
                required_names = set(expected) | set(role_variables[environment])
                missing_variables = [
                    name for name in required_names
                    if name not in actual_variables
                ]
                mismatched_variables = [
                    name for name, value in expected.items()
                    if value is not None
                    and name in actual_variables
                    and actual_variables[name] != value
                ]
                for name, role_name in role_variables[environment].items():
                    if name not in actual_variables:
                        continue
                    role_arn = actual_variables[name]
                    role_arn_pattern = (
                        rf"arn:aws:iam::{re.escape(str(report.account_id))}:"
                        r"role/[A-Za-z0-9+=,.@_/-]+"
                    )
                    if not re.fullmatch(role_arn_pattern, role_arn) or not role_arn.endswith(
                        f"/{role_name}"
                    ):
                        mismatched_variables.append(name)
                valid_variables = not missing_variables and not mismatched_variables
                detail = "Required environment variables are present and match the checked account/region/resources."
                if missing_variables:
                    detail += " Missing: " + ", ".join(sorted(missing_variables)) + "."
                if mismatched_variables:
                    detail += " Mismatched: " + ", ".join(sorted(mismatched_variables)) + "."
                report.add(
                    f"GitHub environment {environment} variables",
                    "passed" if valid_variables else "configuration",
                    detail,
                )
            except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
                report.add(
                    f"GitHub environment {environment} variables",
                    "uncertain",
                    "GitHub returned an unreadable environment-variable response.",
                )
        rules = item.get("protection_rules", [])
        if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
            report.add(
                f"GitHub environment {environment} reviewers",
                "uncertain",
                "GitHub returned an unexpected protection-rules shape.",
            )
            rules = []
        reviewers = [
            reviewer for rule in rules if rule.get("type") == "required_reviewers"
            for reviewer in rule.get("reviewers", [])
        ]
        if environment == "aws-demo" and not reviewers:
            report.add(
                f"GitHub environment {environment} reviewers",
                "configuration",
                "No required independent reviewer was returned; configure required reviewers.",
            )
        elif environment == "aws-demo":
            report.add(
                f"GitHub environment {environment} reviewers",
                "passed",
                "At least one required reviewer is configured; self-review prevention remains a manual check.",
            )
            report.manual_reviews.append("Confirm aws-demo prevents self-approval where available.")
        else:
            report.add(
                f"GitHub environment {environment}",
                "passed",
                "Environment exists; verify the review role is read-only.",
            )
        policy_result = subprocess.run(
            [
                gh,
                "api",
                f"repos/{REPOSITORY}/environments/{environment}/deployment-branch-policies",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if policy_result.returncode:
            report.add(
                f"GitHub environment {environment} branch policy",
                "uncertain",
                "Could not read the environment's allowed deployment branches.",
            )
            continue
        try:
            policy_data = json.loads(policy_result.stdout)
        except json.JSONDecodeError:
            report.add(
                f"GitHub environment {environment} branch policy",
                "uncertain",
                "GitHub returned an unreadable deployment branch policy.",
            )
            continue
        if not isinstance(policy_data, dict) or not isinstance(
            policy_data.get("branch_policies"), list
        ):
            report.add(
                f"GitHub environment {environment} branch policy",
                "uncertain",
                "GitHub returned an unexpected deployment branch policy shape.",
            )
            continue
        branch_policies = policy_data["branch_policies"]
        main_only = (
            len(branch_policies) == 1
            and branch_policies[0].get("name") == "main"
            and branch_policies[0].get("type") == "branch"
        )
        if not main_only:
            report.add(
                f"GitHub environment {environment} branch policy",
                "configuration",
                "The environment is not explicitly restricted to the single main branch.",
            )
        else:
            report.add(
                f"GitHub environment {environment} branch policy",
                "passed",
                "Only the main branch is allowed to deploy to this environment.",
            )


def run_preflight(
    runner: Runner,
    *,
    profile: str,
    expected_account_id: str | None,
    artifact_bucket: str | None,
    deploy_role_name: str = DEPLOY_ROLE_NAME,
    review_role_name: str = REVIEW_ROLE_NAME,
    execution_role_name: str = EXECUTION_ROLE_NAME,
    boundary_arn: str | None = None,
    region: str = REGION,
    check_github: bool = True,
) -> Report:
    report = Report(region=region)
    identity = _call(
        report, runner, "AWS caller identity",
        ["sts", "get-caller-identity"], profile,
    )
    if identity is None:
        return report
    account_id = identity.get("Account", "")
    caller_arn = identity.get("Arn", "")
    if not re.fullmatch(r"\d{12}", account_id):
        report.add("AWS caller account", "uncertain", "AWS did not return a valid 12-digit account ID.")
        report.uncertain_results.append("Caller account ID could not be validated.")
        return report
    report.account_id = account_id
    if caller_arn.endswith(":root"):
        report.add(
            "AWS caller identity safety",
            "configuration",
            "The active identity is the account root user; do not use it for project bootstrap or deployment.",
        )
        report.local_errors.append("Root identity is not an allowed ShareBite deployment/bootstrap identity.")
    if expected_account_id and account_id != expected_account_id:
        report.add(
            "Expected AWS account",
            "configuration",
            f"Active account {account_id} does not match the explicitly expected account.",
        )
        report.local_errors.append("Active AWS account differs from --expected-account-id.")
    else:
        report.add("Expected AWS account", "passed", "Active account matches the configured expectation.")
    if region != REGION:
        report.add(
            "AWS deployment region",
            "configuration",
            f"Configured region is {region}; this project targets {REGION}.",
        )
        report.local_errors.append(f"Region must be {REGION}.")

    if not artifact_bucket:
        report.add("Artifact bucket configuration", "configuration", "Pass --artifact-bucket or set SAM_ARTIFACT_BUCKET; no name is assumed.")
        report.local_errors.append("A reviewed SAM_ARTIFACT_BUCKET value is required.")
    if not boundary_arn:
        report.add("Runtime boundary configuration", "configuration", "Pass --boundary-arn or set RUNTIME_PERMISSIONS_BOUNDARY_ARN.")
        report.local_errors.append("A pre-created runtime permissions boundary ARN is required.")

    oidc_list = _call(
        report, runner, "IAM OIDC provider listing",
        ["iam", "list-open-id-connect-providers"], profile,
    )
    provider_arn = f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com"
    provider_exists = False
    if oidc_list is not None:
        provider_exists = any(
            provider.get("Arn") == provider_arn
            for provider in oidc_list.get("OpenIDConnectProviderList", [])
        )
        report.add(
            "GitHub OIDC provider",
            "passed" if provider_exists else "missing",
            "GitHub Actions OIDC provider exists."
            if provider_exists else "Create the account-level GitHub OIDC provider through an administrator-reviewed step.",
        )
    if provider_exists:
        provider = _call(
            report, runner, "GitHub OIDC provider configuration",
            ["iam", "get-open-id-connect-provider", "--open-id-connect-provider-arn", provider_arn],
            profile,
        )
        if provider is not None:
            configured = "sts.amazonaws.com" in provider.get("ClientIDList", [])
            report.add(
                "GitHub OIDC audience",
                "passed" if configured else "configuration",
                "sts.amazonaws.com is an allowed audience."
                if configured else "Add sts.amazonaws.com to the provider client ID list.",
            )
            if not configured:
                report.missing_prerequisites.append("GitHub OIDC provider has no sts.amazonaws.com audience.")

    if artifact_bucket and not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", artifact_bucket):
        report.add("Artifact bucket name", "configuration", "Bucket name does not satisfy S3 naming syntax.")
        report.local_errors.append("Invalid artifact bucket name.")
    elif artifact_bucket:
        _check_bucket(
            report, runner, profile, artifact_bucket,
            expected_region=REGION, require_artifact_lifecycle=True,
        )
    _check_bucket(
        report, runner, profile,
        f"sharebite-{account_id}-{REGION}-analytics",
        expected_region=REGION,
    )
    _check_bucket(
        report, runner, profile,
        f"sharebite-{account_id}-{REGION}-frontend",
        expected_region=REGION,
    )

    _check_role(
        report, runner, profile, deploy_role_name,
        provider_arn=provider_arn, environment="aws-demo", account_id=account_id,
    )
    _check_role(
        report, runner, profile, review_role_name,
        provider_arn=provider_arn, environment="aws-demo-review", account_id=account_id,
    )
    _check_role(
        report, runner, profile, execution_role_name,
        account_id=account_id,
    )
    if boundary_arn:
        if not re.fullmatch(rf"arn:aws:iam::{account_id}:policy/[A-Za-z0-9+=,.@_/-]+", boundary_arn):
            report.add("Lambda runtime permissions boundary", "configuration", "Boundary ARN must be an IAM policy in the active account.")
            report.local_errors.append("Runtime boundary ARN is malformed or in a different AWS account.")
        else:
            boundary = _call(
                report, runner, "Lambda runtime permissions boundary",
                ["iam", "get-policy", "--policy-arn", boundary_arn], profile,
            )
            if boundary is not None:
                report.add(
                    "Lambda runtime permissions boundary",
                    "passed",
                    "Configured policy exists; its effective permissions still require manual review.",
                )
                report.manual_reviews.append("Review the boundary's default policy version and confirm it is no broader than the two runtime role policies.")

    stack = _call(
        report, runner, f"CloudFormation stack {STACK_NAME}",
        ["cloudformation", "describe-stacks", "--stack-name", STACK_NAME], profile,
        missing_validation_error=True,
    )
    stack_outputs: dict[str, str] = {}
    if stack is not None:
        stacks = stack.get("Stacks", [])
        if len(stacks) != 1 or stacks[0].get("StackName") != STACK_NAME:
            report.add("CloudFormation stack identity", "uncertain", "DescribeStacks returned an unexpected stack response.")
        else:
            item = stacks[0]
            report.add(
                "CloudFormation stack status",
                "passed" if item.get("StackStatus") in {"CREATE_COMPLETE", "UPDATE_COMPLETE"} else "configuration",
                f"Stack status is {item.get('StackStatus')}.",
            )
            if item.get("StackStatus") not in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
                report.missing_prerequisites.append("Stack is not in a stable successful state.")
            if item.get("EnableTerminationProtection") is not True:
                report.add("CloudFormation termination protection", "configuration", "Termination protection is not enabled.")
            else:
                report.add("CloudFormation termination protection", "passed", "Stack termination protection is enabled.")
            stack_outputs = {
                output["OutputKey"]: output.get("OutputValue", "")
                for output in item.get("Outputs", [])
                if "OutputKey" in output
            }
            missing_outputs = REQUIRED_OUTPUTS - stack_outputs.keys()
            report.add(
                "CloudFormation required outputs",
                "passed" if not missing_outputs else "configuration",
                "All expected deployment outputs are present."
                if not missing_outputs else "Missing outputs: " + ", ".join(sorted(missing_outputs)),
            )
            if missing_outputs:
                report.missing_prerequisites.append("CloudFormation stack outputs are incomplete.")

            resources = _call(
                report, runner, "CloudFormation stack resources",
                ["cloudformation", "list-stack-resources", "--stack-name", STACK_NAME],
                profile,
            )
            if resources is not None:
                failures = [
                    resource.get("LogicalResourceId", "unknown")
                    for resource in resources.get("StackResourceSummaries", [])
                    if resource.get("ResourceStatus", "").endswith("_IN_PROGRESS")
                    or resource.get("ResourceStatus", "").endswith("_FAILED")
                ]
                report.add(
                    "CloudFormation resource statuses",
                    "configuration" if failures else "passed",
                    "Unstable or failed resources: " + ", ".join(failures)
                    if failures else "No stack resources are in a failed or in-progress state.",
                )
                if failures:
                    report.missing_prerequisites.append("CloudFormation contains failed or in-progress resources.")
    else:
        # A missing stack is already classified from the AWS error code; continue
        # inspecting independent prerequisites without interpreting denied reads as absence.
        pass

    table_name = f"{PROJECT_NAME}-donations"
    table = _call(
        report, runner, f"DynamoDB table {table_name}",
        ["dynamodb", "describe-table", "--table-name", table_name], profile,
    )
    if table is not None:
        description = table.get("Table", {})
        table_ok = description.get("TableStatus") == "ACTIVE"
        indexes = {
            index.get("IndexName") for index in description.get("GlobalSecondaryIndexes", [])
        }
        expected_indexes = {
            "status-index", "donor-index", "recipient-index", "entity-index", "expiry-index",
        }
        pitr = _call(
            report, runner, f"DynamoDB point-in-time recovery {table_name}",
            ["dynamodb", "describe-continuous-backups", "--table-name", table_name],
            profile,
        )
        pitr_status = (
            pitr.get("ContinuousBackupsDescription", {})
            .get("PointInTimeRecoveryDescription", {})
            .get("PointInTimeRecoveryStatus")
            if pitr
            else None
        )
        cost_aware_backup_setting = pitr_status == "DISABLED"
        good = table_ok and expected_indexes.issubset(indexes) and cost_aware_backup_setting
        report.add(
            f"DynamoDB table readiness {table_name}",
            "passed" if good else "configuration",
            "Table is ACTIVE with expected GSIs and PITR disabled as configured for the low-cost demo."
            if good else (
                "Check ACTIVE status, required GSIs, and PITR status; the template's low-cost "
                f"demo default is DISABLED (current status: {pitr_status or 'unknown'})."
            ),
        )
        if not good:
            report.missing_prerequisites.append(f"DynamoDB table {table_name} is not deployment-ready.")
        if pitr_status == "ENABLED":
            report.manual_reviews.append(
                "DynamoDB point-in-time recovery is enabled and may incur backup-storage charges; "
                "review the cost before using this demo stack."
            )

    _check_runtime_functions(report, runner, profile)
    _check_cognito(report, runner, profile)
    _check_api_and_cloudfront(report, runner, profile, stack_outputs)
    _check_runtime_boundaries(report, runner, profile, boundary_arn, stack)
    if check_github:
        _check_github_environments(
            report,
            expected_artifact_bucket=artifact_bucket,
            boundary_arn=boundary_arn,
            deploy_role_name=deploy_role_name,
            review_role_name=review_role_name,
            execution_role_name=execution_role_name,
        )
    report.manual_reviews.extend(
        [
            "Review current AWS account-plan eligibility, credits, regional pricing, ancillary service charges, and cleanup; this tool does not verify billing.",
            "Validate policies/cloudformation-execution-role-candidate.json with IAM Access Analyzer and target-account simulation against the exact SAM transform; this preflight checks role trust/existence, not policy contents.",
            "Review deployment, review, and runtime role permission documents against the SAM-transformed template; existence checks do not prove least privilege.",
            "Confirm the approved GitHub variables match the verified account, region, role ARNs, boundary ARN, and artifact bucket.",
            "Confirm the designated artifact bucket is owned by the intended AWS account; bucket configuration reads alone do not prove ownership.",
        ]
    )
    return report


def _check_runtime_functions(report: Report, runner: Runner, profile: str) -> None:
    for function_name in (f"{PROJECT_NAME}-api", f"{PROJECT_NAME}-etl"):
        config = _call(
            report, runner, f"Lambda function {function_name}",
            ["lambda", "get-function-configuration", "--function-name", function_name],
            profile,
        )
        if config is not None:
            valid = config.get("State") == "Active" and config.get("Runtime") == "python3.12"
            report.add(
                f"Lambda function readiness {function_name}",
                "passed" if valid else "configuration",
                "Function is Active on Python 3.12."
                if valid else f"Function state/runtime is {config.get('State')}/{config.get('Runtime')}.",
            )
            if not valid:
                report.missing_prerequisites.append(f"Lambda function {function_name} is not ready.")


def _check_cognito(report: Report, runner: Runner, profile: str) -> None:
    token = None
    pools = []
    while True:
        args = ["cognito-idp", "list-user-pools", "--max-results", "60"]
        if token:
            args.extend(["--next-token", token])
        result = _call(report, runner, "Cognito user-pool listing", args, profile)
        if result is None:
            return
        pools.extend(result.get("UserPools", []))
        token = result.get("NextToken")
        if not token:
            break
    matches = [pool for pool in pools if pool.get("Name") == f"{PROJECT_NAME}-users"]
    report.add(
        "Cognito user pool",
        "passed" if len(matches) == 1 else "missing",
        "Exactly one ShareBite user pool exists."
        if len(matches) == 1 else f"Expected one {PROJECT_NAME}-users pool; found {len(matches)}.",
    )
    if len(matches) == 1:
        groups = _call(
            report, runner, "Cognito application groups",
            ["cognito-idp", "list-groups", "--user-pool-id", matches[0]["Id"]],
            profile,
        )
        if groups is not None:
            actual = {group.get("GroupName") for group in groups.get("Groups", [])}
            required = {"food-donors", "food-ngos", "food-admins"}
            valid = required.issubset(actual)
            report.add(
                "Cognito role groups",
                "passed" if valid else "configuration",
                "All expected authorization groups exist."
                if valid else "Missing groups: " + ", ".join(sorted(required - actual)),
            )
            if not valid:
                report.missing_prerequisites.append("Cognito authorization groups are incomplete.")


def _check_api_and_cloudfront(
    report: Report,
    runner: Runner,
    profile: str,
    outputs: dict[str, str],
) -> None:
    api_base = outputs.get("ApiBaseUrl", "")
    api_match = re.match(r"https://([^.]+)\.execute-api\.", api_base)
    if api_match:
        api = _call(
            report, runner, "API Gateway HTTP API",
            ["apigatewayv2", "get-api", "--api-id", api_match.group(1)],
            profile,
        )
        if api is not None:
            valid = api.get("ProtocolType") == "HTTP"
            report.add(
                "API Gateway configuration",
                "passed" if valid else "configuration",
                "API Gateway HTTP API is present."
                if valid else "The stack output does not resolve to an HTTP API.",
            )
            if not valid:
                report.missing_prerequisites.append("API Gateway HTTP API configuration is invalid.")
    elif outputs:
        report.add("API Gateway output", "configuration", "ApiBaseUrl is missing or malformed.")
        report.missing_prerequisites.append("Cannot inspect API Gateway without a valid ApiBaseUrl stack output.")

    distribution_id = outputs.get("FrontendDistributionId")
    if distribution_id:
        distribution = _call(
            report, runner, "CloudFront frontend distribution",
            ["cloudfront", "get-distribution", "--id", distribution_id],
            profile,
        )
        if distribution is not None:
            config = distribution.get("Distribution", {}).get("DistributionConfig", {})
            behaviors = config.get("DefaultCacheBehavior", {})
            origins = config.get("Origins", {}).get("Items", [])
            valid = (
                config.get("Enabled") is True
                and behaviors.get("ViewerProtocolPolicy") == "redirect-to-https"
                and any(origin.get("OriginAccessControlId") for origin in origins)
            )
            report.add(
                "CloudFront HTTPS/private origin",
                "passed" if valid else "configuration",
                "Distribution is enabled, redirects to HTTPS, and uses an origin access control."
                if valid else "Review HTTPS redirect, enabled state, and private S3 origin access control.",
            )
            if not valid:
                report.missing_prerequisites.append("CloudFront distribution is not configured for the expected private HTTPS origin.")


def _check_runtime_boundaries(
    report: Report,
    runner: Runner,
    profile: str,
    boundary_arn: str | None,
    stack_response: dict | None,
) -> None:
    if not boundary_arn or not stack_response:
        return
    resources = _call(
        report, runner, "Runtime IAM roles in stack",
        ["cloudformation", "list-stack-resources", "--stack-name", STACK_NAME],
        profile,
    )
    if resources is None:
        return
    by_logical_id = {
        item.get("LogicalResourceId"): item
        for item in resources.get("StackResourceSummaries", [])
    }
    for logical_id in RUNTIME_RESOURCE_IDS:
        resource = by_logical_id.get(logical_id)
        if not resource or not resource.get("PhysicalResourceId"):
            report.add(f"Runtime boundary {logical_id}", "missing", "Runtime role was not found in the stack.")
            continue
        role_name = resource["PhysicalResourceId"].rsplit("/", 1)[-1]
        role_response = _call(
            report, runner, f"Runtime role boundary {role_name}",
            ["iam", "get-role", "--role-name", role_name], profile,
        )
        if role_response is None:
            continue
        actual = (
            role_response.get("Role", {})
            .get("PermissionsBoundary", {})
            .get("PermissionsBoundaryArn")
        )
        valid = actual == boundary_arn
        report.add(
            f"Runtime boundary {logical_id}",
            "passed" if valid else "configuration",
            "Runtime role uses the configured permissions boundary."
            if valid else "Runtime role permissions boundary does not match the configured ARN.",
        )
        if not valid:
            report.missing_prerequisites.append(f"Runtime role {role_name} does not use the configured permissions boundary.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="sharebite")
    parser.add_argument("--expected-account-id", default=os.environ.get("AWS_EXPECTED_ACCOUNT_ID"))
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--artifact-bucket", default=os.environ.get("SAM_ARTIFACT_BUCKET"))
    parser.add_argument("--boundary-arn", default=os.environ.get("RUNTIME_PERMISSIONS_BOUNDARY_ARN"))
    parser.add_argument("--deploy-role-name", default=os.environ.get("SHAREBITE_DEPLOY_ROLE_NAME", DEPLOY_ROLE_NAME))
    parser.add_argument("--review-role-name", default=os.environ.get("SHAREBITE_REVIEW_ROLE_NAME", REVIEW_ROLE_NAME))
    parser.add_argument("--execution-role-name", default=os.environ.get("SHAREBITE_EXECUTION_ROLE_NAME", EXECUTION_ROLE_NAME))
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--skip-github", action="store_true", help="Do not inspect GitHub environments.")
    return parser


def main(argv: list[str] | None = None, runner: Runner | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.region != REGION:
        print(f"Invalid region: ShareBite deployment region is fixed to {REGION}.", file=sys.stderr)
        return 3
    if not args.expected_account_id:
        print(
            "An explicit --expected-account-id (or AWS_EXPECTED_ACCOUNT_ID) is required.",
            file=sys.stderr,
        )
        return 3
    if args.expected_account_id and not re.fullmatch(r"\d{12}", args.expected_account_id):
        print("--expected-account-id must be exactly 12 digits.", file=sys.stderr)
        return 3
    if not shutil.which("aws") and runner is None:
        print("AWS CLI v2 is required but was not found on PATH.", file=sys.stderr)
        return 3
    if runner is None:
        try:
            version = subprocess.run(
                ["aws", "--version"], capture_output=True, text=True, timeout=10, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("Could not run AWS CLI version check.", file=sys.stderr)
            return 3
        version_text = f"{version.stdout}{version.stderr}"
        if version.returncode or not version_text.startswith("aws-cli/2"):
            print("AWS CLI v2 is required.", file=sys.stderr)
            return 3
        if not shutil.which("sam"):
            print("AWS SAM CLI is required but was not found on PATH.", file=sys.stderr)
            return 3
        try:
            sam_version = subprocess.run(
                ["sam", "--version"], capture_output=True, text=True, timeout=10, check=False
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print("Could not run AWS SAM CLI version check.", file=sys.stderr)
            return 3
        if sam_version.returncode or not sam_version.stdout.startswith("SAM CLI, version "):
            print("AWS SAM CLI version check failed.", file=sys.stderr)
            return 3
        sso_ok, sso_detail = profile_sso_status(
            args.profile,
            expected_account_id=args.expected_account_id,
        )
        if not sso_ok:
            print(f"Refusing AWS calls: {sso_detail}", file=sys.stderr)
            return 3

    try:
        report = run_preflight(
            runner or AwsCli(),
            profile=args.profile,
            expected_account_id=args.expected_account_id,
            artifact_bucket=args.artifact_bucket,
            deploy_role_name=args.deploy_role_name,
            review_role_name=args.review_role_name,
            execution_role_name=args.execution_role_name,
            boundary_arn=args.boundary_arn,
            region=args.region,
            check_github=not args.skip_github,
        )
    except (OSError, subprocess.SubprocessError) as error:
        print(f"Preflight could not complete: {error}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        print(f"ShareBite AWS read-only preflight — account={report.account_id or 'unknown'} region={report.region}")
        for check in report.checks:
            print(f"[{check.status.upper()}] {check.name}: {check.detail}")
        for title, items in (
            ("Missing prerequisites", report.missing_prerequisites),
            ("Denied permissions/authentication", report.auth_or_permission_errors),
            ("Uncertain results", report.uncertain_results),
            ("Manual review still required", report.manual_reviews),
        ):
            if items:
                print(f"\n{title}:")
                for item in items:
                    print(f"- {item}")
        checklist = report.as_dict()["remaining_checklist"]
        if checklist:
            print("\nRemaining checklist:")
            for item in checklist:
                    print(f"- [ ] {item}")
        print(f"\nExit code: {report.exit_code}")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
