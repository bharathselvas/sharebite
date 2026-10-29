import json
from decimal import Decimal

from etl.aws_handler import run_etl


class FakeTable:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def scan(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.pages)


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs


class FakeContext:
    aws_request_id = "demo-run-123"


def test_lambda_etl_extracts_dynamodb_records_and_writes_unique_s3_reports():
    table = FakeTable(
        [
            {
                "Items": [
                    {
                        "id": "donation-1",
                        "donor_id": "synthetic-donor",
                        "food_name": "Rice",
                        "quantity": Decimal("12"),
                        "unit": "portions",
                        "pickup_deadline": "2026-10-30T12:00:00Z",
                        "status": "available",
                        "created_at": "2026-10-29T12:00:00Z",
                    }
                ],
                "LastEvaluatedKey": {"id": "donation-1"},
            },
            {"Items": [], "LastEvaluatedKey": None},
        ]
    )
    s3 = FakeS3()

    result = run_etl({}, FakeContext(), table, s3, "private-analytics")

    assert result["status"] == "succeeded"
    assert result["run_id"] == "demo-run-123"
    assert result["input_records"] == result["clean_records"] == 1
    assert result["rejected_records"] == 0
    assert result["output_prefix"] == "s3://private-analytics/etl/runs/demo-run-123/"
    assert len(s3.objects) == 6
    report = json.loads(s3.objects["etl/runs/demo-run-123/summary.json"]["Body"])
    assert report["run_id"] == "demo-run-123"
    assert report["donations_by_status"]["available"] == 1
    assert report["output_objects"][0].endswith("/clean_donations.csv")
    assert all(call["ProjectionExpression"] for call in table.calls)
    assert all(call["Limit"] > 0 for call in table.calls)


def test_etl_fails_without_lambda_request_id():
    class Context:
        aws_request_id = ""

    try:
        run_etl({}, Context(), FakeTable([]), FakeS3(), "private-analytics")
    except ValueError as error:
        assert "request ID" in str(error)
    else:
        raise AssertionError("ETL should reject a missing invocation ID")
