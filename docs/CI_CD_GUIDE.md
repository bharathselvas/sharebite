# CI/CD Guide

## Test-only CI

`.github/workflows/ci.yml` runs for pushes, pull requests, or manual dispatch. It does not configure AWS credentials or deploy. Jobs:

- Python dependency install, compile check, backend/ETL tests, and synthetic ETL report generation.
- Frontend npm install, TypeScript lint, and Vite production build.
- A lightweight heuristic check for common AWS access-key IDs/private-key blocks (not a comprehensive secret scanner), `cfn-lint`, workflow YAML parsing, and `sam validate --lint`.

The CI job installs SAM CLI to validate the template on GitHub runners. Local availability differs: this environment does not have SAM CLI. A local `cfn-lint` pass must not be reported as `sam validate` evidence.

## Separate manually gated deployment

`.github/workflows/deploy-aws.yml` is separate and has no push/PR trigger. It requires `workflow_dispatch`, both `cost_reviewed` and `deploy_approved` inputs to be true, branch `main`, and the protected `aws-demo` environment. It uses GitHub OIDC temporary credentials, not long-lived keys.

Before any future use, repository maintainers must independently configure environment reviewers and branch restrictions; configure an OIDC trust policy limited to the exact repository and environment; scope the AWS role to the reviewed stack/artifact and `iam:PassRole`; set only reviewed role/region variables; and verify current costs/credit coverage. This task did not configure any of those settings.

`prepare-change-set` may use/create a SAM artifact bucket and prepares a non-executed CloudFormation change set. `execute-reviewed-change-set` accepts a change-set ARN and executes it after the same approval gates. Review and verify workflow logic, the exact change set, and GitHub environment protection before dispatch. Workflow gates do not replace separate explicit user approval or protect against an overly broad role. Do not run deployment as part of local verification.

See [the existing detailed CI/CD guide](./CICD_GUIDE.md) for the future OIDC trust-policy example and cleanup notes. No GitHub workflow was run in this task.
