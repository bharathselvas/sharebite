# AWS Console, Deployment, and Cleanup Guide

## Current state

The project is local-only. There are no project AWS resources, deployment outputs, invocations, logs, screenshots, or resource IDs to show. The following steps are a future demonstration guide, not evidence that a deployment succeeded.

## Before any AWS activity

Do not upgrade the account or create resources as part of setup. The user reports approximately USD 100 in credits, but the balance, expiry, eligible services, account plan, region coverage, and current pricing have not been verified. Credits are not a zero-dollar guarantee. Before any separately approved deployment:

1. Select the account and region intentionally; confirm account type/plan, credit balance/expiry/coverage, current billing allowances and overage exposure in the account's Billing console.
2. Review current regional pricing for every item in the inventory below. Include storage, requests, function duration/memory, API calls, networking and data transfer, CloudWatch logs/retention, artifact storage, and any stack/deployment ancillary resources. AWS free-use allowances are conditional and are not a spending cap.
3. Review the exact CloudFormation change set. Set log retention and verify no unneeded resources appear.
4. Review the OIDC trust relationship and deployment IAM policy. Never use administrator access keys or commit credentials.
5. Provide the resource-specific usage/cost estimate, account eligibility evidence, and cleanup steps to the user and obtain explicit approval before resource creation.

If eligibility or a zero-cost estimate cannot be verified, keep the project local. The project template's Cognito user pool/domain, API Gateway, Lambda, DynamoDB table and GSIs, S3 bucket, log group, and SAM deployment artifact bucket all have potential billable usage. No account-specific plan entitlement has been checked.

## Template inventory (only if explicitly approved)

| Resource | Purpose | Important possible costs |
|---|---|---|
| Cognito User Pool/client | OIDC authorization code + PKCE client, self-registration, and role groups | User/feature tier, managed login domain, email verification/delivery and transfer |
| Cognito managed-login domain | OIDC browser sign-in/sign-out redirect | Domain availability and current feature-tier/usage pricing |
| API Gateway HTTP API | HTTPS API endpoint with Cognito JWT authorizer | Requests, response data transfer, optional API features |
| Lambda function | Python API adapter | Invocations, duration, allocated memory, CloudWatch logs |
| DynamoDB table + status/donor GSIs | Donation records, conditional state transitions, bounded paginated status/owner queries | On-demand read/write requests, table/GSI storage and index writes/queries |
| Private S3 analytics bucket | Optional ETL/report objects | Stored bytes, requests, transfer; 30-day lifecycle does not make usage free |
| CloudWatch log group | Lambda log output, 7-day retention | Log ingestion and stored bytes |
| Lambda IAM role/policies | Scoped table item actions, GSI query, function log writes | Standard IAM roles are not the primary direct charge; review ancillary services/features |
| API Gateway/Lambda permissions and SAM stack | Connect endpoint to handler | Underlying resources are billable; CloudFormation deployment artifacts/operations may add cost |
| SAM deployment artifact bucket | `sam deploy --resolve-s3` uploads packaged code | S3 storage, requests, transfer; this is managed outside the application stack and must be inspected/cleaned separately |

This template does **not** configure S3 website hosting, SNS, EventBridge, Glue, Athena, or a public CDN. Cognito is configured for the prepared auth flow, but account-plan eligibility, live login, group setup, email behavior, and prices have **not** been verified. The frontend remains locally served and needs reviewed outputs in a local `.env.local` file after any separately approved deployment.

## Prepared Cognito browser login

The prepared client uses the public Cognito app-client ID and issuer only, OIDC authorization-code flow with PKCE, and `sessionStorage` through `oidc-client-ts`. The access token is sent in an Authorization bearer header. Sign-out redirects to Cognito managed login. Never add a user-pool password or AWS credential to frontend configuration.

API Gateway validates token signature, issuer, and audience before Lambda. Lambda accepts identity only from `requestContext.authorizer.jwt.claims`. Self-registration is enabled in the template but does not grant application access: an administrator must assign exactly one appropriate `food-donors`, `food-ngos`, or `food-admins` group. No cloud user search/suspension UI is implemented. Local mock IDs never become cloud claims.

## Review the real AWS Console (only after deployment approval)

Use the selected AWS account and region; do not invent or copy placeholder IDs into a report.

1. **CloudFormation:** open Stacks and select `smart-food-demo`. Inspect stack status, Resources, Events, Outputs, and the change set. Save only genuine console evidence.
2. **Cognito:** verify actual User Pool ID, public app-client ID, issuer and managed-login domain from stack outputs. Confirm account-plan eligibility, groups, token settings, and email delivery behavior. Create only synthetic test users and assign group membership manually.
3. **API Gateway:** open the generated HTTP API and stage; use its actual CloudFormation output URL. Confirm the Cognito JWT authorizer uses the same issuer and public client audience. Only API Gateway's authorizer claims are trusted; never pass actor IDs in request bodies.
4. **Lambda:** inspect the function's configuration and execution role. Invoke only through a valid Cognito-authorized synthetic request; verify the function's Invocations and Errors metrics.
5. **DynamoDB:** inspect the table and `status-index`, `donor-index`, `recipient-index`, `entity-index`, and `expiry-index`. Verify donation state and `claimed_by` only with synthetic records. Indexes add storage/write cost. Do not report a live operation based on mock tests.
6. **S3:** inspect the output bucket's Block Public Access, encryption, and lifecycle settings. Upload only an approved synthetic ETL output to an already-created private bucket; no personal data.
7. **CloudWatch:** inspect the named function log group, 7-day retention, log streams, errors, and metrics. Do not log request bodies, tokens, or identity data.
8. **IAM:** inspect the function role for table-scoped `GetItem`, `PutItem`, `UpdateItem`, GSI-scoped `Query`, and log write actions. Inspect the separate GitHub OIDC role trust and permissions. Neither should be administrator.
9. **ETL:** run the local Pandas pipeline. Only after explicit approval and a bucket/identity review, use `--upload-s3` for an existing private bucket. This is not a Glue job.
10. **GitHub Actions:** show actual test workflow run history and, separately, any manually approved deployment run. Local or simulated output is not AWS Console evidence.

## GitHub OIDC setup (future, manual security work)

Do not store an AWS access key in GitHub secrets. An account administrator would have to intentionally configure GitHub's OIDC provider, a dedicated deployment role, the trust policy restricted to the exact repository and `aws-demo` environment, and a narrow permission policy. The role ARN and region belong in GitHub Actions **variables**, not credentials. Configure required reviewers on the GitHub `aws-demo` environment.

The deployment workflow is manually invoked, requires both cost-review and deployment-approval booleans, and is restricted by workflow condition to `main`. GitHub environment reviewers and allowed-branch restrictions still need to be configured manually. Its `prepare-change-set` operation packages code and creates a non-executed CloudFormation change set; `--resolve-s3` can create/use a separate SAM artifact bucket. Review the full change set and bucket before explicitly approving a second workflow run to execute the reviewed ARN from the same revision. Configure role permissions narrowly for only this stack and its resources; the SAM deployment role must be reviewed separately from the Lambda execution role. No workflow has been run from this project.

The execution role in the template is fixed to the project Lambda role name. A deployment role still needs permissions to manage this stack's named resources and the packaged Lambda artifacts, and narrowly scoped `iam:PassRole` for that Lambda role. Verify the account's CloudFormation service-role/deployment model and exact resource ARNs before writing its policy; do not use administrator access as a shortcut. A separate caller needs narrowly scoped `execute-api:Invoke` for the intended API/stage/method/routes.

## Cleanup (only after an approved deployment)

1. Stop/disable the workflow and any project automation.
2. Record outputs you explicitly need; avoid retaining personal data.
3. Empty the exact project analytics bucket, after verifying the account, region, and bucket name.
4. Delete the `smart-food-demo` CloudFormation stack in the reviewed account and region. Confirm stack deletion and inspect retained/failed resources.
5. Inspect and, if no longer used, remove the SAM deployment artifact bucket separately. It is not necessarily owned by the application stack. Confirm that no other stack or project depends on it.
6. Verify the API, Lambda, DynamoDB table/five GSIs, S3 buckets/objects, log group, Cognito user pool/client/domain/groups, and project IAM roles/policies have been removed.
7. Check Billing/Cost Explorer later for delayed or already-incurred charges.

Deletion cannot refund charges already incurred. No cleanup is necessary for the current local-only state.
