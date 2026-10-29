# AWS Readiness Report

**Project:** Cloud-Native Smart Food Redistribution and Analytics Platform Using Serverless Computing, ETL, and CI/CD
**Assessment date:** 2026-10-29
**Decision:** Local implementation and GitHub CI are verified. AWS identity is verified, but deployment remains blocked by missing IAM/GitHub configuration, unavailable billing evidence, and the absence of a prepared change set.

## Executive summary

This is an enhancement to the existing project, not a greenfield replacement. The local app uses React/TypeScript, FastAPI, SQLite, fixed synthetic demo profiles, and a Pandas pipeline. Additive SQLite initialization preserves existing donation rows. Tests use isolated temporary databases.

The optional target includes Cognito OIDC authorization-code + PKCE, API Gateway HTTP API JWT authorizer, Lambda, a DynamoDB single table with five GSIs, private S3, scoped Lambda IAM, CloudWatch logs, and a SAM template. Donation mutations and audit events are transactionally coupled in the DynamoDB adapter. A deadline index allows bounded expiry work to query due records instead of repeating an unrelated newest-record page.

The `sharebite` IAM Identity Center profile was verified with `sts:GetCallerIdentity` as `arn:aws:sts::721733429166:assumed-role/AWSReservedSSO_ShareBiteDeploy_600daa5af1121ef0/sharebite-deployer`. Read-only inventory found no ShareBite CloudFormation stack; earlier regional inventory listed no Lambda functions or DynamoDB tables. S3 listed only `smartslot-datalake`, which is unrelated and must not be modified or reused. The current role cannot list the OIDC provider or read several service resources. No AWS mutation, stack/change set, upload, or deployment was performed.

The account's free-tier plan and spending history remain unverified: `freetier:GetAccountPlanState` and `ce:GetCostAndUsage` returned `AccessDenied`. IAM role-policy inspection and `access-analyzer:ValidatePolicy` are also denied, so generated IAM policy candidates cannot be treated as approved. `iam:ListOpenIDConnectProviders` is denied for resource `arn:aws:iam::721733429166:oidc-provider/*` to the active `ShareBiteDeploy` assumed role. Expected deployment roles and ShareBite buckets do not exist. GitHub CI run [40863469358](https://github.com/bharathselvas/sharebite/actions/runs/40863469358) passed on commit `beba997e7fd92dfc2ea8f00329eb60931f3d2376`. Both GitHub environments are now restricted to `main` with administrator bypass disabled, but `aws-demo` has no independent reviewer, and neither environment has its required variables. No change set or live deployment exists.

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
| CI/CD | Test-only CI and separate manual deployment workflow with approval inputs, `main` condition, OIDC, input validation | Current CI run 40863469358 passed. Environments allow only `main` and admins cannot bypass; independent reviewer, required variables, OIDC roles/provider, and AWS resources are still missing/unverified. |
| Cost/security | Inventory, risk/limits, cleanup steps and approval boundary documented | No account-specific pricing/credit eligibility or spending cap is established. |

## AWS resource inventory (not deployed)

The read-only inventory on 2026-10-29 returned no active stack summaries, Lambda functions, or DynamoDB tables in `ap-south-1`; current expected-resource reads for some Lambda/DynamoDB/Cognito items are denied and cannot prove absence. The account-wide bucket listing returned only `smartslot-datalake`; it is not approved for ShareBite and must not be touched. The expected ShareBite frontend and analytics buckets returned `NoSuchBucket`; the three expected deployment roles returned `NoSuchEntity`.

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
- GitHub Actions history (run 40863469358 passed, but does not indicate AWS deployment).
- AWS Console/resource evidence (none exists in this assessment).

Live user/login, API requests, logs, metrics, DynamoDB records, S3 objects, billing/credit eligibility, deployment, and cleanup have not been verified. Read-only AWS identity/inventory calls and GitHub environment inspection were performed; IAM and billing reads were denied. GitHub's main-only branch policies and disabled admin bypass are configured, but independent approval is still unavailable. Do not present synthetic or mocked output as AWS evidence.

## Deployment gate and next action

The user explicitly authorized proceeding with deployment. Execution is still blocked before change-set creation: the active `ShareBiteDeploy` permission set cannot inspect or create the required OIDC provider and roles, account-specific billing and Free Tier status cannot be verified, the artifact/frontend/analytics buckets do not exist, and GitHub has no independent reviewer for `aws-demo`. The two GitHub environments have been restricted to `main`, administrator bypass disabled, and factual account/region variables set. Do not weaken the gate or reuse `smartslot-datalake`. After an AWS administrator provisions and validates the dedicated IAM roles, permissions boundary, and private buckets, and a second authorized GitHub collaborator is available as reviewer, run preflight and prepare (but do not execute) a change set for review.

See [AWS Console and deployment guide](./docs/AWS_CONSOLE_DEPLOYMENT_GUIDE.md), [cost and security review](./COST_AND_SECURITY.md), and [architecture](./ARCHITECTURE.md).
