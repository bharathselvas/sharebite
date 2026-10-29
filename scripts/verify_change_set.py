#!/usr/bin/env python3
"""Verify a reviewed CloudFormation change set belongs to the expected ShareBite stack."""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

STABLE_STACK_STATUSES = {
    "CREATE_COMPLETE",
    "UPDATE_COMPLETE",
    "UPDATE_ROLLBACK_COMPLETE",
}
ALLOWED_RESOURCE_TYPES = {
    "AWS::ApiGatewayV2::Api",
    "AWS::ApiGatewayV2::Authorizer",
    "AWS::ApiGatewayV2::Integration",
    "AWS::ApiGatewayV2::Route",
    "AWS::ApiGatewayV2::Stage",
    "AWS::CloudFront::Distribution",
    "AWS::CloudFront::OriginAccessControl",
    "AWS::Cognito::UserPool",
    "AWS::Cognito::UserPoolClient",
    "AWS::Cognito::UserPoolDomain",
    "AWS::Cognito::UserPoolGroup",
    "AWS::DynamoDB::Table",
    "AWS::IAM::Role",
    "AWS::Lambda::Function",
    "AWS::Lambda::Permission",
    "AWS::Logs::LogGroup",
    "AWS::S3::Bucket",
    "AWS::S3::BucketPolicy",
}
PERSISTENT_RESOURCES = {
    "DonationsTable",
    "CognitoUserPool",
    "AnalyticsBucket",
    "FrontendBucket",
}


def verify_change_set(
    change_set: dict,
    stack: dict | None,
    expected_arn: str,
    expected_account: str,
    expected_region: str,
    expected_stack: str,
    expected_type: str | None = None,
    expected_source_commit: str | None = None,
) -> list[str]:
    change_set_id = change_set.get("ChangeSetId")
    if change_set_id != expected_arn:
        raise ValueError("CloudFormation returned a different change-set identifier.")
    if not re.fullmatch(
        rf"arn:aws:cloudformation:{re.escape(expected_region)}:"
        rf"{re.escape(expected_account)}:changeSet/smart-food-demo-\d+-\d+/"
        r"[0-9a-fA-F-]+",
        str(change_set_id),
    ):
        raise ValueError("Change-set ARN does not match the expected account, region, and name.")

    if change_set.get("StackName") != expected_stack:
        raise ValueError("Change set does not target the expected stack name.")

    stack_id = change_set.get("StackId", "")
    if not re.fullmatch(
        rf"arn:aws:cloudformation:{re.escape(expected_region)}:"
        rf"{re.escape(expected_account)}:stack/{re.escape(expected_stack)}/"
        r"[0-9a-fA-F-]+",
        stack_id,
    ):
        raise ValueError("Change-set StackId does not match the expected account, region, and stack.")

    change_set_name = change_set.get("ChangeSetName", "")
    if not re.fullmatch(r"smart-food-demo-\d+-\d+", change_set_name):
        raise ValueError("Change-set name does not use the expected run-specific prefix.")

    change_type = change_set.get("ChangeSetType")
    if change_type not in {"CREATE", "UPDATE"}:
        raise ValueError(f"Unsupported change-set type: {change_type!r}.")
    if expected_type and change_type != expected_type:
        raise ValueError("Change-set type no longer matches the type selected during preparation.")

    if expected_source_commit:
        if not re.fullmatch(r"[0-9a-f]{40}", expected_source_commit):
            raise ValueError("Expected source commit must be a full lowercase Git SHA.")
        parameters = change_set.get("Parameters")
        if not isinstance(parameters, list):
            raise ValueError("Change set did not return its parameter list.")
        source_commit = next(
            (
                parameter
                for parameter in parameters
                if parameter.get("ParameterKey") == "SourceCommit"
            ),
            None,
        )
        if (
            source_commit is None
            or source_commit.get("ParameterValue") != expected_source_commit
            or source_commit.get("UsePreviousValue") is True
        ):
            raise ValueError("Change-set SourceCommit does not match the reviewed commit.")

    if change_set.get("Status") != "CREATE_COMPLETE":
        reason = change_set.get("StatusReason", "No status reason returned")
        raise ValueError(
            f"Change set is not ready to execute (status={change_set.get('Status')!r}): {reason}"
        )

    if change_type == "CREATE":
        if stack is not None:
            if stack.get("StackId") != stack_id or stack.get("StackName") != expected_stack:
                raise ValueError("CREATE change set is associated with a different stack identity.")
            if stack.get("StackStatus") != "REVIEW_IN_PROGRESS":
                raise ValueError("CREATE change set is no longer associated with an unexecuted stack.")
    else:
        if stack is None:
            raise ValueError("UPDATE change set has no current target stack.")
        if stack.get("StackId") != stack_id or stack.get("StackName") != expected_stack:
            raise ValueError("UPDATE change set StackId does not match the current stack.")
        if stack.get("StackStatus") not in STABLE_STACK_STATUSES:
            raise ValueError(
                f"Refusing change set while the stack status is {stack.get('StackStatus')!r}."
            )
        change_set_created = _parse_aws_time(change_set.get("CreationTime", ""))
        stack_last_updated = _parse_aws_time(
            stack.get("LastUpdatedTime") or stack.get("CreationTime", "")
        )
        if stack_last_updated > change_set_created:
            raise ValueError("The stack was updated after this change set was created.")

    changes = change_set.get("Changes", [])
    if not changes:
        raise ValueError("Change set contains no resource changes.")

    lines = [
        f"## Reviewed change set: `{change_set_name}`",
        "",
        f"- Stack: `{expected_stack}`",
        f"- Stack ID: `{stack_id}`",
        f"- Change-set type: **{change_type}**",
        f"- Change-set status: **{change_set.get('Status')}**",
        *(
            [f"- Source commit: `{expected_source_commit}`"]
            if expected_source_commit
            else []
        ),
        "",
        "| Action | Logical resource | Resource type | Replacement | Scope / details |",
        "|---|---|---|---|---|",
    ]
    for item in changes:
        resource = item.get("ResourceChange")
        if not isinstance(resource, dict):
            raise ValueError("Change set contains a resource change without details.")
        action_value = resource.get("Action")
        logical_id_value = resource.get("LogicalResourceId")
        resource_type_value = resource.get("ResourceType")
        if not all(isinstance(value, str) and value for value in (
            action_value,
            logical_id_value,
            resource_type_value,
        )):
            raise ValueError("Resource change is missing its action, logical ID, or type.")
        action = action_value
        logical_id = logical_id_value
        resource_type = resource_type_value
        if resource_type not in ALLOWED_RESOURCE_TYPES:
            raise ValueError(f"Unapproved resource type: {resource_type!r}.")
        allowed_actions = {"Add"} if change_type == "CREATE" else {"Add", "Modify"}
        if action not in allowed_actions:
            raise ValueError(
                f"Unapproved {action!r} action for {logical_id!r}; removals and imports are blocked."
            )
        replacement_value = resource.get("Replacement")
        if action == "Modify" and replacement_value not in {
            "False",
            False,
            "True",
            True,
            "Conditional",
        }:
            raise ValueError(f"Unknown replacement behavior for {logical_id!r}.")
        if action == "Modify" and replacement_value not in {"False", False}:
            if logical_id in PERSISTENT_RESOURCES:
                raise ValueError(
                    f"Protected persistent resource {logical_id!r} would be replaced."
                )
            raise ValueError(
                f"Unapproved replacement of {logical_id!r}; add an explicit reviewed exception first."
            )
        if action == "Modify":
            details = resource.get("Details")
            scope = resource.get("Scope")
            if not isinstance(details, list) or not details:
                raise ValueError(f"Change details are unavailable for modified resource {logical_id!r}.")
            if not isinstance(scope, list) or not scope:
                raise ValueError(f"Change scope is unavailable for modified resource {logical_id!r}.")
            if any(
                not isinstance(detail, dict)
                or not isinstance(detail.get("Target"), dict)
                or not detail["Target"].get("Attribute")
                for detail in details
            ):
                raise ValueError(f"Property change details are incomplete for modified resource {logical_id!r}.")
            if logical_id in PERSISTENT_RESOURCES and any(
                detail["Target"]["Attribute"] in {"DeletionPolicy", "UpdateReplacePolicy"}
                for detail in details
            ):
                raise ValueError(
                    f"Change set modifies retention behavior for protected persistent resource {logical_id!r}."
                )

        action = str(resource.get("Action", "unknown")).replace("|", "\\|")
        logical_id = str(resource.get("LogicalResourceId", "unknown")).replace("|", "\\|")
        resource_type = str(resource.get("ResourceType", "unknown")).replace("|", "\\|")
        replacement = str(resource.get("Replacement", "unknown")).replace("|", "\\|")
        scope = resource.get("Scope") or []
        details = resource.get("Details") or []
        detail_summary = ", ".join(
            f"{detail['Target']['Attribute']}:"
            f"{detail['Target'].get('Name', 'unknown')}"
            for detail in details
        )
        scope_summary = ",".join(str(item) for item in scope)
        change_detail = "; ".join(part for part in (scope_summary, detail_summary) if part)
        lines.append(
            f"| {action} | `{logical_id}` | `{resource_type}` | {replacement} | "
            f"{change_detail or 'No property detail returned'} |"
        )
    lines.extend(
        [
            "",
            "> This change set has not been executed. Review every resource action, replacement,",
            "> and removal before approving the protected `aws-demo` execution environment.",
        ]
    )
    return lines


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _parse_aws_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--change-set-file", required=True)
    parser.add_argument("--stack-file")
    parser.add_argument("--expected-change-set-arn")
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--expected-region", required=True)
    parser.add_argument("--expected-stack", required=True)
    parser.add_argument("--expected-type")
    parser.add_argument("--expected-source-commit")
    args = parser.parse_args()

    try:
        change_set = _load_json(args.change_set_file)
        stack = _load_json(args.stack_file)["Stacks"][0] if args.stack_file else None
        expected_arn = args.expected_change_set_arn or change_set.get("ChangeSetId", "")
        lines = verify_change_set(
            change_set,
            stack,
            expected_arn,
            args.expected_account,
            args.expected_region,
            args.expected_stack,
            args.expected_type,
            args.expected_source_commit,
        )
    except (OSError, KeyError, IndexError, json.JSONDecodeError, ValueError) as error:
        print(f"Change-set verification failed: {error}", file=sys.stderr)
        return 1

    summary = "\n".join(lines)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as output:
            output.write(summary + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
