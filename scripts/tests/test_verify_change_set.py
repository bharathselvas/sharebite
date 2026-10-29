import pytest

from scripts.verify_change_set import verify_change_set

ACCOUNT = "123456789012"
REGION = "ap-south-1"
STACK_NAME = "smart-food-demo"
STACK_ID = (
    f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{STACK_NAME}/"
    "d7a914d0-1731-11ef-9aa1-0a1b2c3d4e5f"
)
CHANGE_SET_NAME = "smart-food-demo-123456789-1"
CHANGE_SET_ARN = (
    f"arn:aws:cloudformation:{REGION}:{ACCOUNT}:changeSet/"
    f"{CHANGE_SET_NAME}/a7655e43-1731-11ef-9aa1-0a1b2c3d4e5f"
)


def change_set(change_type="UPDATE"):
    action = "Add" if change_type == "CREATE" else "Modify"
    return {
        "ChangeSetId": CHANGE_SET_ARN,
        "StackId": STACK_ID,
        "StackName": STACK_NAME,
        "ChangeSetName": CHANGE_SET_NAME,
        "ChangeSetType": change_type,
        "Status": "CREATE_COMPLETE",
        "CreationTime": "2026-10-29T10:00:00+00:00",
        "Changes": [
            {
                "ResourceChange": {
                    "Action": action,
                    "LogicalResourceId": "DonationsFunction",
                    "ResourceType": "AWS::Lambda::Function",
                    "Replacement": "False",
                    "Scope": ["Properties"],
                    "Details": [
                        {
                            "Target": {
                                "Attribute": "Properties",
                                "Name": "CodeUri",
                            }
                        }
                    ],
                }
            }
        ],
    }


def stack(status="UPDATE_COMPLETE"):
    return {
        "StackId": STACK_ID,
        "StackName": STACK_NAME,
        "StackStatus": status,
        "CreationTime": "2026-10-20T10:00:00+00:00",
        "LastUpdatedTime": "2026-10-25T10:00:00+00:00",
    }


def verify(value, current_stack, expected_type=None):
    return verify_change_set(
        value,
        current_stack,
        CHANGE_SET_ARN,
        ACCOUNT,
        REGION,
        STACK_NAME,
        expected_type,
    )


def test_accepts_update_for_matching_stable_stack():
    lines = verify(change_set(), stack(), "UPDATE")
    assert any("Change-set type: **UPDATE**" in line for line in lines)
    assert any("DonationsFunction" in line for line in lines)


def test_rejects_replacement_of_a_persistent_resource():
    value = change_set()
    value["Changes"][0]["ResourceChange"].update(
        Action="Modify",
        LogicalResourceId="DonationsTable",
        ResourceType="AWS::DynamoDB::Table",
        Replacement="True",
    )
    with pytest.raises(ValueError, match="persistent resource.*replaced"):
        verify(value, stack(), "UPDATE")


def test_accepts_first_create_change_set_with_no_stack_yet():
    assert verify(change_set("CREATE"), None, "CREATE")


def test_accepts_first_create_change_set_in_review_in_progress():
    assert verify(change_set("CREATE"), stack("REVIEW_IN_PROGRESS"), "CREATE")


@pytest.mark.parametrize(
    ("mutate", "current_stack", "expected_type", "message"),
    [
        (
            lambda value: value.update(StackName="another-stack"),
            stack(),
            None,
            "expected stack name",
        ),
        (
            lambda value: value.update(StackId="arn:aws:cloudformation:us-east-1:123456789012:stack/smart-food-demo/other"),
            stack(),
            None,
            "expected account, region, and stack",
        ),
        (
            lambda value: value.update(ChangeSetId="arn:aws:cloudformation:ap-south-1:123456789012:changeSet/other/id"),
            stack(),
            None,
            "different change-set identifier",
        ),
        (
            lambda value: value.update(Status="FAILED", StatusReason="No changes"),
            stack(),
            None,
            "not ready to execute",
        ),
        (
            lambda value: value.update(
                ChangeSetType="CREATE",
                Changes=[{
                    "ResourceChange": {
                        "Action": "Add",
                        "LogicalResourceId": "DonationsFunction",
                        "ResourceType": "AWS::Lambda::Function",
                        "Replacement": "False",
                    }
                }],
            ),
            stack(),
            "CREATE",
            "unexecuted stack",
        ),
        (
            lambda value: None,
            stack("UPDATE_IN_PROGRESS"),
            None,
            "UPDATE_IN_PROGRESS",
        ),
        (
            lambda value: value.update(Changes=[]),
            stack(),
            None,
            "no resource changes",
        ),
    ],
)
def test_rejects_mismatched_or_unsafe_change_sets(
    mutate, current_stack, expected_type, message
):
    value = change_set()
    mutate(value)
    with pytest.raises(ValueError, match=message):
        verify(value, current_stack, expected_type)


def test_rejects_update_if_current_stack_is_missing():
    with pytest.raises(ValueError, match="no current target stack"):
        verify(change_set(), None, "UPDATE")


def test_rejects_update_if_stack_changed_after_change_set_was_created():
    current_stack = stack()
    current_stack["LastUpdatedTime"] = "2026-10-29T11:00:00+00:00"
    with pytest.raises(ValueError, match="updated after this change set"):
        verify(change_set(), current_stack, "UPDATE")


def test_rejects_unapproved_resource_types_and_destructive_actions():
    value = change_set()
    value["Changes"][0]["ResourceChange"]["ResourceType"] = "AWS::IAM::Policy"
    with pytest.raises(ValueError, match="Unapproved resource type"):
        verify(value, stack())

    value = change_set()
    value["Changes"][0]["ResourceChange"]["Action"] = "Remove"
    with pytest.raises(ValueError, match="removals and imports are blocked"):
        verify(value, stack())


def test_rejects_all_unapproved_replacements():
    value = change_set()
    value["Changes"][0]["ResourceChange"]["Replacement"] = "Conditional"
    with pytest.raises(ValueError, match="explicit reviewed exception"):
        verify(value, stack())


def test_requires_modified_resource_details():
    value = change_set()
    del value["Changes"][0]["ResourceChange"]["Details"]
    with pytest.raises(ValueError, match="details are unavailable"):
        verify(value, stack())


def test_rejects_retention_policy_changes_for_persistent_resources():
    value = change_set()
    value["Changes"][0]["ResourceChange"].update(
        LogicalResourceId="DonationsTable",
        ResourceType="AWS::DynamoDB::Table",
        Details=[
            {
                "Target": {
                    "Attribute": "DeletionPolicy",
                    "Name": "DeletionPolicy",
                }
            }
        ],
    )
    with pytest.raises(ValueError, match="modifies retention behavior"):
        verify(value, stack())


def test_requires_matching_source_commit_parameter():
    commit = "a" * 40
    value = change_set()
    value["Parameters"] = [
        {"ParameterKey": "SourceCommit", "ParameterValue": commit}
    ]
    assert verify_change_set(
        value,
        stack(),
        CHANGE_SET_ARN,
        ACCOUNT,
        REGION,
        STACK_NAME,
        expected_source_commit=commit,
    )

    value["Parameters"][0]["ParameterValue"] = "b" * 40
    with pytest.raises(ValueError, match="SourceCommit"):
        verify_change_set(
            value,
            stack(),
            CHANGE_SET_ARN,
            ACCOUNT,
            REGION,
            STACK_NAME,
            expected_source_commit=commit,
        )
