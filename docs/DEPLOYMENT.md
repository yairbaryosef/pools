# GCP Deployment Specification

## 1. Target platform

Deploy the Python ASGI application to Google Cloud Run in the Firebase project's region. Cloud Run is preferred over a self-managed VM for stateless autoscaling, managed TLS, revision rollback, and identity-based access to Firestore.

## 2. Required GCP resources

- Dedicated runtime service account with least-privilege Firestore access.
- Firestore database in Native mode.
- Artifact Registry repository for container images.
- Cloud Run service with explicit ingress, timeout, concurrency, CPU, memory, and minimum-instance settings.
- Secret Manager entries for the Google OAuth client secret and application session secret.
- Workload identity for CI deployment; no service-account JSON in the repository or image.
- Cloud Logging and Error Reporting with sensitive fields redacted.

## 3. Deployment flow

1. Build a reproducible container from locked Python dependencies.
2. Run lint, type, contract, security, and dependency gates.
3. Push an immutable image digest to Artifact Registry.
4. Deploy a Cloud Run revision with the runtime service account and Secret Manager bindings.
5. Configure `ATLAS_FIREBASE_PROJECT_ID`, Google OAuth redirect URI, frontend origin, and non-secret runtime settings.
6. Run health, readiness, authentication, group, pool lifecycle, and result-visibility smoke checks.
7. Shift traffic only after the revision is healthy; retain the previous revision for rollback.

## 4. Service-account JSON policy

The supplied local file `pools-42d9a-firebase-adminsdk-fbsvc-3bf1b04ccc.json` is a development credential only and is ignored by Git. It must not be copied into the image, uploaded to Cloud Run, placed in an environment variable, or referenced in production. Production uses the Cloud Run service account through ADC.

## 5. Operational gates

Deployment is blocked if the image contains credential files, the runtime service account has project-owner/editor permissions, OAuth redirect URIs are not exact, Firestore is unreachable, secrets are missing, or smoke tests show pre-close results or cross-group access.
