# Cost and Security

## Status and cost boundary

The account's credit balance, expiration, eligible services, account plan, region coverage, and applicable terms have not been independently verified. On 2026-10-29 the configured `sharebite` IAM Identity Center session was verified as a non-root role, but `freetier:GetAccountPlanState` and `ce:GetCostAndUsage` were denied. Credits do not guarantee a zero-dollar bill and may not cover all services, regions, usage, or charges outside AWS.

The local baseline (SQLite, React/Vite, FastAPI, Pandas, tests) requires no AWS resources. Read-only identity and regional inventory checks were performed. No resource was created or changed, no deployment workflow was dispatched, and no data was uploaded. `smartslot-datalake` was the only listed bucket and is unrelated; never reuse or modify it. **Do not deploy based on this document.** Every service's credit/free-use eligibility for the actual account and region remains unknown.

Before any separate deployment approval, verify current regional prices and account eligibility, forecast usage with realistic bounds, review the exact change set and permissions, and present expected charges and cleanup. Do not upgrade the account or configure credentials.

## Resource inventory and pricing variables (optional template only)

| Resource/service | Intended use | Cost drivers and possible ancillary charges | Account/credit eligibility |
|---|---|---|---|
| Amazon Cognito User Pool/client | OIDC SPA users, groups, managed login; self-registration is enabled in the template but grants no role | Monthly active users, feature tier/managed login, domain configuration/availability, email verification delivery, data transfer | **Unknown; verify account, region, current plan, credit terms, and email/login pricing** |
| API Gateway HTTP API | HTTPS API routes and JWT authorizer | API requests, data transfer, optional API features | **Unknown** |
| AWS Lambda | API adapter and repository operations | Invocation count, duration, memory/architecture, CloudWatch ingestion/storage, transfer | **Unknown** |
| DynamoDB table | Donations and audit events, conditional transitions and transactions; template disables point-in-time recovery for the demo default | On-demand read/write requests, item storage, transaction request units; enabling PITR adds backup-storage charges | **Unknown** |
| DynamoDB GSIs (5) | `status-index`, `donor-index`, `recipient-index`, `entity-index`, `expiry-index` | Index storage and write amplification, queries/read requests; ALL projections duplicate attributes. `expiry-index` enables bounded deadline-ordered expiry and adds cost. | **Unknown** |
| Amazon S3 bucket | Private approved analytics reports; 30-day lifecycle in template | Stored bytes, PUT/GET/LIST requests, retrieval, lifecycle, encryption/configuration, transfer | **Unknown** |
| Amazon CloudFront | HTTPS delivery of the private frontend bucket through OAC | Requests, data transfer, invalidations beyond applicable allowances, and logging if enabled | **Unknown** |
| CloudWatch log group | Lambda logs, 7-day retention in template | Log ingestion and stored bytes; queries, metrics, alarms, dashboards, data transfer if added | **Unknown; retention is not an ingestion cost cap** |
| IAM runtime role | Narrow Lambda table/index/log actions | IAM is not assumed to be a primary direct charge; related features/services can incur charges | **Availability and surrounding feature eligibility unverified** |
| SAM/CloudFormation stack | Orchestrate the resources above | No assumption that IaC or stack operations make underlying resources free | **Unknown** |
| SAM artifact bucket | May be created/used by `sam deploy --resolve-s3`; outside application-stack cleanup in some setups | S3 storage, requests, transfer; removal may require separate approval | **Unknown** |
| GitHub Actions/OIDC | Local-independent CI and a future temporary-credential deployment path | GitHub plan/runner use; AWS deployment actions and created resources | **Unverified; no role/secret configured or workflow run** |
| SNS/EventBridge/Glue/Athena/CDN/custom domain/NAT | Not included or selected | Would add service-specific request, runtime, data scan, networking, DNS/certificate, and transfer costs | **Not included; no eligibility or pricing claimed** |

Other charges may apply from taxes, support plans, data transfer, account features, or usage outside the proposed stack. Cost Explorer and Free Tier reads were denied for this role, so current billing/credit status cannot be quoted. No exact total is claimed without verified prices, usage assumptions, and account eligibility.

## Implemented security controls and limitations

- Use only synthetic records; avoid real names, email addresses, identity/banking data, or sensitive donor/recipient details.
- Local mock identities are fixed and predictable, and can select synthetic roles. They are **not authentication**. Backend local mode requires `APP_MODE=local-demo` and `DONATION_STORE=sqlite`; the browser switcher requires Vite development mode plus `VITE_AUTH_MODE=local-demo`. Never expose this mode as production access.
- The production target uses Cognito authorization-code flow with PKCE and session-scoped browser storage. API Gateway validates issuer/audience/signature before Lambda; Lambda derives `sub` and one recognized application group from validated authorizer claims. The request body cannot set cloud actor identity.
- Cognito self-registration is enabled in the template but does not assign a role. An authorized administrator must assign exactly one role group. Cloud user listing, role assignment interface, suspension enforcement, and revocation workflow are not implemented. Local synthetic-profile suspension is not evidence of cloud suspension.
- Donation validation, ownership checks, allowed state transitions, and expiry are backend responsibilities. SQLite commits events with mutations; DynamoDB writes donation state and event in one transaction. Competing claims use conditional updates. These cloud semantics are tested with fakes, not live AWS.
- Audit events are ordinary application data. They are not cryptographically immutable, tamper-proof, or a certified ledger. Existing legacy rows have no fabricated event history.
- Local request IDs and minimized event metadata support troubleshooting; do not log bearer tokens, request bodies, passwords, contact data, or secrets. Lambda log retention is 7 days in the template; ingestion can still cost money.
- DynamoDB indexes are scoped in the API runtime role; the SAM API runtime has no administrator permissions and no S3 access. The separate ETL runtime role can scan the donation table and write only below the analytics `etl/` prefix.
- S3 blocks public access, uses server-side encryption, and expires demonstration objects after 30 days in the template. Lifecycle expiration is not free storage. Uploads require `--upload-s3` and an explicitly named existing bucket; ETL never creates a bucket or uploads by default. Multi-object upload is not atomic; failure can leave earlier reports present.
- GitHub CI does not need AWS credentials and does not deploy. The separate deployment workflow requires manual dispatch, `main`, explicit inputs, protected environments, and temporary OIDC credentials. Read-only GitHub inspection found both environments exist but have no variables, reviewers, or branch restrictions. No OIDC roles were verified.
- The bootstrap plan emits a constrained CloudFormation execution-policy draft. The current Identity Center role cannot inspect IAM role policies or call `access-analyzer:ValidatePolicy`; the draft has not been validated/simulated in the target account and is not approved to attach.
- The active AWS identity and regional resource inventory were read. No AWS resources were created or changed, no workflow was dispatched, and no data was uploaded.

## Operational limits and analytics integrity

- API list pages are bounded at 100. Cloud admin analytics/export queries are capped at 500 donations, and will fail rather than claim a complete aggregate beyond that limit.
- ETL rejects input above 10 MiB or 10,000 rows, reports rejected row number/ID/reason without copying raw rows, normalizes timestamps to UTC, and groups quantity by original unit.
- Claim rate is `(claimed + picked_up) / filtered donations`; completion rate is `picked_up / filtered donations`; expiry rate is `expired / (picked_up + cancelled + expired)`. Empty denominators produce zero. Quantities redistributed include only pickup-confirmed records, grouped by unit; no food-waste or environmental benefit is inferred.
- Expiry is enforced when claiming and can be processed in a bounded, repeat-safe admin action. No EventBridge schedule, SNS alert, alarm, or managed analytics service is configured.

## Cleanup inventory (only after separately approved deployment)

Never run cleanup against AWS without explicit approval and exact resource identifiers. Confirm project ownership before deleting anything.

1. Stop/disable any separately approved schedule or workflow.
2. Export only user-approved synthetic outputs.
3. Empty only the exact approved project bucket/prefix; confirm bucket name and contents first.
4. Delete the reviewed project CloudFormation stack and inspect events for retained/failed resources.
5. Inspect the SAM deployment artifact bucket separately; it may be outside the stack. Empty/delete only after confirming ownership and exact target.
6. Verify API, Lambda, DynamoDB table/five GSIs, S3 bucket, CloudWatch log group, Cognito pool/client/domain/groups, IAM roles/policies, and any approved ancillary resources are removed.
7. Check Billing/Cost Explorer later for delayed usage charges. Deletion does not reverse accrued charges.

No AWS cleanup is required for the local-only state. Preserve the existing SQLite database, sample data, and generated ETL artifacts; the user may remove them manually if desired.
