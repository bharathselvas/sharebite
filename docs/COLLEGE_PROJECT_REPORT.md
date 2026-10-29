# College Project Report

## Title

**ShareBite: Cloud-Native Smart Food Redistribution and Analytics Platform**

## Abstract

ShareBite uses a synthetic food-donation workflow to demonstrate cloud-native application architecture. Its local baseline combines role-based React/TypeScript portals, FastAPI, SQLite storage, and a Pandas ETL pipeline. An explicit idempotent seed command creates a separate synthetic SQLite dataset and refuses databases containing existing tables without a ShareBite seed marker. The optional target architecture uses Amazon Cognito, API Gateway HTTP API, Lambda, DynamoDB, S3, IAM, CloudWatch, and SAM/CloudFormation. Local tests and a production frontend build provide repeatable evidence without cloud credentials or resources. Cloud integrations are template-only or mock-tested, not live deployed. The user's reported AWS credits and service eligibility have not been independently verified.

## Problem context and project objectives

Surplus food redistribution provides a concrete domain for modeling listings, claims, collection confirmations, expiry, user roles, and operational analytics. The technical objectives are to demonstrate:

- A responsive client and validated API.
- Backend authorization and state integrity.
- Local relational persistence and an optional serverless NoSQL target.
- Application audit history and request correlation.
- Deterministic local ETL/analytics output.
- Test automation, infrastructure as code, monitoring design, and cost/security review.

The system does not provide operational food-safety certification, prove physical delivery, or quantify environmental impact.

## Architecture

Use [ARCHITECTURE.md](../ARCHITECTURE.md) for the local and optional AWS diagrams, service responsibilities, DynamoDB access patterns, event behavior, limits, and metric definitions.

### Local implementation

React/TypeScript communicates with FastAPI. SQLite stores donation state, fixed synthetic profiles, and transactional application events. The local API provides account-scoped donor/recipient dashboard summaries from the database, and a Pandas process consumes synthetic CSV/JSON or authorized exports and writes cleaned/rejected records and summaries.

### Optional target

Cognito OIDC authorization code + PKCE authenticates a browser user; API Gateway validates the JWT before Lambda. Lambda derives identity/role from verified claims and accesses a DynamoDB single table. Donation state and event writes use DynamoDB transactions and conditional state updates. Local ETL can optionally upload only approved results to an existing private S3 bucket. IAM scopes runtime access; CloudWatch stores logs with bounded retention. No service is assumed eligible/free, and no service was deployed.

## Data integrity and security

Donations use `available`, `claimed`, `picked_up`, `cancelled`, and `expired` statuses. Claims require an available, unexpired listing and are conditional to prevent two recipients from claiming concurrently. Event records are backend-generated and written with successful state changes. They are application audit data, not a tamper-proof ledger.

Local demo identities are fixed, predictable role simulations. Cognito self-registration is prepared, but users require an administrator-assigned role group; cloud user management, suspension, and revocation workflows are not implemented. Synthetic data only. See [COST_AND_SECURITY.md](../COST_AND_SECURITY.md).

## ETL method and outputs

Extraction accepts bounded CSV/JSON. Transformation validates record schema and status, normalizes timezone-aware timestamps to UTC, rejects duplicates and invalid quantities, and reports rejected row number/ID/reason without copying raw rows. Loading generates cleaned records, rejected reports, daily and status aggregates, and run metadata. Completed quantities include only pickup-confirmed records and are separated by unit. See [ETL guide](./ETL_GUIDE.md).

AWS Glue and Athena are optional future alternatives, not used in the baseline. Their runtime, catalog, scan, and storage costs would need individual review.

## CI/CD and infrastructure

Test CI runs Python tests/compilation, ETL sample output, frontend type/build checks, CloudFormation lint, workflow YAML parsing, and SAM validation on GitHub runners. A separate manually triggered OIDC deployment workflow has explicit boolean approval gates and requires a protected GitHub environment and `main`. The workflow was not dispatched. SAM/CloudFormation template validation does not establish that a live deployment is cost-eligible or successful.

## Verification results

Record only actual local command results in [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md). Label fake AWS clients as mocks and don't present their results as AWS integration. AWS account, console, credits, and GitHub run evidence are not available in this workspace.

Suggested demonstration:

1. Start the local app and create/edit a synthetic listing.
2. Compete for a claim and verify one successful claim only.
3. Confirm pickup and inspect the audit timeline.
4. Run ETL to a temporary output directory and inspect clean/rejected/summary reports.
5. Show local tests/build and the optional architecture/template.

## Limitations and future work

- Add cloud-side Cognito user/group administration and suspension enforcement with an explicit authorization model.
- Extend the current compact dashboard into broader accessible trend/status/category visualizations.
- Replace bounded 500-item aggregate with a validated scalable analytics design if data grows.
- Add tested live AWS behavior only after explicit authorization, cost review, and a small change-set review.
- Consider scheduled expiry/notifications only after cost, permission, and failure-mode review.
- Independently verify account credits and plan eligibility before any deployment.

## References and appendices

Use current official AWS service/pricing documentation and the actual account Billing console at report-submission time. Include only genuine test output, screenshots, resource identifiers, and GitHub run links, each with a date and clear environment label. Do not fabricate deployment evidence or quote unverified costs.
