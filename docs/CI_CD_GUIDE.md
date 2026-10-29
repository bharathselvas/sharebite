# CI/CD Guide

## Test-only CI

`.github/workflows/ci.yml` runs for pushes, pull requests, or manual dispatch. It does not configure AWS credentials or deploy. Its jobs cover Python backend/ETL/change-set-verifier tests, synthetic ETL output, frontend lint/build, credential-marker checks, CloudFormation lint, workflow YAML parsing, and AWS SAM validation.

## Separate manually gated deployment

`.github/workflows/deploy-aws.yml` has no push/PR trigger. It manually prepares an explicitly named, non-executed CloudFormation change set, then requires a separate dispatch, read-only identity review, and protected `aws-demo` environment approval before execution. It uses GitHub OIDC, a dedicated review role, a separate deployment role, and a CloudFormation execution role; it does not use static AWS keys or a human Identity Center permission set.

Configure the GitHub variables, OIDC role trust, artifact bucket, and protected environments as described in the [detailed CI/CD guide](./CICD_GUIDE.md). Those resources/settings are not created by this repository change. No AWS workflow was dispatched.
