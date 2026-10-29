import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from .pipeline import MAX_RECORDS, run_pipeline, upload_outputs
except ImportError:
    from pipeline import MAX_RECORDS, run_pipeline, upload_outputs

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SOURCE_FIELDS = (
    "id",
    "donor_id",
    "food_name",
    "description",
    "category",
    "quantity",
    "unit",
    "available_at",
    "pickup_deadline",
    "pickup_location",
    "status",
    "claimed_by",
    "created_at",
    "updated_at",
    "claimed_at",
    "completed_at",
)


def _extract_donations(table) -> list[dict]:
    names = {f"#field{index}": field for index, field in enumerate(SOURCE_FIELDS)}
    projection = ", ".join(names)
    records: list[dict] = []
    last_key = None

    while True:
        remaining = MAX_RECORDS + 1 - len(records)
        response = table.scan(
            ProjectionExpression=projection,
            ExpressionAttributeNames=names,
            Limit=remaining,
            **({"ExclusiveStartKey": last_key} if last_key else {}),
        )
        records.extend(response.get("Items", []))
        if len(records) > MAX_RECORDS:
            raise ValueError(f"Donation export exceeds the {MAX_RECORDS}-record ETL limit")
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return records


def run_etl(event: dict, context, table, s3_client, bucket: str) -> dict:
    del event
    run_id = getattr(context, "aws_request_id", "")
    if not run_id:
        raise ValueError("Lambda request ID is required for an ETL run")

    started_at = datetime.now(timezone.utc)
    started = time.monotonic()
    records = _extract_donations(table)
    with tempfile.TemporaryDirectory(prefix="sharebite-etl-") as workdir:
        work = Path(workdir)
        input_path = work / "donations.json"
        input_path.write_text(
            json.dumps(records, default=str),
            encoding="utf-8",
        )
        output_dir = work / "reports"
        summary = run_pipeline(input_path, output_dir)
        completed_at = datetime.now(timezone.utc)
        summary.update(
            {
                "run_id": run_id,
                "source": "DynamoDB",
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
                "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
                "processing_duration_seconds": round(time.monotonic() - started, 6),
            }
        )
        prefix = f"etl/runs/{run_id}"
        object_keys = [
            f"{prefix}/{name}"
            for name in (
                "clean_donations.csv",
                "rejected_records.csv",
                "summary.json",
                "donation_daily_summary.csv",
                "donation_status_summary.csv",
                "etl_run_summary.json",
            )
        ]
        summary["output_prefix"] = f"s3://{bucket}/{prefix}/"
        summary["output_objects"] = [f"s3://{bucket}/{key}" for key in object_keys]
        for report_name in ("summary.json", "etl_run_summary.json"):
            (output_dir / report_name).write_text(
                json.dumps(summary, indent=2) + "\n",
                encoding="utf-8",
            )
        uploaded = upload_outputs(output_dir, bucket, s3_client, prefix)

    result = {
        "run_id": run_id,
        "status": "succeeded",
        "input_records": summary["input_records"],
        "clean_records": summary["total_clean_donations"],
        "rejected_records": summary["rejected_records"],
        "output_prefix": f"s3://{bucket}/{prefix}/",
        "output_objects": [f"s3://{bucket}/{key}" for key in uploaded],
        "processing_duration_seconds": round(time.monotonic() - started, 6),
    }
    logger.info(json.dumps({"event": "sharebite_etl_completed", **result}))
    return result


def handler(event, context):
    import boto3

    table_name = os.environ.get("DONATIONS_TABLE")
    bucket = os.environ.get("ANALYTICS_BUCKET")
    if not table_name or not bucket:
        raise RuntimeError("DONATIONS_TABLE and ANALYTICS_BUCKET must be configured")

    try:
        table = boto3.resource("dynamodb").Table(table_name)
        return run_etl(event or {}, context, table, boto3.client("s3"), bucket)
    except Exception:
        logger.exception(
            json.dumps(
                {
                    "event": "sharebite_etl_failed",
                    "run_id": getattr(context, "aws_request_id", None),
                }
            )
        )
        raise
