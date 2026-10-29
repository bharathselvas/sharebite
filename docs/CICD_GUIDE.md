# CI/CD Demonstration Guide

## Test-only CI

`.github/workflows/ci.yml` runs for pushes, pull requests, or manual dispatch. It does not configure AWS credentials or deploy. It performs:

- Python dependency installation, bytecode compilation, backend and ETL tests, change-set verifier tests, and a synthetic ETL execution/report parse.
- Frontend npm install from the lock file, TypeScript lint, and Vite production build.
- Credential-marker checks, `cfn-lint`, workflow YAML parsing, and AWS SAM template validation.

A successful local run is not evidence of a GitHub Actions run. SAM CLI and `cfn-lint` may not be installed in a local environment; report their absence rather than inferring validation.

## Optional AWS deployment

`.github/workflows/deploy-aws.yml` has only a manual `workflow_dispatch` trigger. It is restricted to `main`, requires the `cost_reviewed` and `deploy_approved` inputs to be true, and uses GitHub OIDC temporary credentials. It never uses `--resolve-s3`, never creates an artifact bucket, and never executes a change set in the preparation job. The Boolean approval input is not an independent authorization; `aws-demo` must also have required independent reviewers and main-only branch restrictions configured.

### Prepare and review flow

1. Review current account plan, region eligibility, applicable prices, credit coverage, resource inventory, cleanup, and the proposed deployment. Obtain explicit approval before dispatch.
2. Dispatch `prepare-change-set` from `main`. GitHub gates the job through the protected `aws-demo` environment.
3. The workflow validates all required configuration, confirms the OIDC caller account, and classifies the stack:
   - No stack: `CREATE`.
   - Existing `REVIEW_IN_PROGRESS` stack: `CREATE` (no resources have been executed from that pending stack yet).
   - `CREATE_COMPLETE`, `UPDATE_COMPLETE`, or `UPDATE_ROLLBACK_COMPLETE`: `UPDATE`.
   - Any other status: fail closed.
4. `sam build` and `sam package` use the configured, pre-created artifact bucket and fixed `sharebite/artifacts` prefix. The workflow then calls CloudFormation `CreateChangeSet` directly with the explicit name `smart-food-demo-<run-id>-<run-attempt>`, the configured execution role, region, stack tags, the source commit, and the pre-created runtime permissions boundary. This bypasses SAM's generated change-set naming behavior.
5. The job waits for change-set creation and prints a readable resource-action/replacement table in the workflow summary. Empty or failed change sets fail safely. The resulting exact change-set ARN is printed for later review. It is **not executed**.
6. Independently dispatch `execute-reviewed-change-set` with the exact ARN and source commit from the prepare run. A separate `aws-demo-review` OIDC role reads the actual change set and current stack, verifies the returned `StackName`, `StackId`, change-set ID/name/type/status/source commit, and confirms that the stack has not been updated since the change set was created. It rejects resource types outside the repository allowlist, all removals/imports, all replacements, and modified resources without change details. It writes the resource summary. Only after that succeeds does the `execute` job wait at the protected `aws-demo` environment.
7. After an authorized reviewer approves that protected environment, the execution job checks out the same commit, confirms it is reachable from `main`, obtains temporary credentials, repeats account/region/stack/change-set identity checks, and executes only that exact change set. It then waits for stack completion, enables termination protection, builds the frontend using actual stack outputs, uploads it to the private frontend bucket, invalidates CloudFront, and smoke-tests the HTTPS frontend and API.

The create-change-set call gives CloudFormation a stack identifier for a first deployment even while no resources have been created. The workflow accepts either no stack record or that matching stack in `REVIEW_IN_PROGRESS`; it rejects a mismatched StackId. A first deployment can still fail if a previous pending change set or stack is in an unexpected state. Resolve that condition through a separately reviewed process; the workflow has no automatic cleanup fallback.

### Required GitHub variables and environment protections

For safe read-only AWS/GitHub readiness checks and review-only IAM/bootstrap artifacts, see the [AWS bootstrap guide](./AWS_BOOTSTRAP_GUIDE.md). Its `apply` mode is intentionally disabled; it does not dispatch this deployment workflow.

Set these as environment variables, not secrets:

| Environment | Required variables |
|---|---|
| `aws-demo` | `AWS_REGION` = `ap-south-1`; `AWS_ACCOUNT_ID` = selected 12-digit account; `AWS_DEPLOY_ROLE_ARN` = dedicated GitHub OIDC deployment role ARN; `CFN_EXECUTION_ROLE_ARN` = dedicated CloudFormation service role ARN; `RUNTIME_PERMISSIONS_BOUNDARY_ARN` = pre-created IAM permissions-boundary policy ARN; `SAM_ARTIFACT_BUCKET` = approved, pre-created artifact bucket name. |
| `aws-demo-review` | `AWS_REGION` = `ap-south-1`; `AWS_ACCOUNT_ID` = same selected account; `AWS_REVIEW_ROLE_ARN` = separate read-only GitHub OIDC role ARN. |

Configure `aws-demo` to allow only the `main` branch, require an independent reviewer, and prevent self-approval where available. Do not configure reviewers on `aws-demo-review`; restrict its deployment branch to `main`. The review role must be read-only and distinct from the deployment and CloudFormation execution roles.

### Artifact bucket requirements

The bucket must exist before a prepare run. Create it only in a separately approved AWS change. It must:

- Be in `ap-south-1` and be a ShareBite-approved bucket—not an assumed reuse of `smartslot-datalake`.
- Block all public access, have no public bucket policy, and use private access only.
- Default-encrypt objects (SSE-S3 is sufficient for this workflow) and use S3 Object Ownership `BucketOwnerEnforced`.
- Grant the deployment role only the required bucket-location/list and object-upload/read/multipart permissions under `sharebite/artifacts/*`.
- Allow that deployment role to read the bucket's public-access block, encryption, and ownership controls; the prepare job checks the region and requires all four public-access blocks, default SSE-S3, and `BucketOwnerEnforced` before packaging.
- Grant the CloudFormation execution role read access only to the same artifact prefix.
- Have a reviewed lifecycle for old deployment artifacts; lifecycle expiry, stored bytes, requests, and transfer may incur charges.

The workflow uploads a packaged template into that prefix and also uses `sam package` to upload function artifacts there. It does not configure the bucket, enable public hosting, or clean up prior packages.

### IAM/OIDC roles (configuration only; not created here)

- **Human Identity Center identity:** not reused by Actions and not represented by these workflow roles.
- **GitHub deployment role:** trust the GitHub OIDC provider with `aud=sts.amazonaws.com` and `sub=repo:bharathselvas/sharebite:environment:aws-demo`. Restrict actions to create/inspect/execute only named ShareBite change sets; inspect the exact artifact bucket; upload/read artifacts only in `sharebite/artifacts/*`; allow `s3:ListBucket`/`s3:GetBucketLocation` on and object uploads only to `sharebite-${account}-${region}-frontend`; create invalidations only for the ShareBite distribution; and `iam:PassRole` only for `CFN_EXECUTION_ROLE_ARN` to CloudFormation. CloudFront’s generated distribution ID prevents an exact distribution ARN from being known before first creation; constrain invalidation to this account and an approved tag condition only if supported, then replace with the exact ARN once available. It must not be AdministratorAccess or a Lambda role.
- **GitHub review role:** separate trust with `sub=repo:bharathselvas/sharebite:environment:aws-demo-review`; read-only `DescribeChangeSet` and `DescribeStacks` for the intended stack/change-set scope.
- **CloudFormation execution role:** trust `cloudformation.amazonaws.com`; its permission policy is separate and limited to the exact resources CloudFormation manages. It must create only the two named Lambda roles with `RUNTIME_PERMISSIONS_BOUNDARY_ARN`, attach the template's exact inline policies, and pass those roles only to Lambda. It must not be the human role or GitHub caller role.
- **Lambda application runtime role:** defined by the template; DynamoDB item/transaction actions on the donation table, GSI query, and function log writes.
- **Lambda ETL runtime role:** defined by the template; DynamoDB `Scan` on the donation table, S3 `PutObject` only under the analytics `etl/` prefix, and ETL log writes.

The current template creates the Cognito pool, HTTP API, and CloudFront distribution with generated IDs. Analytics and frontend bucket names are deterministic from the account ID and region to make S3 object policies reviewable; still check global name availability and account ownership. Exact-resource least-privilege policies cannot safely scope all generated resources in the first stack operation, especially CloudFront invalidation and generated API/Cognito ARNs. The template now requires a pre-created runtime permissions boundary; the CloudFormation execution role must create only the two named Lambda runtime roles, attach that boundary, and pass those roles only to Lambda. The deployment policy must be checked against the actual SAM-transformed template, including CloudFront and S3 changes. No role, trust policy, permission policy, OIDC provider, or bucket has been created or attached by this repository change.

### Persistent data and rollback

The template disables DynamoDB point-in-time recovery by default to avoid the associated backup-storage cost in the teaching demo. Enabling PITR requires a separate cost review. It applies `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain` to the donation table, Cognito pool, analytics bucket, and frontend bucket. This can leave billable resources behind after stack deletion/replacement and requires explicit manual cleanup. The analytics bucket expires objects after 30 days. A non-empty S3 bucket may prevent stack deletion unless its retention policy is honored. Rollback restores the prior stack configuration when possible but is not a backup guarantee and cannot recover data already deleted by an operation or lifecycle expiration.

The execution workflow enables termination protection after a successful create/update. A stack policy is not installed automatically; add one in a separately reviewed bootstrap step if the resource permission design supports it. The verifier blocks all resource removals and replacements until an explicit reviewed exception is implemented. An update that requires a denied deletion may fail and need operator-reviewed recovery. S3 lifecycle expiry and log retention remain independent destructive controls.

The workflow shows all proposed resource actions and replacements before protected execution, but approval is not a substitute for inspecting the change set. No blanket delete permissions or destructive cleanup command is included.

### Deployment blockers and local boundaries

- The artifact bucket, deployment/review OIDC roles, CloudFormation execution role, trust policies, environment variables, and GitHub environment protections must be provisioned/configured separately.
- The template creates Cognito, API Gateway, and CloudFront resources with generated identifiers; only the bucket names are deterministic. The reviewed exact-resource policy design still needs specific scoping for generated APIs, Cognito resources, and the CloudFront distribution.
- The new CloudFront frontend and AWS ETL Lambda add resources and cost exposure; current regional pricing and account eligibility have not been verified.
- The stack requires `RUNTIME_PERMISSIONS_BOUNDARY_ARN`; a suitably restrictive boundary must exist and be reviewed before creating a change set.
- The Cognito domain prefix must be globally available. Current cost, account-plan eligibility, credits, and service pricing must be reviewed independently.
- `prepare-change-set` and `execute-reviewed-change-set` are AWS operations that can incur charges or create resources when the reviewed change set executes. Do not dispatch without separate explicit approval.
- Never save AWS access keys as GitHub secrets. This change did not run or dispatch the workflow and did not call AWS.

See [AWS Console and Deployment Guide](./AWS_CONSOLE_GUIDE.md) for the resource inventory, cost review, console checks, and cleanup caveats.
