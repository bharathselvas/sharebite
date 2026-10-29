import argparse
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any

import pandas as pd


REQUIRED_FIELDS = {
    "id",
    "donor_id",
    "food_name",
    "quantity",
    "unit",
    "pickup_deadline",
    "status",
    "created_at",
}
STATUSES = {"available", "claimed", "picked_up", "cancelled"}
STATUSES.add("expired")
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 10_000
OUTPUT_FIELDS = [
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
]


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    missing = pd.isna(value)
    return bool(missing) if isinstance(missing, (bool, type(pd.NA))) else False


def read_records(path: Path) -> list[dict[str, Any]]:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"Input exceeds the {MAX_INPUT_BYTES}-byte processing limit")
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        return frame.to_dict(orient="records")
    if path.suffix.lower() == ".json":
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list) or not all(
            isinstance(record, dict) for record in records
        ):
            raise ValueError("JSON input must be an array of record objects")
        if len(records) > MAX_RECORDS:
            raise ValueError(f"Input exceeds the {MAX_RECORDS}-record processing limit")
        return records
    raise ValueError("Input must be a .csv or .json file")


def normalize_timestamp(value: Any) -> str:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("timestamp is missing or invalid")
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return timestamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def transform_records(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(records) > MAX_RECORDS:
        raise ValueError(f"Input exceeds the {MAX_RECORDS}-record processing limit")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for source_row, original in enumerate(records, start=2):
        record_id = str(original.get("id", "")).strip()
        try:
            for field in ("id", "donor_id", "food_name", "unit", "status"):
                if field in original and not isinstance(original[field], str):
                    raise ValueError(f"{field} must be a string")
            missing = sorted(
                field
                for field in REQUIRED_FIELDS
                if field not in original or is_blank(original[field])
            )
            if missing:
                raise ValueError(f"missing required fields: {', '.join(missing)}")
            if record_id in seen_ids:
                raise ValueError("duplicate donation id")
            if isinstance(original["quantity"], bool):
                raise ValueError("quantity must be a number, not a boolean")
            quantity = float(original["quantity"])
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError("quantity must be a positive number")
            status = str(original["status"]).strip().lower()
            if status not in STATUSES:
                raise ValueError(f"unsupported status: {status}")
            optional_text_fields = (
                "description",
                "category",
                "pickup_location",
                "claimed_by",
            )
            for field in optional_text_fields:
                    if (
                        field in original
                        and original[field] is not None
                        and not isinstance(original[field], str)
                    ):
                        raise ValueError(f"{field} must be a string")
            cleaned = {
                "id": record_id,
                "donor_id": str(original["donor_id"]).strip(),
                "food_name": str(original["food_name"]).strip(),
                "description": str(original.get("description", "")).strip(),
                "category": str(original.get("category", "other")).strip().lower() or "other",
                "quantity": quantity,
                "unit": str(original["unit"]).strip(),
                "available_at": (
                    normalize_timestamp(original["available_at"])
                    if not is_blank(original.get("available_at"))
                    else ""
                ),
                "pickup_deadline": normalize_timestamp(original["pickup_deadline"]),
                "pickup_location": str(original.get("pickup_location", "")).strip(),
                "status": status,
                "claimed_by": (
                    ""
                    if is_blank(original.get("claimed_by"))
                    else str(original["claimed_by"]).strip()
                ),
                "created_at": normalize_timestamp(original["created_at"]),
                "updated_at": (
                    normalize_timestamp(original["updated_at"])
                    if not is_blank(original.get("updated_at"))
                    else normalize_timestamp(original["created_at"])
                ),
                "claimed_at": (
                    normalize_timestamp(original["claimed_at"])
                    if not is_blank(original.get("claimed_at"))
                    else ""
                ),
                "completed_at": (
                    normalize_timestamp(original["completed_at"])
                    if not is_blank(original.get("completed_at"))
                    else ""
                ),
            }
            if not all(cleaned[field] for field in ("donor_id", "food_name", "unit")):
                raise ValueError("donor_id, food_name, and unit must not be blank")
            if status in {"claimed", "picked_up"} and not cleaned["claimed_by"]:
                raise ValueError(f"{status} donation must include claimed_by")
            if cleaned["available_at"] and cleaned["available_at"] >= cleaned["pickup_deadline"]:
                raise ValueError("available_at must be earlier than pickup_deadline")
            seen_ids.add(record_id)
            accepted.append(cleaned)
        except (TypeError, ValueError, OverflowError) as error:
            rejected.append(
                {
                    "source_row": source_row,
                    "record_id": record_id,
                    "reason": str(error),
                }
            )

    clean_frame = pd.DataFrame(accepted, columns=OUTPUT_FIELDS)
    rejected_frame = pd.DataFrame(
        rejected, columns=["source_row", "record_id", "reason"]
    )
    return clean_frame, rejected_frame


def summarize(clean: pd.DataFrame, rejected: pd.DataFrame) -> dict[str, Any]:
    donations_by_status = {
        status: int((clean["status"] == status).sum()) if not clean.empty else 0
        for status in sorted(STATUSES)
    }
    quantities_by_status_and_unit = {
        status: {
            unit: float(
                clean.loc[
                    (clean["status"] == status) & (clean["unit"] == unit), "quantity"
                ].sum()
            )
            for unit in sorted(clean.loc[clean["status"] == status, "unit"].unique())
        }
        for status in sorted(STATUSES)
    }
    completed_quantity_by_unit = quantities_by_status_and_unit["picked_up"]
    return {
        "input_records": len(clean) + len(rejected),
        "total_clean_donations": len(clean),
        "rejected_records": len(rejected),
        "duplicate_records": int(
            rejected["reason"].str.startswith("duplicate donation id").sum()
        ) if not rejected.empty else 0,
        "completed_pickups": donations_by_status["picked_up"],
        "completed_quantity_by_unit": completed_quantity_by_unit,
        "donations_by_status": donations_by_status,
        "quantities_by_status_and_unit": quantities_by_status_and_unit,
    }


def run_pipeline(input_path: Path, output_dir: Path, parquet: bool = False) -> dict[str, Any]:
    started = time.perf_counter()
    records = read_records(input_path)
    clean, rejected = transform_records(records)
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_path = output_dir / "clean_donations.csv"
    rejected_path = output_dir / "rejected_records.csv"
    clean.to_csv(clean_path, index=False)
    clean.to_csv(output_dir / "cleaned_donations.csv", index=False)
    rejected.to_csv(rejected_path, index=False)
    rejected.to_csv(output_dir / "rejected_donations.csv", index=False)
    summary = summarize(clean, rejected)
    if clean.empty:
        daily = pd.DataFrame(columns=["created_date", "unit", "donations", "completed_quantity"])
        statuses = pd.DataFrame(columns=["status", "unit", "donations", "quantity"])
    else:
        working = clean.assign(created_date=clean["created_at"].str[:10])
        daily = (
            working.assign(
                _completed_quantity=working["quantity"].where(
                    working["status"].eq("picked_up"), 0
                )
            )
            .groupby(["created_date", "unit"], as_index=False)
            .agg(
                donations=("id", "count"),
                completed_quantity=("_completed_quantity", "sum"),
            )
            .sort_values(["created_date", "unit"])
        )
        statuses = (
            working.groupby(["status", "unit"], as_index=False)
            .agg(donations=("id", "count"), quantity=("quantity", "sum"))
            .sort_values(["status", "unit"])
        )
    daily_path = output_dir / "donation_daily_summary.csv"
    status_path = output_dir / "donation_status_summary.csv"
    daily.to_csv(daily_path, index=False)
    statuses.to_csv(status_path, index=False)
    summary["processing_duration_seconds"] = round(time.perf_counter() - started, 6)
    summary["output_locations"] = {
        "clean_donations": str(clean_path),
        "rejected_records": str(rejected_path),
        "daily_summary": str(daily_path),
        "status_summary": str(status_path),
        "run_summary": str(output_dir / "etl_run_summary.json"),
        "cleaned_donations": str(output_dir / "cleaned_donations.csv"),
        "rejected_donations": str(output_dir / "rejected_donations.csv"),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "etl_run_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    if parquet:
        clean.to_parquet(output_dir / "clean_donations.parquet", index=False)
    return summary


def upload_outputs(
    output_dir: Path,
    bucket_name: str,
    s3_client,
    prefix: str = "",
) -> list[str]:
    if not bucket_name or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket_name):
        raise ValueError("A valid explicitly configured S3 bucket name is required")
    key_prefix = prefix.strip("/")
    if key_prefix and any(part in {".", ".."} for part in key_prefix.split("/")):
        raise ValueError("S3 prefix must not contain dot path segments")

    objects = (
        ("clean_donations.csv", "text/csv"),
        ("rejected_records.csv", "text/csv"),
        ("summary.json", "application/json"),
        ("donation_daily_summary.csv", "text/csv"),
        ("donation_status_summary.csv", "text/csv"),
        ("etl_run_summary.json", "application/json"),
    )
    uploaded_keys = []
    for filename, content_type in objects:
        path = output_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Expected ETL output does not exist: {path}")
        key = f"{key_prefix}/{filename}" if key_prefix else filename
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=path.read_bytes(),
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        uploaded_keys.append(key)
    return uploaded_keys


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and aggregate donation exports")
    parser.add_argument("--input", type=Path, required=True, help="Input CSV or JSON file")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--upload-s3",
        action="store_true",
        help="Explicitly upload generated reports to an existing private S3 bucket",
    )
    parser.add_argument(
        "--s3-bucket",
        default=None,
        help="Existing bucket name; may be supplied as ETL_S3_BUCKET",
    )
    parser.add_argument("--s3-prefix", default="", help="Optional object-key prefix")
    parser.add_argument(
        "--parquet", action="store_true", help="Also write Parquet (requires PyArrow or fastparquet)"
    )
    args = parser.parse_args()
    if args.upload_s3 and not (args.s3_bucket or os.environ.get("ETL_S3_BUCKET")):
        parser.error("--upload-s3 requires --s3-bucket or ETL_S3_BUCKET")
    summary = run_pipeline(args.input, args.output_dir, args.parquet)
    print(json.dumps(summary, indent=2))
    if args.upload_s3:
        try:
            import boto3
            from botocore.exceptions import BotoCoreError, ClientError
        except ImportError:
            parser.error(
                "S3 upload requires boto3; install the declared backend requirements first"
            )
        bucket_name = args.s3_bucket or os.environ["ETL_S3_BUCKET"]
        try:
            keys = upload_outputs(
                args.output_dir,
                bucket_name,
                boto3.client("s3"),
                args.s3_prefix,
            )
        except (ClientError, BotoCoreError) as error:
            error_code = (
                error.response.get("Error", {}).get("Code", "AWS client error")
                if isinstance(error, ClientError)
                else type(error).__name__
            )
            parser.exit(1, f"S3 upload failed ({error_code}); no bucket was created.\n")
        except (FileNotFoundError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps({"uploaded_bucket": bucket_name, "uploaded_keys": keys}, indent=2))


if __name__ == "__main__":
    main()
