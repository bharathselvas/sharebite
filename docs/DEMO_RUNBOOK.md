# ShareBite live demonstration runbook

## Deployment status and values

This runbook is a procedure, not evidence of deployment. At the time it was written, the `smart-food-demo` stack did not exist in `ap-south-1`, and no public frontend or API URL was available. The only discovered S3 bucket was `smartslot-datalake` in another region; it is not approved for ShareBite and must not be used.

After an approved deployment, copy actual values from the GitHub deployment summary:

| Value | Current state |
|---|---|
| Frontend HTTPS URL | Not deployed; use `FrontendUrl` from the successful workflow summary |
| API base URL | Not deployed; use `ApiBaseUrl` from the successful workflow summary |
| Stack status and commit | Not deployed; use the workflow summary and CloudFormation |
| ETL Lambda name | Not deployed; use `ETLFunctionName` from stack outputs |
| Analytics bucket | Not deployed; use `AnalyticsBucketName` from stack outputs |

Do not replace these with guessed resource IDs or URLs.

## A. Before the demo

1. Confirm the latest CI run for the deployed commit passed.
2. In GitHub, open the manually triggered deployment run and verify the source commit, reviewed change-set summary, independent `aws-demo` environment approval, stack completion, and HTTPS/API smoke checks.
3. In the AWS Console, select the reviewed account and `ap-south-1`. Confirm the `smart-food-demo` stack is `CREATE_COMPLETE` or `UPDATE_COMPLETE`, termination protection is enabled, and outputs match the GitHub summary.
4. Open the frontend URL on both laptops. The distribution is public HTTPS; neither laptop needs AWS credentials or access to the developer’s machine.
5. Create two distinct synthetic Cognito users before presenting: one assigned only to `food-donors`, one only to `food-ngos`. Use the Cognito administrator’s approved console workflow to assign exactly one group per user. Do not share passwords in source control or this runbook.
6. Confirm the Cognito callback/logout URLs include the actual CloudFront URL (the template configures it) and that each user can sign in. Avoid real personal information; test Cognito email delivery and pricing before enabling signup.

## B. Two-laptop donor/recipient flow

1. **Laptop A — donor:** open the HTTPS frontend, sign in with the donor account, and choose **Create donation**.
2. Enter clearly synthetic data, for example: “Demo vegetable boxes”, quantity `12`, unit `portions`, category `produce`, pickup location `Demo collection point`, and a deadline at least one hour ahead. Submit once.
3. Note the returned donation ID or the food name and creation time. The UI displays data from the authenticated API; the write is stored in DynamoDB.
4. **Laptop B — recipient:** open the same HTTPS URL, sign in with the separate NGO account, and open **Browse food**.
5. The donation should appear after the next refresh (the authenticated cloud view refreshes every eight seconds while visible). It can also be fetched immediately with **Refresh**.
6. Claim it on Laptop B. A successful claim changes the persistent DynamoDB status to `claimed`; another recipient attempting to claim the same record should receive a conflict rather than become a second claimant.
7. **Laptop A — donor:** wait for polling or press **Refresh**. The donor’s listing should show the `claimed` status. Refresh both browsers to demonstrate persistence.
8. Laptop B can mark pickup complete from the claimed donation. Laptop A should then see `picked_up` after refresh.

No two-laptop demonstration has been run yet. Do not claim this outcome until the live smoke test has actually been observed.

## C. AWS ETL demonstration

1. In the AWS Console, open the deployed `ETLFunctionName` Lambda stack output (default `smart-food-demo-etl`).
2. Select **Test**, create a test event with `{}`, and invoke it. This is a real AWS invocation that scans the configured DynamoDB table, writes to S3, and may incur charges; do it only after account pricing/credit status has been reviewed and the operator approves this invocation.
3. Confirm the invocation returns `status: succeeded`, a run ID, counts, and an `s3://.../etl/runs/<run-id>/` output prefix. A failed invocation must not be described as successful.
4. Open CloudWatch Logs for `/aws/lambda/smart-food-demo-etl`; find the structured `sharebite_etl_completed` event for that run ID. Failures emit `sharebite_etl_failed` and the invocation fails.
5. Open the private analytics bucket output prefix from the response or `AnalyticsBucketName`. Verify the six objects:
   - `clean_donations.csv`
   - `rejected_records.csv`
   - `summary.json`
   - `donation_daily_summary.csv`
   - `donation_status_summary.csv`
   - `etl_run_summary.json`
6. In `summary.json`, compare `input_records`, `total_clean_donations`, `rejected_records`, `duplicate_records`, `completed_pickups`, `donations_by_status`, and unit-separated quantities. These are computed from the DynamoDB scan; they are not seed metrics.

The function projects only the ETL donation fields, enforces the existing 10,000-record bound, runs the same Pandas pipeline as local tests, and writes under a Lambda request-ID prefix. It has read-only DynamoDB scan permission and S3 `PutObject` permission limited to the analytics `etl/` prefix. Do not invoke it on real personal data.

An authorized operator with an approved SSO profile can invoke it from a terminal instead of the Console:

```bash
aws lambda invoke \
  --profile sharebite \
  --region ap-south-1 \
  --function-name smart-food-demo-etl \
  --invocation-type RequestResponse \
  --cli-binary-format raw-in-base64-out \
  --payload '{}' \
  /tmp/sharebite-etl-response.json
python -m json.tool /tmp/sharebite-etl-response.json
```

For a non-default stack name, use the actual `ETLFunctionName` output. The invoking identity separately needs `lambda:InvokeFunction`; this documented command performs a real invocation and was not run during repository work.

## D. GitHub CI/CD demonstration

1. Open **Actions → Test and validate** and show the Python/ETL/verifier test result, frontend lint/build, credential-marker check, and infrastructure checks.
2. For a deployment, first review current billing eligibility, all resource prices, cleanup, IAM/OIDC trust, runtime boundary, artifact bucket, and GitHub environment settings. The current repository state is not authorization to create AWS resources.
3. Configure `aws-demo` for `main` only with independent required reviewers and self-approval disabled where available. Configure `aws-demo-review` for `main`; its role must be read-only.
4. Trigger **Optional AWS deployment** on `main` with `prepare-change-set`, cost review acknowledged, and the domain prefix. Preparation produces but does not execute a change set.
5. Inspect the complete Actions summary, including all resource action/type/replacement details. The verifier rejects unapproved resource types, removals, imports, and replacements.
6. Start a separate workflow dispatch using the exact change-set ARN and 40-character source commit from the prepare summary. Verify the review job’s current stack identity/freshness checks. An independent reviewer must approve the protected `aws-demo` environment before the execute job can proceed.
7. After deployment, verify stack completion, termination protection, frontend/API smoke checks, commit SHA, URLs, and ETL Lambda output. The verifier cannot prevent a console/other-principal stack update in the tiny interval between its final check and execution; restrict other writers during the deployment window.

The Boolean `deploy_approved` is only a workflow condition; it does not replace GitHub environment protection.

## E. Troubleshooting

| Symptom | Check |
|---|---|
| Login fails or returns to the callback | Verify the actual Cognito issuer/client ID, assigned single role group, managed-login domain, and exact CloudFront callback/logout URLs. |
| CORS error | Confirm browser origin equals the CloudFront `FrontendUrl`; confirm the API stack has completed with the current `DonationsApi` CORS configuration. |
| API fails | Check the API URL includes the deployed stage, `/api/health`, API Gateway authorizer, Lambda errors, and CloudWatch logs. |
| Donation is not visible | Ensure Laptop A used a donor group, the request returned success, both clients are on the same deployment, and Laptop B refreshed or waited for polling. Check DynamoDB table and Lambda role permissions. |
| Claim fails | Refresh and check current status/deadline. HTTP 409 is expected if the record was already claimed or its state changed. |
| ETL invocation fails | Read the Lambda error and CloudWatch log stream. Verify the environment table/bucket values, DynamoDB scan access, Pandas package, memory/timeout, and S3 `PutObject` access. |
| S3 report is missing | Use the invocation’s exact run ID and output prefix; do not assume a prior output is from the latest run. Check the function result and logs. |
| OIDC access denied | Confirm exact GitHub repository/environment `sub`, audience, configured provider, role ARN, account/region variables, and role policy. Never switch to root keys or store AWS keys in GitHub. |
| Change-set review fails | Stop. Read the verifier diagnostic; do not execute or edit the ARN. Re-prepare only after identifying the mismatch and re-reviewing the new changes. |
| Frontend uses localhost | Production builds require the API URL, `VITE_AUTH_MODE=cognito`, Cognito issuer, and client ID; deployment builds them from stack outputs. Do not bypass the production build guard. |

## F. Cleanup and evidence

**No project AWS resources are currently confirmed deployed.** The artifact bucket, OIDC roles/provider, CloudFormation role, permissions boundary, and any stack-created services require separate setup/approval.

After a temporary demo, inventory the exact stack outputs/resources and costs first. The workflow enables termination protection; disabling it is a separate, reviewed destructive action. The template retains DynamoDB, Cognito, analytics S3, and frontend S3 resources on stack deletion/replacement; retained resources need a separate explicit cleanup plan. The artifact bucket is outside the stack. Do not empty/delete any bucket or table without verifying exact ownership, stack references, data retention and approval. Do not modify `smartslot-datalake`.

CloudFront, Lambda, API Gateway, Cognito, DynamoDB, S3 storage/requests, and CloudWatch logs may incur charges; enabling DynamoDB PITR adds backup-storage costs. Check current Mumbai pricing and billing before and after the demo. Retain genuine GitHub run links, change-set summaries, invocation run IDs, S3 report paths, CloudWatch log streams, and screenshots; never manufacture console evidence or include credentials.
