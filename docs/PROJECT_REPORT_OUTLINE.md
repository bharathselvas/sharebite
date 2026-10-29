# College Project Report Outline

## Title

Cloud-Native Smart Food Redistribution and Analytics Platform Using Serverless Computing, ETL, and CI/CD

## Suggested chapters

1. **Abstract** — problem example, cloud-computing learning objectives, local-first implementation, and clearly qualified results.
2. **Introduction** — surplus-food redistribution as a demonstration domain; scope is cloud technology, not operational food safety or real-world NGO service.
3. **Objectives and requirements** — React UI, validated API, persistent local data, duplicate-claim prevention, Pandas ETL, CI, IaC, cost/security constraints.
4. **Architecture and service selection** — include the diagrams in `ARCHITECTURE.md`; explain S3, Cognito JWT authorization, API Gateway, Lambda, DynamoDB query indexes, IAM, CloudWatch, and SAM roles. Note unselected SNS/EventBridge/Glue/Athena.
5. **Design and implementation** — API routes and state transitions, local mock identity limitation, frontend workflows, input validation, SQLite vs. DynamoDB, ETL input/outputs.
6. **ETL and analytics** — extract/transform/load stages, timezone normalization, duplicate handling, rejected rows, metrics, and optional Parquet. Explain how Glue/Athena could replace/extend local processing without claiming they ran.
7. **Security, privacy, and cost control** — synthetic data only, mock authentication limitations, least privilege, OIDC, account-plan eligibility unknown until reviewed, service pricing dimensions and cleanup gates.
8. **CI/CD and infrastructure as code** — automated test workflow, disabled-by-default separate deployment workflow, SAM template, parameterization, OIDC, and human-reviewed change sets.
9. **Testing and results** — add actual local pytest/build results and, only if independently approved and performed, actual AWS Console evidence. Label simulation and deployment separately; include date and region only when verified.
10. **Limitations and future work** — real authentication/authorization, scale-aware query/index design, reliable export ingestion, frontend hosting, operational policies, monitoring alerts, and cost-aware service evaluation.
11. **Conclusion** — summarize demonstrated cloud concepts and zero-cost baseline.
12. **References and appendix** — official current AWS pricing/service docs, test commands, API examples, sample synthetic ETL inputs/reports, and cleanup checklist.

## Suggested demonstration sequence

1. Start local API and React frontend; create, claim, and confirm a synthetic donation.
2. Attempt an invalid request and duplicate claim; show validation and conflict handling.
3. Run Pandas ETL; inspect clean output, rejected-record report, and summary metrics.
4. Show passing tests and local frontend build, then actual GitHub CI history if available.
5. Present the optional architecture/template and explain that no AWS resources are deployed unless separately approved.

Do not fabricate AWS screenshots, logs, resource IDs, costs, deployment results, or institutional findings.
