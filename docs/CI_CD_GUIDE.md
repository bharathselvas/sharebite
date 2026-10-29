# CI/CD Guide

## Test-only CI

`.github/workflows/ci.yml` runs for pushes, pull requests, or manual dispatch. It does not configure AWS credentials or deploy. Its jobs cover Python backend/ETL/change-set-verifier tests, synthetic ETL output, frontend lint/build, credential-marker checks, CloudFormation lint, workflow YAML parsing, and AWS SAM validation.

## Separate manually gated deployment

`.github/workflows/deploy-aws.yml` has no push/PR trigger. It manually prepares an explicitly named, non-executed CloudFormation change set, then requires a separate dispatch, read-only identity review, and protected `aws-demo` environment approval before execution. It uses GitHub OIDC, a dedicated review role, a separate deployment role, and a CloudFormation execution role; it does not use static AWS keys or a human Identity Center permission set.

The GitHub OIDC provider, scoped roles, runtime boundary, private artifact bucket, and deployment environment variables are configured. The test-only CI run [40868228770](https://github.com/bharathselvas/sharebite/actions/runs/40868228770) passed. No AWS deployment workflow has been dispatched; the independent `aws-demo` environment reviewer is still missing.
