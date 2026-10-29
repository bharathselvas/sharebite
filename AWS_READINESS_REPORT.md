# AWS Readiness Report

**Project:** Cloud-Native Smart Food Redistribution and Analytics Platform Using Serverless Computing, ETL, and CI/CD
**Assessment date:** 2026-10-28
**Decision:** Local implementation is the safe verification baseline. The optional AWS target is prepared for review only. Deployment is not approved.

## Executive summary

This is an enhancement to the existing project, not a greenfield replacement. The local app uses React/TypeScript, FastAPI, SQLite, fixed synthetic demo profiles, and a Pandas pipeline. Additive SQLite initialization preserves existing donation rows. Tests use isolated temporary databases.

The optional target includes Cognito OIDC authorization-code + PKCE, API Gateway HTTP API JWT authorizer, Lambda, a DynamoDB single table with five GSIs, private S3, scoped Lambda IAM, CloudWatch logs, and a SAM template. Donation mutations and audit events are transactionally coupled in the DynamoDB adapter. A deadline index allows bounded expiry work to query due records instead of repeating an unrelated newest-record page.

The user reports about USD 100 in AWS credits. Credit balance/expiry/coverage, current account plan, region eligibility, and prices have **not** been checked. Credits do not guarantee zero out-of-pocket cost. No AWS account or console was accessed; no credentials were configured; no resources, uploads, stacks, deployment artifacts, GitHub workflow runs, or screenshots were created. Do not deploy without explicit approval and an account-specific review.

## Feature status and boundaries

| Area | Prepared/implemented | Verified or remaining limitation |
|---|---|---|
| Local app | Synthetic donor/recipient/admin flows, donation lifecycle, backend authorization against fixed demo profiles, SQLite transactions, expiry, history, analytics | Mock identities are not authentication and grant predictable demo roles. Never use real data. |
| SQLite safety | Additive schema migration and local expiry index; event writes share mutation transaction | Existing database was inspected read-only earlier and preserved; test suite uses temporary DBs. |
| Frontend | Responsive React UI, forms, search/status filters, participant timeline, analytics charts/filters, cursor-based load-more controls, local demo profile controls, Cognito client | Local profile controls are simulation only. Cloud user management/suspension UI and a full editable profile page are not implemented. |
| Cognito | Template enables self-registration, email verification, public SPA client, PKCE managed-login flow and role groups | Template/client only; no live auth tested. A newly registered user has no role until an admin assigns exactly one group. Cloud group assignment, user search/suspension/revocation workflows are not implemented. Email/managed-login costs unknown. |
| API auth | API Gateway JWT authorizer; Lambda derives `sub` and one recognized group from authorizer claims | No live token, issuer/client, API request, or Gateway-to-Lambda behavior verified. |
| DynamoDB | Conditional donation operations, transactional donation/event writes, paginated bounded queries, five GSIs | Fake-client tests only. Cloud admin donation/export/analytics bounds are 500 records. Live indexes, pagination, throttling, and transaction behavior are unverified. |
| Expiry | Claim deadline checks, SQLite due-date index, DynamoDB `expiry-index`, bounded repeat-safe admin action | No EventBridge schedule, background task, or notifications. |
| Audit history | Backend-generated UTC events, actor/status metadata and request IDs; event reads role/participant scoped | Application audit data is not immutable or legally certified. No fabricated history for legacy records. |
| ETL | Bounded Pandas CSV/JSON; validation, UTC normalization, duplicate/rejection reports, per-unit/daily/status summaries and run manifest | S3 integration is mocked only; local ETL defaults to no upload. No Glue/Athena use. |
| Infrastructure | Parameterized SAM template for Cognito, API, Lambda, DynamoDB, S3, IAM, CloudWatch | `cfn-lint` can run locally; SAM CLI validation was not available. No stack/change set created. Five GSI cost impact must be reviewed. |
| CI/CD | Test-only CI and separate manual deployment workflow with approval inputs, main-branch condition, OIDC, input validation | No GitHub run or AWS trust/environment setup. Reviewers, branch restrictions, role policy and trust conditions remain manual tasks. |
| Cost/security | Inventory, risk/limits, cleanup steps and approval boundary documented | No account-specific pricing/credit eligibility or spending cap is established. |

## AWS resource inventory (optional, not deployed)

The SAM template defines:

1. Cognito User Pool, public OAuth client, managed-login domain, and donor/NGO/admin groups. Self-registration is enabled; it does not permit users to assign a role. Email verification behavior can have cost implications.
2. API Gateway HTTP API, JWT authorizer and stage.
3. Python 3.12 Lambda function and scoped execution role.
4. DynamoDB donation/event table with five ALL-projection GSIs: `status-index`, `donor-index`, `recipient-index`, `entity-index`, and `expiry-index`.
5. Private S3 analytics bucket with encryption, public access block, ownership controls, and a 30-day example lifecycle.
6. CloudWatch log group configured with seven-day retention.
7. SAM/CloudFormation stack outputs. `sam deploy --resolve-s3` may use/create a separate artifact bucket that may need separate cleanup.

Potential cost dimensions include identity monthly active use, managed login/email delivery; API requests/transfer; Lambda invocation, duration/memory and logs; DynamoDB transactional/on-demand requests and table/GSI storage/write amplification; S3 storage/requests/transfer/lifecycle; CloudWatch log ingestion/storage and optional queries/alarms; deployment artifacts and any ancillary services. Verify all prices and credit coverage for the actual account and region before approval. SNS, EventBridge, Glue, Athena, CDN, custom domain, and NAT are not included.

## Validation and evidence

Record command outcomes in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) after final local verification. Distinguish:

- Local unit tests and fake AWS client behavior (not live integration).
- Template lint and workflow YAML parsing (not stack deployment).
- GitHub Actions history (not available unless an actual run exists).
- AWS Console/resource evidence (none exists in this assessment).

AWS CLI/SAM validation, live user/login, API requests, logs, metrics, DynamoDB records, S3 objects, billing/credit eligibility, deployment, and cleanup have not been verified. Do not present synthetic or mocked output as AWS evidence.

## Approval gate and next review

No deployment approval is included. Before any future deployment, the user must explicitly approve after receiving the selected account/region, verified credit terms/plan, current itemized pricing drivers and usage assumptions, exact CloudFormation change set, IAM/OIDC review, deployment/artifact resource inventory, and cleanup procedure. Do not upgrade the account, configure credentials, upload data, or dispatch the deployment workflow in the meantime.

See [AWS Console and deployment guide](./docs/AWS_CONSOLE_DEPLOYMENT_GUIDE.md), [cost and security review](./COST_AND_SECURITY.md), and [architecture](./ARCHITECTURE.md).
