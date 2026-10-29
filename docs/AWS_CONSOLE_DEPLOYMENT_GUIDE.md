# AWS Console and Deployment Guide

## Current truthful state

There are no project AWS resources, resource IDs, screenshots, logs, invocations, or deployment outputs to inspect. AWS credentials/account settings were not accessed. This document describes what a later, separately approved deployment demonstration would verify; it is not authorization or deployment evidence.

The account owner reports approximately USD 100 in credits, but the balance, expiration, eligible services, account plan, region coverage, and billing are unverified. Credits are not a zero-dollar guarantee. Do not upgrade the account or deploy until account-specific pricing, eligibility, the exact change set, permissions, and cleanup have been reviewed and the user explicitly approves.

## Resource inventory in the template

| Service | Resource | Verify in console | Cost/security notes |
|---|---|---|---|
| Cognito | User Pool, public SPA client, domain, three groups | Sign-up, issuer/client, groups, token settings, actual email behavior | Self-registration does not grant a role; admin must assign exactly one group. Email/managed login may incur charges. |
| API Gateway | HTTP API and stage | JWT issuer/audience, routes, actual URL | Requests and transfer may cost; local origins only are configured. |
| Lambda | Python 3.12 function | Invocation/error metrics, timeout/memory, environment table name | Duration, memory, invocations, logs and transfer are cost drivers. |
| DynamoDB | Donation table, five GSIs | Table/items, conditional writes, indexes and queries | On-demand requests, table/index storage and write amplification; admin aggregate bound is 500. |
| S3 | Private ETL analytics bucket | Block Public Access, encryption, lifecycle, objects | Storage, requests and transfer may cost. No upload is authorized by this guide. |
| CloudWatch | Function log group, 7-day retention | Actual structured logs, retention and metrics | Ingestion/storage can cost even with bounded retention. |
| IAM | Lambda role | Table-scoped item actions, five index queries, log writes only | No Lambda admin or S3 permission. Deployment OIDC role is separate and not configured. |
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

Do not invent screenshots, resource identifiers, logs, bills, or successful requests. For the manual OIDC and stack procedure, see [AWS Console guide](./AWS_CONSOLE_GUIDE.md). No deployment, upload, or workflow dispatch is authorized here.
