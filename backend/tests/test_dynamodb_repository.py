import copy
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from botocore.exceptions import ClientError
from boto3.dynamodb.types import TypeDeserializer

from backend.repositories import (
    DynamoDBDonationRepository,
    DonationConflict,
    DonationForbidden,
    DonationNotFound,
)


class FakeDynamoTable:
    def __init__(self):
        self.items = {}
        self.fail_with = None
        self.name = "test-donations"
        self.meta = SimpleNamespace(client=self)
        self.deserializer = TypeDeserializer()

    def _deserialize(self, item):
        return {key: self.deserializer.deserialize(value) for key, value in item.items()}

    def transact_write_items(self, TransactItems, ReturnConsumedCapacity):
        if self.fail_with:
            raise self.fail_with
        before = copy.deepcopy(self.items)
        try:
            for transaction in TransactItems:
                if "Put" in transaction:
                    operation = transaction["Put"]
                    self.put_item(
                        Item=self._deserialize(operation["Item"]),
                        ConditionExpression=operation.get("ConditionExpression"),
                    )
                else:
                    operation = transaction["Update"]
                    values = self._deserialize(operation["ExpressionAttributeValues"])
                    self.update_item(
                        Key=self._deserialize(operation["Key"]),
                        UpdateExpression=operation["UpdateExpression"],
                        ConditionExpression=operation["ConditionExpression"],
                        ExpressionAttributeNames=operation["ExpressionAttributeNames"],
                        ExpressionAttributeValues=values,
                        ReturnValues="ALL_NEW",
                    )
        except ClientError as error:
            self.items = before
            raise ClientError(
                {
                    "Error": {"Code": "TransactionCanceledException"},
                    "CancellationReasons": [{"Code": "ConditionalCheckFailed"}],
                },
                "TransactWriteItems",
            ) from error

    def put_item(self, Item, ConditionExpression=None):
        if self.fail_with:
            raise self.fail_with
        if ConditionExpression and Item["id"] in self.items:
            raise conditional_failure()
        self.items[Item["id"]] = dict(Item)

    def get_item(self, Key, ConsistentRead=False):
        if self.fail_with:
            raise self.fail_with
        item = self.items.get(Key["id"])
        return {"Item": dict(item)} if item else {}

    def update_item(
        self,
        Key,
        UpdateExpression,
        ConditionExpression,
        ExpressionAttributeNames,
        ExpressionAttributeValues,
        ReturnValues,
    ):
        if self.fail_with:
            raise self.fail_with
        item = self.items.get(Key["id"])
        values = ExpressionAttributeValues
        expected = values.get(":available", values.get(":expected_status"))
        deadline = item.get("pickup_deadline", "") if item else ""
        if (
            item is None
            or item["status"] != expected
            or (
                "pickup_deadline > :now" in ConditionExpression
                and deadline <= values[":now"]
            )
            or (
                "pickup_deadline <= :now" in ConditionExpression
                and deadline > values[":now"]
            )
        ):
            raise conditional_failure()
        if ":actor" in values:
            owner_field = "donor_id" if "donor_id = :actor" in ConditionExpression else "claimed_by"
            if item.get(owner_field) != values[":actor"]:
                raise conditional_failure()
        new_status = values.get(
            ":claimed", values.get(":new_status", values.get(":expired"))
        )
        if new_status:
            item["status"] = new_status
            item["status_pk"] = new_status
        for field in (
            "food_name",
            "description",
            "category",
            "quantity",
            "unit",
            "available_at",
            "pickup_deadline",
            "deadline_sk",
            "pickup_location",
            "updated_at",
        ):
            if f":{field}" in values:
                item[field] = values[f":{field}"]
        if ":deadline_sort" in values:
            item["deadline_sk"] = values[":deadline_sort"]
        if ":ngo" in values:
            item["claimed_by"] = values[":ngo"]
            item["recipient_pk"] = values[":ngo"]
            item["recipient_sk"] = values.get(":recipient_sort", "claim")
            item["claimed_at"] = values.get(":now")
        if ":new_status" in values and values[":new_status"] == "picked_up":
            item["completed_at"] = values.get(":now")
        if ":now" in values:
            item["updated_at"] = values[":now"]
        return {"Attributes": dict(item)}

    def query(self, **kwargs):
        if self.fail_with:
            raise self.fail_with
        index = kwargs["IndexName"]
        key_condition = kwargs["KeyConditionExpression"]
        if index == "expiry-index":
            partition_condition, range_condition = key_condition.get_expression()["values"]
            partition_key, partition_value = partition_condition._values
            range_key, range_value = range_condition._values
        else:
            partition_key, partition_value = key_condition._values
        field = partition_key.name
        records = [
            item for item in self.items.values() if item.get(field) == partition_value
        ]
        sort_field = {
            "status-index": "status_sk",
            "donor-index": "donor_sk",
            "recipient-index": "recipient_sk",
            "entity-index": "entity_sk",
            "expiry-index": "deadline_sk",
        }[index]
        if index == "expiry-index":
            records = [
                item for item in records
                if item.get(range_key.name, "") <= range_value
            ]
        records.sort(key=lambda item: item[sort_field], reverse=not kwargs["ScanIndexForward"])
        start_key = kwargs.get("ExclusiveStartKey")
        if start_key:
            start_index = next(
                (index for index, item in enumerate(records) if item["id"] == start_key["id"]),
                None,
            )
            if start_index is None:
                raise ValueError("cursor record is not in this query")
            records = records[start_index + 1 :]
        page = records[: kwargs["Limit"]]
        result = {"Items": [dict(item) for item in page]}
        if len(records) > len(page):
            last = page[-1]
            result["LastEvaluatedKey"] = {
                key: last[key]
                for key in (
                    "id",
                    "status_pk",
                    "status_sk",
                    "donor_pk",
                    "donor_sk",
                    "recipient_pk",
                    "recipient_sk",
                    "entity_pk",
                    "entity_sk",
                    "deadline_sk",
                )
                if key in last
            }
        return result

    def scan(self, **kwargs):
        raise AssertionError("Normal donation queries must not scan the table")


def conditional_failure():
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}},
        "UpdateItem",
    )


def service_failure():
    return ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException"}},
        "UpdateItem",
    )


def donation(**overrides):
    value = {
        "donor_id": "donor-sub-1",
        "food_name": "Rice bags",
        "quantity": Decimal("12"),
        "unit": "bags",
        "pickup_deadline": (
            datetime.now(timezone.utc) + timedelta(days=1)
        ).isoformat(),
        "status": "available",
        "claimed_by": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "claimed_at": None,
        "completed_at": None,
        "description": "",
        "category": "other",
        "available_at": None,
        "pickup_location": "",
    }
    value.update(overrides)
    return value


@pytest.fixture
def repository():
    return DynamoDBDonationRepository(FakeDynamoTable())


def test_dynamo_create_and_paginated_status_and_owner_queries(repository):
    first = repository.create(donation())
    second = repository.create(donation(food_name="Lentil bags"))
    assert first["donor_id"] == "donor-sub-1"
    assert not (
        {
            "status_pk",
            "status_sk",
            "donor_pk",
            "donor_sk",
            "recipient_pk",
            "recipient_sk",
        }
        & first.keys()
    )
    page, cursor = repository.list_status("available", 1)
    assert len(page) == 1
    assert cursor
    second_page, next_cursor = repository.list_status("available", 1, cursor)
    assert len(second_page) == 1
    assert next_cursor is None
    assert {page[0]["id"], second_page[0]["id"]} == {first["id"], second["id"]}
    donor_page, _ = repository.list_by_donor("donor-sub-1", 10)
    assert len(donor_page) == 2
    repository.claim(first["id"], "ngo-sub-1")
    claimed_page, _ = repository.list_by_claimant("ngo-sub-1", 10)
    assert [item["id"] for item in claimed_page] == [first["id"]]
    events, cursor = repository.list_events("donation", first["id"], 10)
    assert cursor is None
    assert [event["event_type"] for event in events] == [
        "donation_claimed",
        "donation_created",
    ]


def test_dashboard_aggregates_account_scoped_dynamodb_data():
    repository = DynamoDBDonationRepository(FakeDynamoTable())
    rice = repository.create(donation())
    milk = repository.create(
        donation(food_name="Milk", unit="litres", quantity=Decimal("3"))
    )
    repository.create(donation(donor_id="another-donor", food_name="Bread"))
    repository.claim(rice["id"], "ngo-sub-1")
    repository.transition(rice["id"], "picked_up", "ngo-sub-1", "ngo")

    donor_dashboard = repository.dashboard_for_user("donor-sub-1", "donor")
    assert donor_dashboard["total_donations"] == 2
    assert donor_dashboard["available_donations"] == 1
    assert donor_dashboard["marketplace_available_donations"] == 2
    assert donor_dashboard["completed_pickups"] == 1
    assert donor_dashboard["completed_quantity_by_unit"] == {"bags": Decimal("12")}
    assert donor_dashboard["recent_donations"][0]["id"] == milk["id"]
    assert {
        event["event_type"] for event in donor_dashboard["recent_activity"]
    } == {
        "donation_created",
        "donation_claimed",
        "donation_completed",
    }

    ngo_dashboard = repository.dashboard_for_user("ngo-sub-1", "ngo")
    assert ngo_dashboard["total_donations"] == 1
    assert ngo_dashboard["completed_pickups"] == 1
    assert ngo_dashboard["upcoming_pickups"] == []
    assert ngo_dashboard["data_source"] == "cloud_live"


def test_dashboard_fails_closed_when_account_query_exceeds_bound():
    repository = DynamoDBDonationRepository(FakeDynamoTable(), max_admin_items=1)
    repository.create(donation())
    repository.create(donation(food_name="Second donation"))

    with pytest.raises(RuntimeError, match="dashboard query exceeded"):
        repository.dashboard_for_user("donor-sub-1", "donor")


def test_dynamo_claim_is_conditional_and_distinguishes_missing(repository):
    item = repository.create(donation())
    claimed = repository.claim(item["id"], "ngo-sub-1")
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by"] == "ngo-sub-1"
    with pytest.raises(DonationConflict):
        repository.claim(item["id"], "ngo-sub-2")
    with pytest.raises(DonationNotFound):
        repository.claim("missing", "ngo-sub-1")


def test_dynamo_claim_expiration_and_audit_are_transactional(repository):
    item = repository.create(
        donation(
            pickup_deadline=(
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat()
        )
    )
    with pytest.raises(DonationConflict):
        repository.claim(item["id"], "ngo-sub-1")
    assert repository.get(item["id"])["status"] == "expired"
    events, _ = repository.list_events("donation", item["id"])
    assert {event["event_type"] for event in events} == {
        "donation_created",
        "donation_expired",
    }


def test_dynamo_transition_checks_owner_and_state(repository):
    item = repository.create(donation())
    with pytest.raises(DonationForbidden):
        repository.transition(item["id"], "cancelled", "other-donor", "donor")
    cancelled = repository.transition(item["id"], "cancelled", "donor-sub-1", "donor")
    assert cancelled["status"] == "cancelled"
    with pytest.raises(DonationConflict):
        repository.transition(item["id"], "cancelled", "donor-sub-1", "donor")

    second = repository.create(donation())
    repository.claim(second["id"], "ngo-sub-1")
    with pytest.raises(DonationForbidden):
        repository.transition(second["id"], "picked_up", "other-ngo", "ngo")
    picked_up = repository.transition(second["id"], "picked_up", "ngo-sub-1", "ngo")
    assert picked_up["status"] == "picked_up"


def test_dynamo_update_is_owner_and_status_conditional(repository):
    item = repository.create(donation())
    fields = {
        "food_name": "Updated rice",
        "description": "Sealed surplus",
        "category": "packaged",
        "quantity": Decimal("8"),
        "unit": "bags",
        "available_at": None,
        "pickup_deadline": (
            datetime.now(timezone.utc) + timedelta(days=2)
        ).isoformat(),
        "pickup_location": "Community centre",
    }
    with pytest.raises(DonationForbidden):
        repository.update_donation(item["id"], fields, "other-donor", "donor")
    updated = repository.update_donation(item["id"], fields, "donor-sub-1", "donor")
    assert updated["food_name"] == "Updated rice"
    assert repository.table.items[item["id"]]["deadline_sk"].startswith(
        fields["pickup_deadline"]
    )
    events, _ = repository.list_events("donation", item["id"])
    assert [event["event_type"] for event in events] == [
        "donation_updated",
        "donation_created",
    ]
    repository.claim(item["id"], "ngo-sub-1")
    with pytest.raises(DonationConflict):
        repository.update_donation(item["id"], fields, "donor-sub-1", "donor")


def test_dynamo_expiry_queries_due_deadlines_without_scanning_recent_available_items(repository):
    now = datetime.now(timezone.utc)
    for index in range(105):
        repository.create(
            donation(
                food_name=f"Future donation {index}",
                pickup_deadline=(now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                created_at=(now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            )
        )
    due = repository.create(
        donation(
            food_name="Due donation",
            pickup_deadline=(now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        )
    )

    assert repository.expire_due(now=now, limit=100) == 1
    assert repository.get(due["id"])["status"] == "expired"


def test_dynamo_unexpected_service_errors_are_not_mapped_to_conflicts(repository):
    item = repository.create(donation())
    repository.table.fail_with = service_failure()
    with pytest.raises(ClientError) as error:
        repository.claim(item["id"], "ngo-sub-1")
    assert error.value.response["Error"]["Code"] == "ProvisionedThroughputExceededException"


def test_dynamo_invalid_cursor_fails_clearly(repository):
    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        repository.list_status("available", 10, "not-a-cursor")
