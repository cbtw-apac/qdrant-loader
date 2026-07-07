# AWS Deployment Placeholders

This folder reserves infrastructure-as-code entry points for AWS deployment paths:

- `cdk/` — AWS CDK app for ECS/EKS, queues, object storage, and managed databases.
- `terraform/` — Terraform modules for platform-managed deployments.
- `step-functions/` — Step Functions workflow definitions for serverless ingestion orchestration.

The local Docker Compose path should be validated before implementing cloud infrastructure.
