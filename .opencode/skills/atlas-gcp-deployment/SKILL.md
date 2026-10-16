---
name: atlas-gcp-deployment
description: Defines secure deployment and operations for the Atlas pools server on Google Cloud.
compatibility: Google Cloud Run, Firestore, Artifact Registry, Secret Manager
metadata:
  domain: deployment
  project: atlas
---

# Atlas GCP Deployment Skill

## Use when

Use for container packaging, Cloud Run deployment, Firestore runtime identity, Artifact Registry, Secret Manager, CI/CD, observability, rollback, and production smoke checks.

## Operating method

Read `docs/DEPLOYMENT.md`, `docs/DATABASE.md`, `docs/SECURITY.md`, and current handoff packets. Prefer Cloud Run with a dedicated service account and ADC. Build immutable images, deploy by digest, bind secrets through Secret Manager, verify the revision, then shift traffic.

## Credential rules

The local Firebase Admin SDK JSON is a secret and must remain gitignored. Never read it into prompts, commit it, copy it into an image, upload it to Cloud Run, or place its contents in environment variables. Production must use the Cloud Run service account through ADC. If local credential setup is required, reference the file path only.

## Boundary rules

The deployment agent owns infrastructure manifests, container/deploy configuration, IAM recommendations, and deployment runbooks. It does not change application behavior, Firestore domain schema, security policy, or tests. SecurityAgent approves IAM and secret decisions.

## Deterministic conventions

Use explicit GCP project/region/service names, immutable image digests, least-privilege IAM, pinned build inputs, revision health checks, documented rollback, and redacted deployment evidence. Never use project-owner/editor roles for runtime.

## Edge cases

Handle missing APIs, wrong Firebase project, unavailable Firestore, missing secrets, invalid OAuth redirect URIs, credential files accidentally included in the build context, Cloud Run startup failures, revision rollback, and quota/region mismatch.
