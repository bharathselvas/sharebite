# Project Plan

## Project

**Cloud-Native Smart Food Redistribution and Analytics Platform Using Serverless Computing, ETL, and CI/CD**

The existing application is upgraded in place. Its food redistribution workflow is a teaching use case; the emphasis is on cloud architecture, serverless patterns, persistence, security, ETL, automation, observability, and infrastructure as code. Use synthetic data only.

## Preservation and safety constraints

- Preserve the existing SQLite database, sample data, generated reports, and unrelated work.
- Automated database tests use temporary files. Schema initialization is additive and does not reset existing donation rows.
- Local application, tests, and CI do not require AWS credentials.
- No AWS resource is created, changed, deployed, or cleaned up without a separate explicit approval and an account-specific cost/security review.
- Do not upgrade the AWS account, configure credentials, upload data, or run GitHub deployment workflows as part of this project work.
- Keep every cloud feature clearly labeled as template-only, mocked, unverified, or live-tested as appropriate.

## Initial inspection and baseline

The prior inspection recorded an existing React/TypeScript frontend, FastAPI backend, SQLite database with six legacy donation rows, Pandas ETL, SAM template, and GitHub Actions. The database was inspected read-only; it was not migrated or reset during tests. The workspace is not a Git repository, so tracked/uncommitted state could not be determined with `git status`. Baseline tests and frontend checks passed before the latest implementation changes.

## Milestones and current acceptance

1. **Inspect and preserve existing project — complete** — read source, manifests, tests, infrastructure, docs, and local data; retained existing data and files.
2. **Harden local lifecycle and authorization — implemented and tested** — additive SQLite schema, fixed synthetic profiles, donation edits while available, role/status enforcement, atomic claims/transitions, expiry checks, and transactionally coupled audit records.
3. **Improve participant/admin workflows — implemented locally** — donor/recipient history, detail timelines, user status controls, filters, admin metrics, and bounded expiry processing. Synthetic demo identity switching is not real authentication.
4. **ETL and analytics — implemented and tested locally** — bounded CSV/JSON input, timezone validation, explicit row rejections without raw-row exposure, duplicate detection, per-unit summaries, daily/status reports, run summary, and mocked opt-in uploads.
5. **AWS readiness — prepared, not deployed** — Cognito PKCE target, API Gateway JWT authorizer, Lambda adapter, DynamoDB transactions and five GSIs, private S3, IAM, CloudWatch retention, and SAM template. Cloud user management/suspension and live AWS verification remain gaps.
6. **CI/CD and infrastructure — configured, not run remotely** — test-only CI and separate manually dispatched, approval-gated deployment workflow. OIDC role/trust/environment protections require manual review/configuration. AWS CLI and SAM CLI are not available in the recorded environment.
7. **Documentation and final verification — in progress** — reconcile docs to actual feature boundaries, run local tests/build/template lint, inspect generated production bundle, and record exact outcomes. No live AWS or GitHub evidence will be claimed.

## Local verification workflow

Use the commands in [docs/LOCAL_SETUP.md](./docs/LOCAL_SETUP.md). Run backend/ETL tests with a temporary test database, build the frontend, inspect ETL reports in a temporary output directory, and lint the SAM template with locally available tools. Do not start a development server unless needed for an approved local demonstration.

## Cloud deployment gate

Before any separately approved AWS deployment, identify each resource and side effect, verify current service availability/pricing for the actual account and region, estimate all usage and ancillary costs, inspect the exact CloudFormation change set and IAM policies, and present cleanup steps. Credits or free usage are not a spending cap. If eligibility or costs are uncertain, leave the project local and ask the user.

## Completion checklist

- [x] Existing project preserved and extended in place.
- [x] Local application workflow, tests, and ETL available without AWS.
- [x] Optional serverless target and least-privilege intent documented.
- [x] CI separated from manually gated deployment.
- [x] Local migration/data preservation and cloud limitations documented.
- [ ] AWS resources deployed or verified (not authorized; not required for completion).
