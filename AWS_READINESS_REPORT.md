# AWS Readiness Report

**Project:** Cloud-Native Smart Food Redistribution and Analytics Platform Using Serverless Computing, ETL, and CI/CD
**Assessment date:** 2026-10-29
**Decision:** Local implementation and GitHub CI are verified. ShareBite bootstrap infrastructure is provisioned. Application deployment remains blocked by the missing independent GitHub environment reviewer, incomplete billing evidence, and the absence of an approved change set.

## Executive summary

This is an enhancement to the existing project, not a greenfield replacement. The local app uses React/TypeScript, FastAPI, SQLite, fixed synthetic demo profiles, and a Pandas pipeline. Additive SQLite initialization preserves existing donation rows. Tests use isolated temporary databases.

The optional target includes Cognito OIDC authorization-code + PKCE, API Gateway HTTP API JWT authorizer, Lambda, a DynamoDB single table with five GSIs, private S3, scoped Lambda IAM, CloudWatch logs, and a SAM template. Donation mutations and audit events are transactionally coupled in the DynamoDB adapter. A deadline index allows bounded expiry work to query due records instead of repeating an unrelated newest-record page.

The `sharebite` IAM Identity Center profile was verified with `sts:GetCallerIdentity` as `arn:aws:sts::721733429166:assumed-role/AWSReservedSSO_ShareBiteDeploy_600daa5af1121ef0/sharebite-deployer` in account `721733429166` and region `ap-south-1`. The exact `smart-food-demo` CloudFormation stack is absent. ShareBite bootstrap resources now exist: the GitHub OIDC provider; tagged deployment, read-only review, and CloudFormation roles; a tagged runtime boundary; a private, encrypted, owner-enforced artifact bucket with a 90-day lifecycle; and GitHub environment variables. The artifact bucket is empty. `smartslot-datalake` is unrelated and was not queried or touched. No application stack, change set, frontend, API, Cognito pool, DynamoDB table, Lambda function, analytics bucket, or application data was created.

The account plan reports PAID/ACTIVE and USD 0 remaining Free Tier credits. Cost Explorer returned `AccessDeniedException: User not enabled for cost explorer access`; total charges and any additional credits are not fully verified. IAM Access Analyzer validation returned no findings on the current deployment, review, CloudFormation, runtime, and boundary policy candidates after correcting the source configuration. The deployment-role policy simulation allowed uploads only to the ShareBite artifact prefix and denied an unrelated bucket and unrelated role passing. GitHub CI run [40868228770](https://github.com/bharathselvas/sharebite/actions/runs/40868228770) passed on commit `26690c1bc36855cc1d21c7a8d8df80f7d97a31d0`. Both GitHub environments are main-only with administrator bypass disabled, and all documented variables are set. `aws-demo` has no independent reviewer; the only repository collaborator found was the owner. No change set or live application deployment exists.

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
| CI/CD | Test-only CI and separate manual deployment workflow with approval inputs, `main` condition, OIDC, input validation | CI run 40868228770 passed. OIDC provider/roles and variables are configured; environments allow only `main` and admins cannot bypass. Independent `aws-demo` reviewer remains missing. |
| Cost/security | Inventory, risk/limits, cleanup steps and approval boundary documented | PAID plan, USD 0 remaining Free Tier credits; Cost Explorer denied, so total costs/credits and spending cap remain unverified. |

## AWS resource inventory (not deployed)

The exact `smart-food-demo` stack lookup returned not found. The bootstrap OIDC provider, roles, runtime boundary, and artifact bucket exist and were verified. No application Lambda, DynamoDB table, Cognito pool, frontend/analytics buckets, or change set has been created. `smartslot-datalake` remains unrelated and must not be touched.

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
- GitHub Actions history (run 40868228770 passed, but does not indicate AWS application deployment).
- AWS Console bootstrap evidence exists for the OIDC provider, scoped roles, boundary, and empty artifact bucket; no application stack evidence exists.

Live user/login, API requests, application logs/metrics, DynamoDB records, analytics/frontend S3 objects, billing/credit eligibility, deployment, and cleanup have not been verified. GitHub's main-only branch policies and disabled admin bypass are configured, but independent approval is still unavailable. Do not present synthetic or mocked output as AWS evidence.

## Deployment gate and next action

The user explicitly authorized proceeding with deployment. The dedicated OIDC provider, roles, permissions boundary, artifact bucket, and GitHub role variables are now provisioned. The application change set has not been prepared because GitHub's `aws-demo` environment has no independent required reviewer; repository collaborator inspection returned only the owner. Cost Explorer access is denied and the account plan reports USD 0 remaining Free Tier credits, so account-wide charges and any additional credits are not fully verified. Do not weaken the gate or reuse `smartslot-datalake`. After an independent authorized reviewer is configured and cost/change-set review is complete, run the existing preparation and review flow; do not execute until approval is recorded.

See [AWS Console and deployment guide](./docs/AWS_CONSOLE_DEPLOYMENT_GUIDE.md), [cost and security review](./COST_AND_SECURITY.md), and [architecture](./ARCHITECTURE.md).
