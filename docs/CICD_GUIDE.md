# CI/CD Demonstration Guide

## CI: tests and validation

`.github/workflows/ci.yml` runs for pushes, pull requests, or manual dispatch. It performs:

- Python dependency installation, backend and ETL pytest suites, bytecode compilation, and a synthetic ETL execution/report parse.
- Frontend npm install from the lock file, TypeScript checks, and a production Vite build.
- CloudFormation linting and AWS SAM template validation.

These are test/validation steps only and do not request AWS credentials or deploy resources. A GitHub run must complete before reporting it as a CI run; local test output is not GitHub Actions evidence.

## Optional AWS deployment: separate and gated

`.github/workflows/deploy-aws.yml` is distinct from CI, is only manually dispatched, defaults both cost review and deployment approval to false, and has a job condition requiring `main`. It requires the GitHub `aws-demo` environment and a configured OIDC role/region. Configure required environment reviewers and branch restrictions separately in repository settings; a workflow condition is not a replacement for protected-branch controls. No access key is stored in this repository.

The manual sequence is:

1. Complete account/region eligibility and current cost review, review the resource inventory and cleanup procedure, and receive the user's explicit deployment approval.
2. Configure required reviewers for the `aws-demo` environment and a repository/ref/environment-restricted GitHub OIDC trust policy and narrowly scoped AWS deployment role. Set `AWS_DEPLOY_ROLE_ARN` and `AWS_REGION` as environment variables.
3. Dispatch with `prepare-change-set`, set both approval inputs only after explicit review, and supply a valid unique `cognito_domain_prefix`. This can create/use a separate SAM artifact bucket and prepares, but does not execute, the stack change set. Inspect all resources/permissions and account/region before proceeding.
4. Only after a second, explicit approval, dispatch `execute-reviewed-change-set` with the exact reviewed change set ARN, the expected `AWS_REGION` variable, and the two approval inputs enabled. The workflow validates the ARN shape and region before requesting OIDC credentials; a malformed value fails before AWS access.
5. Verify Cognito, API authorizer, deployment outputs, and runtime in the AWS Console; do not infer success from a workflow being queued.

This workflow is intentionally not set up with a role ARN or region. The first operation can use/create a separate SAM artifact bucket. Repository maintainers must review SAM/CloudFormation permissions (including tightly scoped `iam:PassRole`) before configuring any role. Never add administrator permissions or long-lived credentials. A deployment workflow run can create resources with possible charges; do not dispatch without user approval.

An example trust-policy condition for one repository's protected GitHub environment is:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:<OWNER>/<REPOSITORY>:environment:aws-demo"
        }
      }
    }
  ]
}
```

Replace placeholders only in the AWS account configuration; do not commit account-specific role ARNs or secrets. Pair the trust with a dedicated role permission policy scoped to the exact stack/resources, artifact bucket, deployment actions, and `iam:PassRole` for the template's Lambda execution role. This trust document alone does not grant deployment permissions. An AWS administrator must verify the OIDC provider, GitHub token subject, stack/resource ARNs, and required CloudFormation service-role behavior before creating the role.

## Demonstration evidence checklist

- [ ] Actual CI run with passing tests and build
- [ ] Actual SAM template validation output
- [ ] Only if separately approved: reviewed change set and explicit execution run
- [ ] Actual CloudFormation outputs and resource status from the selected account/region
- [ ] Actual API request and corresponding Lambda/DynamoDB activity
- [ ] Actual CloudWatch log/metric evidence with no sensitive records
- [ ] Cleanup and follow-up billing review

Mark local checks, proposed infrastructure, and synthetic simulation separately from GitHub/AWS evidence.
