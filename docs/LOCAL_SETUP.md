# Local Setup and Verification

## Scope and safety

This is the zero-AWS baseline. It uses synthetic local accounts, SQLite, React/Vite, FastAPI, and Pandas ETL. Do not enter real personal data. No AWS credentials, AWS resources, uploads, or deployment steps are needed for this guide.

The local account picker is deliberately a development feature, not authentication. Run the backend only with `APP_MODE=local-demo` and `DONATION_STORE=sqlite`; the picker is enabled only with `VITE_AUTH_MODE=local-demo` in Vite development mode. Production builds do not enable the picker.

## Requirements

- Python with project dependencies (the CI workflow currently uses Python 3.12).
- Node.js 22 and npm.
- Existing local `.venv` and `frontend/node_modules` may be reused if already installed.

Install dependencies only if setting up a new local environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt -r etl/requirements.txt
cd frontend
npm ci
```

## Start the application

### Optional synthetic data

The application database is never seeded automatically. To create a separate populated local database:

```bash
.venv/bin/python -m backend.seed_data
```

The command uses `backend/data/sharebite-synthetic.db`. It creates eight internally consistent synthetic donation records and their lifecycle events, and it is idempotent for that seed. It refuses to modify an existing database that has tables but no ShareBite seed marker. It does not read or change `backend/data/app.db`. To choose another empty SQLite path:

```bash
.venv/bin/python -m backend.seed_data --database /tmp/sharebite-synthetic.db
```

Use the same database path for the API process below. Seed records and all displayed account names are illustrative synthetic examples.

Terminal 1, from the project root:

```bash
FOOD_REDISTRIBUTION_DB=backend/data/sharebite-synthetic.db \
APP_MODE=local-demo DONATION_STORE=sqlite \
  .venv/bin/uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd frontend
VITE_AUTH_MODE=local-demo npm run dev -- --host 127.0.0.1
```

Open the Vite URL shown in the terminal (normally `http://127.0.0.1:5173`). Stop each server with Ctrl+C when finished. Do not start a server merely to run tests.

The default SQLite file is `backend/data/app.db`. `FOOD_REDISTRIBUTION_DB` can point to a different file, for example a scratch copy. Startup only adds missing schema fields/indexes/tables; it does not reset or delete donations. Existing data should be backed up before any intentional migration. Automated tests use temporary databases.

## Demo walkthrough

1. Select **Ananya Raman · Donor**, create a listing with a future pickup deadline, and verify it appears.
2. Edit it while still available, then select **Meera Foundation · Recipient** and claim it.
3. Check that the event timeline shows backend-generated actions. Another recipient cannot claim the same donation.
4. Confirm pickup as the claiming recipient. Donors can cancel their own available listings.
5. Select **ShareBite Operations** to inspect backend analytics, local-only synthetic user controls, ETL reports, audit history, and local service health.
6. Try an invalid deadline, invalid quantity, wrong owner, or suspended demo profile; verify the UI reports the error and the API refuses the operation.

Local account IDs are predictable and must never be treated as real identities or reused for real users.

## Tests and checks

Run from the project root:

```bash
.venv/bin/python -m pytest -q backend/tests etl/tests
.venv/bin/python -m compileall -q backend etl
cd frontend
npm run lint
npm run build
```

Infrastructure validation, when the already-installed linter is available:

```bash
cd ..
.venv/bin/cfn-lint template.yaml
```

`sam validate --lint --template-file template.yaml` requires AWS SAM CLI. Do not install/run any deployment script as a substitute for template linting; SAM is not needed for local application use.

## ETL without cloud access

Use a temporary output directory; do not overwrite checked-in sample reports:

```bash
mkdir -p /tmp/food-etl-demo
.venv/bin/python etl/pipeline.py \
  --input etl/sample_data/donations.csv \
  --output-dir /tmp/food-etl-demo
```

Review the CSV and JSON reports in `/tmp/food-etl-demo`. The ETL does not upload data unless an explicit S3 flag and bucket are provided; do not use that mode as part of this local setup.

## Authentication configuration

The default local setup does not require Cognito configuration. A future reviewed AWS deployment could use `VITE_AUTH_MODE=cognito`, `VITE_COGNITO_ISSUER`, `VITE_COGNITO_CLIENT_ID`, and `VITE_API_BASE` in an untracked local env file after resource deployment and explicit approval. Do not put credentials or tokens into frontend variables. No such deployment/configuration was performed.
