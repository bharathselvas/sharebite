# ShareBite — Cloud-Native Smart Food Redistribution and Analytics Platform

**Cloud-Native Smart Food Redistribution and Analytics Platform Using Serverless Computing, ETL, and CI/CD**

A local-first food redistribution and analytics product for a college cloud-computing project. ShareBite combines a role-based React application, FastAPI, SQLite, Pandas ETL, automated checks, and an optional AWS serverless template.

> **Zero-cost guardrail:** The local baseline creates no AWS resources. No AWS resources have been deployed by this project. Do not run deployment workflows or SAM/CloudFormation deployment commands until account/region eligibility, current pricing, the complete resource inventory, cleanup, and a specific deployment have been reviewed and explicitly approved. No AWS service is claimed to be free.
>
> The user reports approximately USD 100 in AWS credits; balance, expiry, eligible services, account plan, region coverage, and applicable terms have not been independently verified. Credits are not a zero-dollar guarantee.

## What is implemented

- **React + TypeScript frontend:** responsive donor, recipient, and operations portals; searchable listings; lifecycle actions; synthetic local accounts.
- **FastAPI backend:** additive SQLite migrations, role/status checks for fixed synthetic profiles, donation creation/edit-before-claim, atomic claims, pickup/cancellation/expiry, participant-scoped history, admin user status controls, analytics, pagination, and JSON export.
- **Optional cloud backend:** DynamoDB conditional updates and transactions that record donation audit events atomically; status/donor/recipient/event/deadline indexes; Cognito JWT authorizer; Lambda derives identity and role only from validated claims.
- **Pandas ETL:** bounded CSV/JSON ingestion, timestamp/type/state validation, duplicate rejection, minimized rejection details, unit-separated summaries, daily/status aggregates, and run metadata.
- **AWS target:** SAM template for Cognito, a Cognito-JWT-protected API Gateway HTTP API, Lambda, DynamoDB, private S3 analytics bucket, scoped IAM permissions, and bounded CloudWatch log retention.
- **Automation:** GitHub CI tests/build/template checks; separate manually gated, two-step AWS workflow using OIDC. Neither workflow has been run against AWS here.

## Local mode and deployment boundaries

- Local accounts are **not authentication**. The account switcher is enabled only with `VITE_AUTH_MODE=local-demo` in Vite development mode and `APP_MODE=local-demo` with `DONATION_STORE=sqlite` for FastAPI; use synthetic users/data only.
- SQLite is a local development store. The optional target Lambda adapter uses DynamoDB condition expressions for competing claims.
- The AWS frontend auth client uses OIDC authorization code + PKCE. API Gateway validates Cognito access tokens before Lambda; Lambda maps only the Cognito `sub` and assigned `cognito:groups` claims to roles. No cloud account is configured here.
- No AWS resource is deployed, no AWS Console screenshot or resource ID is available, and no live AWS behavior has been verified.
- The AWS template defines API, Lambda, DynamoDB table and five GSIs, S3, IAM, CloudWatch, Cognito User Pool/client/groups, and a managed-login domain. These are configuration only; none has been deployed. Account-plan eligibility and current costs are not verified.
- The deadline GSI lets bounded cloud expiry processing select due listings without repeatedly paging unrelated available donations; its storage/write costs are included in the review.
- The DynamoDB repository's donation/audit writes are transactionally coupled. Administrative aggregation reads are bounded to 500 records; this and the three role groups are teaching-scale design, not production user administration.
- Self-registration through the Cognito managed-login flow is a prepared design only; new users have no application role until an administrator assigns exactly one group. AWS-side list/suspend/reactivate user workflows are not implemented in the Lambda adapter. Local profile suspension is a demo-only SQLite feature.
- Audit events are application records, not an immutable or legally certified ledger. SQLite administrators with file access can alter the database.
- SNS, EventBridge, Glue, and Athena are not selected or provisioned.

## Local setup

Requirements: Python 3.12+ (3.14 was exercised locally), Node.js 22+, and npm. No AWS account or credentials are needed.

From the project root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r backend/requirements-dev.txt -r etl/requirements.txt
python -m pytest -q backend/tests etl/tests
```

For a populated demonstration, create a separate synthetic SQLite database. This command refuses to seed databases containing existing tables/data, and repeat execution against its own seeded file is idempotent:

```bash
.venv/bin/python -m backend.seed_data
```

The default target is `backend/data/sharebite-synthetic.db`; it does not touch `backend/data/app.db`. See the [synthetic data guide](./docs/SYNTHETIC_DATA_GUIDE.md).

In terminal 1, start the API:

```bash
FOOD_REDISTRIBUTION_DB=backend/data/sharebite-synthetic.db \
APP_MODE=local-demo DONATION_STORE=sqlite \
  .venv/bin/uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

In terminal 2, start the UI:

```bash
cd frontend
npm ci
VITE_AUTH_MODE=local-demo npm run dev -- --host 127.0.0.1
```

Open <http://127.0.0.1:5173>. The API health check is <http://127.0.0.1:8000/api/health>, and the interactive local API documentation is <http://127.0.0.1:8000/docs>.

The local database defaults to `backend/data/app.db`; set `FOOD_REDISTRIBUTION_DB` to another path if needed. The SQLite file is ignored by Git. Sample ETL input is under `etl/sample_data/`.

The backend startup migration only adds missing columns/tables and preserves existing donation records. The project tests use isolated temporary SQLite files. Do not remove the existing database to reset a demonstration.

See the detailed [local setup guide](./docs/LOCAL_SETUP.md) and [user guide](./docs/USER_GUIDE.md) for all workflows and limitations.

### Local walkthrough

1. As **Ananya Raman · Donor**, review the seeded donation set or create a listing with a future pickup deadline.
2. Edit an available listing. Switch to **Meera Foundation · Recipient** and claim it; a competing claim receives HTTP 409.
3. Confirm pickup as the claiming recipient. Open **History** on a donation you participate in to view the backend event timeline.
4. Switch to **ShareBite Operations** to view filtered analytics, audit activity, ETL reports, user-management controls for local synthetic accounts, and verified local health.
5. Try invalid quantity, past pickup time, editing after a claim, a cross-user action, and a suspended profile; the API returns validation/authorization/conflict errors.

The selectable local account list is fixed; account registration and trusted login are not production authentication. The local seed command is manual and never runs on application startup.

## ETL demonstration

```bash
.venv/bin/python etl/pipeline.py \
  --input etl/sample_data/donations.csv \
  --output-dir etl/output
```

Inspect `clean_donations.csv` / `cleaned_donations.csv`, `rejected_records.csv` / `rejected_donations.csv`, `donation_daily_summary.csv`, `donation_status_summary.csv`, `summary.json`, and `etl_run_summary.json`. The bundled input intentionally includes invalid and duplicate records. Rejected outputs include source row, record ID, and validation reason; they deliberately omit raw row contents. Quantity aggregates are separated by unit and are not converted across units.

To extract the local application's synthetic records as JSON for ETL, first create a donation in the app, then run:

```bash
curl --fail --silent http://127.0.0.1:8000/api/admin/export?actor_id=admin-demo \
  -o /tmp/demo-donations.json
.venv/bin/python etl/pipeline.py --input /tmp/demo-donations.json --output-dir etl/output
```

The export endpoint requires the demo admin ID; it is not real authentication.

For JSON, pass a JSON array of donation objects to `--input`. For optional Parquet output, install PyArrow in the same environment and add `--parquet`:

```bash
python -m pip install pyarrow
.venv/bin/python etl/pipeline.py --input etl/sample_data/donations.csv --output-dir etl/output --parquet
```

`etl/output/` is ignored. Optional upload requires `--upload-s3` and an explicitly configured existing private bucket; no bucket is created and ordinary ETL never uploads:

```bash
.venv/bin/python etl/pipeline.py --input etl/sample_data/donations.csv \
  --output-dir etl/output --upload-s3 --s3-bucket YOUR_REVIEWED_EXISTING_BUCKET \
  --s3-prefix ia3/reports
```

Do not run an upload without separate explicit approval and an account-specific review. The SDK credential provider chain is not configured in this task. No live upload has been performed. Output upload is multi-object and non-atomic: a failed request can leave earlier synthetic reports in the bucket. For a future extension, Glue/Athena remain unselected and require their own plan/cost review.

## Verification commands

```bash
.venv/bin/python -m pytest -q backend/tests etl/tests
cd frontend && npm ci && npm run lint && npm run build
cd ..
.venv/bin/python -m compileall -q backend etl
```

GitHub Actions runs comparable backend, ETL, frontend, and infrastructure validation. Workflow status in GitHub is actual only after that workflow has run; local success is not a live CI run.

## AWS, cost, and security guides

- [Architecture](./ARCHITECTURE.md)
- [Cost and security controls](./COST_AND_SECURITY.md)
- [Project plan](./PROJECT_PLAN.md)
- [Implementation status and verification log](./IMPLEMENTATION_STATUS.md)
- [AWS Console and deployment guide](./docs/AWS_CONSOLE_GUIDE.md)
- [CI/CD walkthrough](./docs/CICD_GUIDE.md)
- [College report outline](./docs/PROJECT_REPORT_OUTLINE.md)
- [AWS deployment readiness report](./AWS_READINESS_REPORT.md)
- [Local setup guide](./docs/LOCAL_SETUP.md)
- [User guide](./docs/USER_GUIDE.md)
- [API reference](./docs/API_REFERENCE.md)
- [ETL guide](./docs/ETL_GUIDE.md)
- [CI/CD guide](./docs/CI_CD_GUIDE.md)
- [AWS Console and deployment guide](./docs/AWS_CONSOLE_DEPLOYMENT_GUIDE.md)
- [College project report](./docs/COLLEGE_PROJECT_REPORT.md)

No action in these guides should be interpreted as approval to deploy. Deployment remains an explicit, separate user decision.
