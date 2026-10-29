# ShareBite AWS bootstrap and deployment-readiness guide

## Status and safety boundary

This guide describes a read-only diagnostic and a local plan generator. On 2026-10-29 the `sharebite` Identity Center profile was verified as an assumed non-root role in the supplied account and region. Regional read-only inventory returned no ShareBite stack, Lambda, or DynamoDB table; the only listed bucket was `smartslot-datalake`, which is unrelated and must not be used. The role was denied IAM policy inspection, IAM Access Analyzer validation, Cost Explorer, and Free Tier account-plan reads. Both GitHub environments exist but currently have no variables or protection rules. No ShareBite AWS resources have been created.

The scripts do **not** create or change AWS resources, IAM roles/policies, the GitHub OIDC provider, S3 buckets, GitHub variables/environments, or the application stack. There is intentionally no apply implementation. Generated policy documents are review candidates, not proof of least privilege and not instructions to attach policies automatically. The plan now emits a constrained CloudFormation execution-policy draft scoped to the template's fixed resource names, account, and region, plus a transform/action manifest. It has not been validated by IAM Access Analyzer or simulated in the target account; an administrator must review every action/resource and rollback delete before attaching it.

No command below deploys ShareBite or executes a CloudFormation change set. `scripts/aws_bootstrap_plan.sh apply` always fails closed.

## 1. Install/configure AWS CLI v2 SSO

Use the approved Identity Center start URL, SSO region, and account/role selection. Do not enter AWS access keys or paste SSO credentials into chat or source files.

```bash
aws --version
aws configure sso --profile sharebite
aws sso login --profile sharebite
aws sts get-caller-identity --profile sharebite
```

Confirm the returned account is the intended account and the ARN is an assumed Identity Center role, not `root`. `aws configure sso` prompts interactively for organization-specific values; those are not inferable from this repository. If `ShareBiteDeploy` has no permissions, ask the account administrator to grant a reviewed read-only diagnostic permission set first. Do not attach `AdministratorAccess` or attempt privilege escalation.

## 2. Run read-only preflight

The profile defaults to `sharebite`; the deployment region is fixed to `ap-south-1`. The preflight requires an explicit expected account ID, AWS CLI v2, and AWS SAM CLI. Before issuing any AWS service API call, it verifies that the profile is configured for IAM Identity Center SSO and refuses static credential fields, chained credential providers, or AWS credential environment variables. The artifact bucket and permissions-boundary ARN must be supplied from independently reviewed configuration. They are intentionally not guessed.

```bash
cd /home/bharath/projects/III-IA/cloud-computing

export AWS_EXPECTED_ACCOUNT_ID="$(aws sts get-caller-identity \
  --profile sharebite --query Account --output text)"
export SAM_ARTIFACT_BUCKET='REPLACE_WITH_ADMIN_APPROVED_BUCKET_NAME'
export RUNTIME_PERMISSIONS_BOUNDARY_ARN='REPLACE_WITH_VERIFIED_BOUNDARY_ARN'

bash scripts/aws_preflight.sh \
  --profile sharebite \
  --expected-account-id "$AWS_EXPECTED_ACCOUNT_ID" \
  --region ap-south-1 \
  --artifact-bucket "$SAM_ARTIFACT_BUCKET" \
  --boundary-arn "$RUNTIME_PERMISSIONS_BOUNDARY_ARN"
```

The two `REPLACE_...` strings are instructions, not valid resource values. Obtain actual values from the account administrator; do not put guessed values into GitHub configuration.

Optional role-name flags override the proposed naming convention:

```bash
bash scripts/aws_preflight.sh --help
bash scripts/aws_preflight.sh --profile sharebite --json \
  --expected-account-id "$AWS_EXPECTED_ACCOUNT_ID" \
  --artifact-bucket "$SAM_ARTIFACT_BUCKET" \
  --boundary-arn "$RUNTIME_PERMISSIONS_BOUNDARY_ARN"
```

The diagnostic checks AWS CLI v2 and SAM CLI, STS identity/account, IAM read access and GitHub OIDC provider/audience, expected role trust conditions, the exact S3 bucket region/public-access/encryption/ownership/lifecycle configuration, CloudFormation stack state/outputs/resources, DynamoDB indexes and the configured PITR state, Cognito groups, Lambda functions, runtime boundaries, API Gateway and CloudFront, and (when `gh` is installed and authenticated) GitHub environments/reviewers/branch restrictions. It never treats a denied or generic failed read as proof that a resource is absent. It does not retrieve or print credentials.

Bucket Object Ownership settings are checked, but AWS's read responses alone do not establish that the designated artifact bucket belongs to the intended account. Have the administrator verify its account ownership explicitly before use.

### Exit codes

| Code | Meaning |
|---:|---|
| `0` | All automated read-only prerequisites checked by the script passed. Manual billing, policy, and self-approval reviews still apply. |
| `1` | A resource or configuration prerequisite is missing or incorrect. |
| `2` | AWS authentication/permissions failed, GitHub checks were unavailable/uncertain, or a read result could not be safely interpreted. |
| `3` | Local input/tool configuration is invalid, AWS CLI v2 is unavailable, the active identity is root, or the expected account/region does not match. |

Use `--skip-github` only when intentionally doing AWS-only diagnostics; separately verify both GitHub environments. A preflight pass is not deployment authorization and does not prove that the deployment role has the required write permissions.

### Read permission handoff

For diagnosis, an administrator should grant only the read-only actions needed for the resources being inspected, including:

- `sts:GetCallerIdentity`
- IAM: `iam:ListOpenIDConnectProviders`, `iam:GetOpenIDConnectProvider`, `iam:GetRole`, `iam:GetPolicy`
- CloudFormation: `cloudformation:DescribeStacks`, `cloudformation:ListStackResources`
- S3: `s3:GetBucketLocation`, `s3:GetBucketPublicAccessBlock`, `s3:GetEncryptionConfiguration`, `s3:GetBucketOwnershipControls`, `s3:GetLifecycleConfiguration`
- DynamoDB: `dynamodb:DescribeTable`, `dynamodb:DescribeContinuousBackups`
- Lambda: `lambda:GetFunctionConfiguration`
- Cognito: `cognito-idp:ListUserPools`, `cognito-idp:ListGroups`
- API Gateway v2: `apigateway:GET` for the expected API
- CloudFront: `cloudfront:GetDistribution`

Scope resources to exact existing ARNs where IAM supports it. Some list/read actions require `Resource: "*"`. The administrator must validate every action/resource combination against AWS Service Authorization Reference and the selected role; this list is diagnostic guidance, not a ready-to-attach policy. GitHub environment inspection uses the already authenticated `gh` CLI and requires repository Actions/environment read access.

## 3. Generate deterministic review artifacts

Plan mode is the default and makes no AWS or GitHub API calls. Supply the account ID obtained from the identity check; it is not embedded in source. The artifact bucket is a candidate unless a verified bucket name is explicitly passed:

```bash
ACCOUNT_ID="$(aws sts get-caller-identity \
  --profile sharebite --query Account --output text)"

bash scripts/aws_bootstrap_plan.sh plan \
  --account-id "$ACCOUNT_ID" \
  --output-dir .sharebite-bootstrap-plan
```

If an administrator has approved and verified an artifact bucket, pass `--artifact-bucket "$SAM_ARTIFACT_BUCKET"`. Otherwise the plan proposes `sharebite-<account>-ap-south-1-artifacts`, explicitly marked unverified; S3 names are globally unique, so check ownership and availability before any creation.
Plan generation refuses to overwrite an existing artifact file. Inspect existing output first and use `--force` only when intentionally replacing previously generated plan files:

```bash
bash scripts/aws_bootstrap_plan.sh plan \
  --account-id "$ACCOUNT_ID" \
  --output-dir .sharebite-bootstrap-plan \
  --force
```

Generated files include:

- `report.md` and `plan.json` with the template resource inventory, proposed identities, GitHub environment variables, and unresolved review items.
- GitHub deployment/review OIDC trust policies restricted to the exact repository and environment subjects.
- CloudFormation service trust restricted to the account and `smart-food-demo` stack ARN.
- Scoped GitHub deploy/review and Lambda API/ETL permission candidates.
- A Lambda runtime permissions-boundary candidate.
- `cloudformation-execution-role-candidate.json`, a constrained draft for administrator review, and `cloudformation-execution-role-requirements.json`, the companion action/transform manifest.

The CloudFormation candidate contains limited `Resource: "*"` statements for resources that do not have an addressable ARN before creation (including the user pool and CloudFront distribution/OAC) and an API Gateway ARN pattern because API Gateway ARNs omit the account ID. It uses exact names for the DynamoDB table, S3 buckets, Lambda functions, IAM runtime roles, and log groups; IAM `PassRole` is limited to the two runtime roles and `lambda.amazonaws.com`, and role creation requires the configured permissions boundary. It includes narrowly named rollback delete actions. These statements can still be wrong or insufficient for the current CloudFormation provider behavior. The manifest explicitly records that IAM Access Analyzer and target-account simulation were not run. Do not attach this draft before those checks and an exact transformed-template review.

The candidate deployment policy includes an account-scoped CloudFront distribution wildcard because the stack creates its distribution ID dynamically. After a successful reviewed deployment, narrow it to the exact distribution ARN if compatible with invalidation workflow. The deploy candidate also uses `sts:GetCallerIdentity` with `Resource: "*"`, which is a read-only identity API that does not support resource-level scoping. Do not assume either generated candidate is approved.

The runtime policies mirror the current template's app and ETL permissions. The shared boundary candidate restricts each permission statement to the exact API or ETL role ARN with `aws:PrincipalArn`. The template already contains runtime inline policies and a permissions-boundary parameter; generated JSON is for comparison and administrator review, not a request to create duplicate roles. An administrator should validate the global condition-key behavior with IAM Access Analyzer before attachment.

The Python API and ETL runtime sources were also analyzed locally with IAM Policy Autopilot. This generates a useful, reproducible baseline, not a directly attachable permission set: the tool emits wildcards and extra service-authorized actions that must be checked against the actual template/runtime roles. Run the separate commands and review their full output; do not use `--upload-policies`:

```bash
uvx iam-policy-autopilot@latest generate-policies \
  backend/aws_handler.py backend/repositories.py \
  --region ap-south-1 --account "$AWS_EXPECTED_ACCOUNT_ID" \
  --service-hints dynamodb --pretty

uvx iam-policy-autopilot@latest generate-policies \
  etl/aws_handler.py etl/pipeline.py \
  --region ap-south-1 --account "$AWS_EXPECTED_ACCOUNT_ID" \
  --service-hints dynamodb s3 --pretty
```

These are application runtime policies only; they do not generate the GitHub deployment or CloudFormation execution policies. The local bootstrap generator emits candidates for those roles, but IAM Access Analyzer and target-account simulation were denied for the current operator. An authorized administrator must validate the exact SAM transform, generated policies, resource ARN support, and destructive rollback actions before any attachment. Do not copy the candidate blindly into the `ShareBiteDeploy` permission set; keep the human diagnostic identity read-only and use separate OIDC/service roles.

## 4. Check mode and intentionally disabled apply

`check` runs the preflight. It has the same required account, boundary and artifact configuration as the diagnostic:

```bash
bash scripts/aws_bootstrap_plan.sh check \
  --profile sharebite \
  --expected-account-id "$ACCOUNT_ID" \
  --artifact-bucket "$SAM_ARTIFACT_BUCKET" \
  --boundary-arn "$RUNTIME_PERMISSIONS_BOUNDARY_ARN"
```

`apply` is deliberately not implemented. It stops before making calls:

```bash
bash scripts/aws_bootstrap_plan.sh apply
```

If bootstrap resources are approved later, an account administrator should create them through the organization's reviewed IAM/IaC process. This tool is not a generic policy applier and does not deploy the application. No ShareBite bootstrap operation should be performed by editing a permission set or attaching a generated policy without a separate review and explicit authorization.

## 5. Administrator bootstrap sequence

1. Verify account ownership, account plan, service/region availability, current prices, credits, and budget alerts. The scripts do not query or guarantee billing eligibility.
2. Verify the AWS CLI Identity Center caller is the intended non-root human role and that the required diagnostic reads are allowed.
3. Generate the local plan; review every proposed ARN and policy. Confirm the proposed bucket name is globally available and not owned by another project.
4. Configure the GitHub OIDC identity provider for `token.actions.githubusercontent.com` with audience `sts.amazonaws.com`; check the existing provider before attempting anything. There must be only the intended provider for the account.
5. Create the GitHub deploy role trust for `repo:bharathselvas/sharebite:environment:aws-demo` and the read-only review trust for `repo:bharathselvas/sharebite:environment:aws-demo-review`. Verify audience and subject restrictions. Do not add branch wildcards or repository-wide subjects.
6. Attach a separately reviewed deploy permission policy. Confirm CloudFormation resource-level scopes and `iam:PassRole` exactly restrict the execution role and `iam:PassedToService=cloudformation.amazonaws.com`. Reconcile every operation in `.github/workflows/deploy-aws.yml`; it uses `CreateChangeSet`, `DescribeChangeSet`, `ExecuteChangeSet`, stack reads, termination-protection update, artifact operations, frontend uploads, and CloudFront invalidation.
7. Create the review role with only read-only CloudFormation change-set/stack operations. Ensure it cannot create, execute, update, or pass roles.
8. Create the CloudFormation execution role trust. Review `policies/cloudformation-execution-role-candidate.json` alongside `policies/cloudformation-execution-role-requirements.json`. Run `sam build --template-file template.yaml`, inspect the actual transformed `.aws-sam/build/template.yaml`, confirm all resource actions/scopes against AWS Service Authorization Reference, validate the policy with IAM Access Analyzer and target-account simulation, then prepare a non-executed change set and inspect its resource actions. Preserve the exact Lambda `PassRole` and permissions-boundary restrictions. The candidate includes rollback deletes on exact project resources; only attach after a human has accepted those exact destructive capabilities and verified retention behavior. If the required scope is not supportable, stop and revise the architecture rather than broadening permissions.
9. Create the restrictive permissions boundary before any stack preparation. Verify it allows no more than the API/ETL candidate role policies. `GetPolicy` existence alone is not proof of correct contents.
10. Create the dedicated artifact bucket only after separate authorization. Require `ap-south-1`, all four Block Public Access settings, default SSE-S3 encryption, `BucketOwnerEnforced`, and reviewed lifecycle expiry for `sharebite/artifacts/`. Do not reuse `smartslot-datalake` or any bucket whose ownership is unknown.
11. Configure GitHub repository environments in **Settings → Environments**. Set both to `main` only. Require an independent reviewer for `aws-demo`, prevent self-approval where available, and confirm the review role is read-only. Add only the documented environment **variables**. Do not create AWS key secrets.
12. Run read-only preflight again and compare all roles, trust documents, bucket configuration, GitHub settings, costs, and the exact stack template. A passing preflight is not authorization to dispatch deployment.
13. Only after separate explicit approval may an authorized operator use the existing protected `prepare-change-set → review → execute` process described in [CICD_GUIDE.md](./CICD_GUIDE.md). This guide never starts that process.

## 6. GitHub environment inspection/configuration

If `gh` is already installed and authenticated, read environment state without changing it:

```bash
gh auth status
gh api repos/bharathselvas/sharebite/environments
gh api repos/bharathselvas/sharebite/environments/aws-demo
gh api repos/bharathselvas/sharebite/environments/aws-demo-review
gh api repos/bharathselvas/sharebite/environments/aws-demo/deployment-branch-policies
gh api repos/bharathselvas/sharebite/environments/aws-demo-review/deployment-branch-policies
```

The diagnostic checks whether the environments exist, reviewer protection is present for `aws-demo`, and a branch policy is enabled. Independently confirm the only permitted branch is `main` and self-approval is blocked where supported. The review environment must not have a write-capable role. If CLI authentication or API permission is unavailable, use the repository settings UI; do not create PATs or expose credentials for this task.

Environment variables expected by the current deployment workflow:

| Environment | Variables |
|---|---|
| `aws-demo` | `AWS_REGION`, `AWS_ACCOUNT_ID`, `AWS_DEPLOY_ROLE_ARN`, `CFN_EXECUTION_ROLE_ARN`, `RUNTIME_PERMISSIONS_BOUNDARY_ARN`, `SAM_ARTIFACT_BUCKET` |
| `aws-demo-review` | `AWS_REGION`, `AWS_ACCOUNT_ID`, `AWS_REVIEW_ROLE_ARN` |

Set values only after the actual resources and trust policies have been verified. Do not store access keys in environment variables or GitHub secrets.

## 7. Costs, resources, cleanup, and recovery

Preflight and plan are read-only/local operations, but they do not prove AWS pricing or account-plan eligibility. The application stack may incur Cognito managed-login/email, API Gateway, Lambda, DynamoDB table/GSI, S3 storage/requests, CloudFront requests/transfer/invalidation, CloudWatch logs, and artifact bucket costs. The table defaults to PITR disabled; enabling it may add backup-storage charges. Check current regional pricing, the account plan, credits and credit expiry, and all ancillary usage before any resource creation. Free-use allowances are conditional, not a spend cap.

The template retains the donations table, Cognito pool, analytics bucket, and frontend bucket on deletion/replacement; PITR is disabled by default and the analytics bucket expires objects after 30 days. Stack termination protection is enabled by the deployment workflow after a successful operation. Retained resources and the separately managed artifact bucket can continue to incur charges. Never remove retention, disable termination protection, empty a bucket, delete a table, or clean up unknown resources without verifying exact ownership/data and separate approval.

If a read fails, report it as denied/uncertain unless the AWS response specifically proves absence. Ask an administrator to grant only the missing read action or confirm resource ownership. If stack status is unstable, do not retry deployment or remove a change set automatically; have an administrator inspect CloudFormation events and current resources. The plan generator does not create resources and the preflight performs no cleanup.

## 8. Local validation

```bash
python3 -m pytest -q backend/tests etl/tests scripts/tests
bash -n scripts/aws_preflight.sh scripts/aws_bootstrap_plan.sh
python3 -m compileall -q backend etl scripts
sam validate --lint --template-file template.yaml
git diff --check
sha256sum backend/data/app.db
```

These are local tests and static checks. They do not prove live IAM authorization, GitHub OIDC exchange, AWS resource creation, AWS pricing eligibility, or a successful deployment.
