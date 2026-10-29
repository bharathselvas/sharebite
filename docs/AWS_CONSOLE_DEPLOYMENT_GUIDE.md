# AWS Console and Deployment Guide

## Current truthful state

ShareBite bootstrap resources exist and were verified on 2026-10-29: the GitHub OIDC provider, three tagged scoped IAM roles, a tagged runtime boundary, and an empty, private, SSE-S3 artifact bucket. The `smart-food-demo` application stack, change set, frontend, API, Cognito pool, DynamoDB table, Lambda functions, and ETL outputs do not exist. There are no live application URLs, requests, or application logs. This document describes later verification; it is not evidence that the application is deployed.

The account plan reports PAID/ACTIVE and USD 0 remaining Free Tier credits. Cost Explorer is denied for the current identity; a previously reported approximate USD 100 credit balance is unverified. Credits are not a zero-dollar guarantee. Costs and credit coverage are incomplete. Do not execute the application stack until account-specific pricing, eligibility, the exact change set, permissions, cleanup, and independent reviewer approval are satisfied.

## Resource inventory in the template

| Service | Resource | Verify in console | Cost/security notes |
|---|---|---|---|
| Cognito | User Pool, public SPA client, domain, three groups | Sign-up, issuer/client, groups, token settings, actual email behavior | Self-registration does not grant a role; admin must assign exactly one group. Email/managed login may incur charges. |
| API Gateway | HTTP API and stage | JWT issuer/audience, routes, actual URL | Requests and transfer may cost; local origins only are configured. |
| Lambda | Python 3.12 function | Invocation/error metrics, timeout/memory, environment table name | Duration, memory, invocations, logs and transfer are cost drivers. |
| DynamoDB | Donation table, five GSIs | Table/items, conditional writes, indexes and queries | On-demand requests, table/index storage and write amplification; admin aggregate bound is 500. |
| S3 | Empty private SAM artifact bucket `sharebite-721733429166-ap-south-1-artifacts` exists; application analytics bucket not deployed | Artifact bucket Block Public Access, SSE-S3, `BucketOwnerEnforced`, tags, 90-day lifecycle, and empty prefix verified | Storage, requests and transfer may cost; no application analytics object exists. |
| CloudWatch | Function log group, 7-day retention | Actual structured logs, retention and metrics | Ingestion/storage can cost even with bounded retention. |
| IAM | Deployment/review/CloudFormation roles and runtime boundary exist; template Lambda roles are not deployed | Exact GitHub environment trust, scoped policies, boundary policy and tags | Deployment role simulation denies unrelated bucket and role access. Human `ShareBiteDeploy` still has AdministratorAccess. |
| CloudFormation/SAM | Stack and outputs | Stack status/events, exact resource inventory | SAM may create/use a separate artifact bucket. |

Eligibility and regional pricing for every service are unknown. See [COST_AND_SECURITY.md](../COST_AND_SECURITY.md) and [AWS readiness report](../AWS_READINESS_REPORT.md).

## Future demonstration checklist (only after approval)

1. **Billing/account:** confirm account plan, selected region, current credits/balance/expiry/coverage, current prices, and expected overage exposure.
2. **Change set:** examine every resource, IAM action, stack parameter, domain choice, API callback/CORS origin, and artifact bucket before execution.
3. **Cognito:** verify actual client/issuer/domain. Self-register only synthetic accounts; assign exactly one `food-donors`, `food-ngos`, or `food-admins` group through an approved admin process. Users cannot select/assign their own trusted group.
4. **API Gateway:** verify the JWT authorizer audience/issuer. Make a valid synthetic request and record the actual status/response.
5. **Lambda/CloudWatch:** verify invocations/errors and 7-day retention. Do not expose tokens, request bodies, or personal data in logs/screenshots.
6. **DynamoDB:** verify the donation row and corresponding event after a successful operation; show conditional conflict on competing claims. Inspect all five GSIs: `status-index`, `donor-index`, `recipient-index`, `entity-index`, `expiry-index`.
7. **S3/ETL:** run local Pandas ETL. Upload only an approved synthetic report to a reviewed existing private bucket; no Glue job is included.
8. **GitHub:** show actual test workflow history separately from any manually approved deployment run. Local tests are not GitHub/AWS evidence.
9. **Cleanup/cost:** follow exact resource inventory and cleanup procedure, then check billing for delayed usage charges.

Do not invent screenshots, resource identifiers, logs, bills, or successful requests. For the bootstrap inventory and remaining approval gate, see [AWS bootstrap guide](./AWS_BOOTSTRAP_GUIDE.md). No application deployment or workflow dispatch has been performed.
