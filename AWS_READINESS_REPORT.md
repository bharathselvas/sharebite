# AWS Readiness Report

**Project:** Cloud-Native Smart Food Redistribution and Analytics Platform Using Serverless Computing, ETL, and CI/CD
**Assessment date:** 2026-10-29
**Decision:** Local implementation is verified. AWS identity is now verified, but deployment remains blocked by missing IAM/GitHub configuration, unavailable billing evidence, and the absence of an approved change set.

## Executive summary

This is an enhancement to the existing project, not a greenfield replacement. The local app uses React/TypeScript, FastAPI, SQLite, fixed synthetic demo profiles, and a Pandas pipeline. Additive SQLite initialization preserves existing donation rows. Tests use isolated temporary databases.

The optional target includes Cognito OIDC authorization-code + PKCE, API Gateway HTTP API JWT authorizer, Lambda, a DynamoDB single table with five GSIs, private S3, scoped Lambda IAM, CloudWatch logs, and a SAM template. Donation mutations and audit events are transactionally coupled in the DynamoDB adapter. A deadline index allows bounded expiry work to query due records instead of repeating an unrelated newest-record page.

The `sharebite` IAM Identity Center profile was verified with `sts:GetCallerIdentity` as an assumed non-root role in the supplied account and target region. Read-only inventory found no CloudFormation stacks, Lambda functions, or DynamoDB tables in `ap-south-1`; S3 listed only `smartslot-datalake`, which is unrelated and must not be modified or reused. No AWS mutation, stack/change set, upload, or deployment was performed.

The account's free-tier plan and spending history remain unverified: `freetier:GetAccountPlanState` and `ce:GetCostAndUsage` returned `AccessDenied`. IAM role-policy inspection and `access-analyzer:ValidatePolicy` are also denied, so generated IAM policy candidates cannot be treated as approved. GitHub environments exist, but read-only inspection found no required variables, reviewer rules, or deployment-branch restrictions. No deployment approval is included.

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
| ETL | Bounded Pandas CSV/JSON plus a manual-only cloud Lambda that reads DynamoDB and writes reports to private S3 | Local tests use fakes; no live invocation/object exists. No Glue/Athena use. |
| Infrastructure | Parameterized SAM template for Cognito, API, Lambda, DynamoDB, private S3/CloudFront frontend, IAM, CloudWatch | SAM validation/build and `cfn-lint` passed locally. No stack/change set created. Five GSI, CloudFront, Cognito, and other cost drivers require review. |
| CI/CD | Test-only CI and separate manual deployment workflow with approval inputs, `main` condition, OIDC, input validation | Historical CI run exists for old committed SHA only. Current environments have no variables/protections; OIDC trust and roles are unverified. |
| Cost/security | Inventory, risk/limits, cleanup steps and approval boundary documented | No account-specific pricing/credit eligibility or spending cap is established. |

## AWS resource inventory (not deployed)

The read-only inventory on 2026-10-29 returned no active stack summaries, Lambda functions, or DynamoDB tables in `ap-south-1`. The account-wide bucket listing returned only `smartslot-datalake`; it is not approved for ShareBite and must not be touched.

The SAM template defines:

1. Cognito User Pool, public OAuth client, managed-login domain, and donor/NGO/admin groups. Self-registration is enabled; it does not permit users to assign a role. Email verification behavior can have cost implications.
2. API Gateway HTTP API, JWT authorizer and stage.
3. Python 3.12 Lambda function and scoped execution role.
4. DynamoDB donation/event table with five ALL-projection GSIs: `status-index`, `donor-index`, `recipient-index`, `entity-index`, and `expiry-index`.
5. Separate private S3 analytics and frontend buckets with encryption, public access blocks, ownership controls, and a 30-day analytics lifecycle.
6. CloudFront distribution and origin access control for HTTPS frontend delivery.
7. CloudWatch log groups configured with seven-day retention.
8. SAM/CloudFormation stack outputs. The workflow requires a separate pre-created artifact bucket and does not use `--resolve-s3`.

Potential cost dimensions include identity monthly active use, managed login/email delivery; API requests/transfer; Lambda invocation, duration/memory and logs; DynamoDB transactional/on-demand requests and table/GSI storage/write amplification; S3 storage/requests/transfer/lifecycle; CloudWatch log ingestion/storage and optional queries/alarms; deployment artifacts and any ancillary services. Verify all prices and credit coverage for the actual account and region before approval. SNS, EventBridge, Glue, Athena, CDN, custom domain, and NAT are not included.

## Validation and evidence

Record command outcomes in [IMPLEMENTATION_STATUS.md](./IMPLEMENTATION_STATUS.md) after final local verification. Distinguish:

- Local unit tests and fake AWS client behavior (not live integration).
- Template lint and workflow YAML parsing (not stack deployment).
- GitHub Actions history (not available unless an actual run exists).
- AWS Console/resource evidence (none exists in this assessment).

Live user/login, API requests, logs, metrics, DynamoDB records, S3 objects, billing/credit eligibility, deployment, and cleanup have not been verified. Read-only AWS identity/inventory calls and GitHub environment inspection were performed; IAM and billing reads were denied. Do not present synthetic or mocked output as AWS evidence.

## Approval gate and next review

No deployment approval is included. Before any future deployment, the user must explicitly approve after receiving the selected account/region, verified credit terms/plan, current itemized pricing drivers and usage assumptions, exact CloudFormation change set, IAM/OIDC review, deployment/artifact resource inventory, and cleanup procedure. Do not upgrade the account, configure credentials, upload data, or dispatch the deployment workflow in the meantime.

See [AWS Console and deployment guide](./docs/AWS_CONSOLE_DEPLOYMENT_GUIDE.md), [cost and security review](./COST_AND_SECURITY.md), and [architecture](./ARCHITECTURE.md).
