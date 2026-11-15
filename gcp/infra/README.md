# GCP Terraform

See [../README.md](../README.md) for configuration, local validation, approved deployment and cleanup.
Google provider is pinned and locked. Secret versions are never managed by Terraform.
Runtime has query-job permission and dataset-scoped get/getData/updateData; build-source access is bucket-scoped.
`ingest_guard` initialization must finish before Cloud Run receives events.
Do not apply `deploy_service=false` to an existing deployment. Preserve the private state and deployment settings.
