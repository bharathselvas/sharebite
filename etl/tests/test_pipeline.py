import json

import pandas as pd
import pytest

from etl.pipeline import (
    read_records,
    run_pipeline,
    summarize,
    transform_records,
    upload_outputs,
)


def valid_record(**overrides):
    record = {
        "id": "donation-1",
        "donor_id": "donor-demo",
        "food_name": "Rice bags",
        "quantity": "10",
        "unit": "bags",
        "pickup_deadline": "2026-10-30T10:00:00+05:30",
        "status": "PICKED_UP",
        "claimed_by": "ngo-demo",
        "created_at": "2026-10-28T10:00:00+05:30",
    }
    record.update(overrides)
    return record


def test_normalizes_and_accepts_valid_record():
    clean, rejected = transform_records([valid_record()])
    assert rejected.empty
    assert clean.loc[0, "quantity"] == 10
    assert clean.loc[0, "status"] == "picked_up"
    assert clean.loc[0, "created_at"] == "2026-10-28T04:30:00Z"


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (valid_record(quantity="0"), "positive number"),
        (valid_record(quantity="not-a-number"), "could not convert"),
        (valid_record(status="in_transit"), "unsupported status"),
        (valid_record(created_at="2026-10-28T10:00:00"), "timezone"),
        (valid_record(food_name=" "), "missing required fields"),
    ],
)
def test_rejects_invalid_records(record, reason):
    clean, rejected = transform_records([record])
    assert clean.empty
    assert reason in rejected.loc[0, "reason"]
    assert rejected.loc[0, "source_row"] == 2


def test_rejects_duplicate_ids_and_keeps_first_clean_row():
    clean, rejected = transform_records(
        [valid_record(), valid_record(food_name="Duplicate rice")]
    )
    assert len(clean) == 1
    assert len(rejected) == 1
    assert rejected.loc[0, "reason"] == "duplicate donation id"
    assert not ({"raw_record", "password", "token"} & set(rejected.columns))


def test_summary_keeps_quantities_separate_by_unit():
    clean, rejected = transform_records(
        [
            valid_record(quantity=10, unit="bags"),
            valid_record(id="donation-2", quantity=2, unit="boxes"),
        ]
    )
    summary = summarize(clean, rejected)
    assert summary["completed_quantity_by_unit"] == {"bags": 10.0, "boxes": 2.0}


def test_rejects_inconsistent_claim_state_and_invalid_optional_timestamp():
    clean, rejected = transform_records(
        [
            valid_record(status="claimed", claimed_by=""),
            valid_record(id="bad-date", available_at="not-a-time"),
        ]
    )
    assert clean.empty
    assert rejected["reason"].str.contains("claimed_by|datetime").all()


def test_accepts_null_claimant_for_available_application_export():
    clean, rejected = transform_records(
        [valid_record(status="available", claimed_by=None)]
    )
    assert len(clean) == 1
    assert clean.iloc[0]["claimed_by"] == ""
    assert rejected.empty


def test_writes_clean_rejected_and_dashboard_outputs(tmp_path):
    source = tmp_path / "donations.json"
    source.write_text(
        json.dumps([valid_record(), valid_record(id="bad", quantity="-1")]),
        encoding="utf-8",
    )
    output = tmp_path / "report"
    summary = run_pipeline(source, output)
    assert summary["total_clean_donations"] == 1
    assert summary["completed_pickups"] == 1
    assert summary["completed_quantity_by_unit"] == {"bags": 10.0}
    assert summary["rejected_records"] == 1
    assert summary["input_records"] == 2
    assert summary["duplicate_records"] == 0
    assert (output / "clean_donations.csv").is_file()
    assert (output / "cleaned_donations.csv").is_file()
    assert (output / "rejected_records.csv").is_file()
    assert (output / "rejected_donations.csv").is_file()
    assert (output / "donation_daily_summary.csv").is_file()
    assert (output / "donation_status_summary.csv").is_file()
    assert (output / "etl_run_summary.json").is_file()
    assert json.loads((output / "summary.json").read_text()) == summary


def test_etl_outputs_are_deterministic_for_identical_input(tmp_path):
    source = tmp_path / "donations.json"
    records = [
        valid_record(status="picked_up", unit="bags"),
        valid_record(id="donation-2", status="available", unit="boxes"),
    ]
    source.write_text(json.dumps(records), encoding="utf-8")
    output = tmp_path / "stable-output"
    first = run_pipeline(source, output)
    files = (
        "clean_donations.csv",
        "rejected_records.csv",
        "donation_daily_summary.csv",
        "donation_status_summary.csv",
    )
    bytes_before = {name: (output / name).read_bytes() for name in files}
    second = run_pipeline(source, output)
    assert first["input_records"] == second["input_records"] == 2
    assert first["duplicate_records"] == second["duplicate_records"] == 0
    assert {name: (output / name).read_bytes() for name in files} == bytes_before


def test_reads_csv_synthetic_sample():
    from pathlib import Path

    sample = Path(__file__).parents[1] / "sample_data" / "donations.csv"
    records = read_records(sample)
    clean, rejected = transform_records(records)
    assert len(clean) == 2
    assert len(rejected) == 3


def test_rejects_input_over_configured_size(tmp_path):
    from etl.pipeline import MAX_INPUT_BYTES

    source = tmp_path / "large.json"
    source.write_bytes(b" " * (MAX_INPUT_BYTES + 1))
    with pytest.raises(ValueError, match="processing limit"):
        read_records(source)


class FakeS3Client:
    def __init__(self):
        self.uploads = []
        self.fail_on_key = None

    def put_object(self, **kwargs):
        if kwargs["Key"] == self.fail_on_key:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "AccessDenied"}},
                "PutObject",
            )
        self.uploads.append(kwargs)


def test_s3_upload_requires_bucket_and_uploads_only_reports_private_with_encryption(tmp_path):
    source = tmp_path / "donations.json"
    source.write_text(json.dumps([valid_record()]), encoding="utf-8")
    output = tmp_path / "report"
    run_pipeline(source, output)
    client = FakeS3Client()

    keys = upload_outputs(output, "approved-demo-bucket-123", client, "ia3/reports")

    assert keys == [
        "ia3/reports/clean_donations.csv",
        "ia3/reports/rejected_records.csv",
        "ia3/reports/summary.json",
        "ia3/reports/donation_daily_summary.csv",
        "ia3/reports/donation_status_summary.csv",
        "ia3/reports/etl_run_summary.json",
    ]
    assert [item["Bucket"] for item in client.uploads] == [
        "approved-demo-bucket-123"
    ] * 6
    assert all(item["ServerSideEncryption"] == "AES256" for item in client.uploads)
    assert all("ACL" not in item for item in client.uploads)


@pytest.mark.parametrize(
    ("bucket", "prefix"),
    [
        ("", ""),
        ("Invalid_Bucket", ""),
        ("approved-demo-bucket", "../private"),
    ],
)
def test_s3_upload_rejects_missing_or_invalid_configuration(tmp_path, bucket, prefix):
    with pytest.raises(ValueError):
        upload_outputs(tmp_path, bucket, FakeS3Client(), prefix)


def test_s3_upload_reports_client_permission_errors(tmp_path):
    source = tmp_path / "donations.json"
    source.write_text(json.dumps([valid_record()]), encoding="utf-8")
    output = tmp_path / "report"
    run_pipeline(source, output)
    client = FakeS3Client()
    client.fail_on_key = "clean_donations.csv"

    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        upload_outputs(output, "approved-demo-bucket-123", client)
