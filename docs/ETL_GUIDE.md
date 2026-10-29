# Pandas ETL Guide

## Run locally

```bash
.venv/bin/python etl/pipeline.py \
  --input etl/sample_data/donations.csv \
  --output-dir /tmp/food-etl-output
```

Input may be CSV or a JSON array of records. The deterministic data outputs are generated from the same input/configuration; run duration and output paths in `etl_run_summary.json` naturally vary by run. Input is bounded to 10 MiB and 10,000 rows.

## Pipeline

1. **Extract:** read CSV/JSON; JSON must contain a list of object records.
2. **Transform:** check required fields/types and donation statuses; reject non-finite/non-positive quantities; require timezone-aware timestamps; normalize timestamps to UTC; validate availability/deadline order; reject duplicate IDs.
3. **Load:** write clean/rejected reports, dashboard-ready daily/status summaries, and run metadata locally. Optional Parquet requires an available Parquet engine.

Invalid rows are not silently discarded. Rejected output contains source row number, record ID, and validation reason, not the raw row. Do not include secrets or personal data in source records.

## Outputs

- `clean_donations.csv` and compatibility alias `cleaned_donations.csv`
- `rejected_records.csv` and compatibility alias `rejected_donations.csv`
- `donation_daily_summary.csv` — grouped by UTC date and source unit
- `donation_status_summary.csv` — grouped by status and source unit
- `summary.json` and `etl_run_summary.json` — input/accepted/rejected/duplicate counts, completed pickups and unit-separated quantities, processing duration, output paths
- Optional `clean_donations.parquet`

Only `picked_up` records contribute to completed/redistributed quantity. Units are not converted or summed together. ETL metrics do not establish avoided waste or emissions.

## Tests

```bash
.venv/bin/python -m pytest -q etl/tests
```

Tests use temporary directories and mocked S3 clients. Do not overwrite `etl/output/` or `etl/sample_output/` during verification.

## Optional S3 upload (not used in this project work)

The default command is local-only. Upload requires `--upload-s3` plus a named existing bucket via `--s3-bucket` or `ETL_S3_BUCKET`; the script does not create buckets. It writes the six report files to a configured prefix with `AES256` server-side encryption, but does not set bucket policy/public settings. It relies on the local AWS SDK credential provider chain. Uploads are multi-object and non-atomic: a failure can leave earlier objects.

Do not invoke the upload path without separate explicit user approval, account/region/credit review, a reviewed pre-existing private bucket, and exact permission confirmation. No upload occurred. A future Glue replacement/Athena query is optional and has additional runtime/catalog/scanned-data/S3 pricing to verify.
