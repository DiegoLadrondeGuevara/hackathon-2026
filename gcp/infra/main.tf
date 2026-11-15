locals {
  apis = toset([
    "run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com",
    "bigquery.googleapis.com", "secretmanager.googleapis.com", "iam.googleapis.com",
    "logging.googleapis.com", "cloudresourcemanager.googleapis.com", "storage.googleapis.com"
  ])
}
resource "google_project_service" "apis" {
  for_each           = local.apis
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
resource "google_service_account" "runtime" {
  account_id   = "rtc-gcp-runtime"
  display_name = "Red TeleCorp API runtime"
  depends_on   = [google_project_service.apis]
}
resource "google_service_account" "build" {
  account_id   = "rtc-gcp-builder"
  display_name = "Red TeleCorp container builder"
  depends_on   = [google_project_service.apis]
}
resource "google_bigquery_dataset" "analytics" {
  dataset_id                 = var.dataset_id
  location                   = var.bq_location
  delete_contents_on_destroy = false
  depends_on                 = [google_project_service.apis]
}
resource "google_bigquery_table" "events" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "incident_events"
  schema              = file("${path.module}/schema.json")
  deletion_protection = var.protect_data
  time_partitioning {
    type  = "DAY"
    field = "occurred_at"
  }
  clustering = ["event_id", "zone_id"]
  # Global event_id deduplication must also find an ID with a changed timestamp.
  require_partition_filter = false
}
resource "google_bigquery_table" "guard" {
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  table_id            = "ingest_guard"
  deletion_protection = var.protect_data
  schema = jsonencode([
    { name = "id", type = "STRING", mode = "REQUIRED" },
    { name = "generation", type = "INTEGER", mode = "REQUIRED" }
  ])
}
resource "google_bigquery_job" "initialize_guard" {
  project  = var.project_id
  location = var.bq_location
  job_id   = "rtc_initialize_guard_${google_bigquery_table.guard.table_id}_${substr(sha256("${google_bigquery_table.guard.id}:${google_bigquery_table.guard.creation_time}"), 0, 12)}"
  query {
    query          = <<-SQL
      MERGE `${var.project_id}.${var.dataset_id}.ingest_guard` T
      USING (SELECT 'singleton' AS id) S ON T.id = S.id
      WHEN NOT MATCHED THEN INSERT (id, generation) VALUES (S.id, 0)
    SQL
    use_legacy_sql = false
  }
}
resource "google_project_iam_custom_role" "runtime_data" {
  project     = var.project_id
  role_id     = "rtcBigQueryData"
  title       = "Red TeleCorp event data access"
  permissions = ["bigquery.tables.get", "bigquery.tables.getData", "bigquery.tables.updateData"]
  depends_on  = [google_project_service.apis]
}
resource "google_bigquery_dataset_iam_member" "data" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = google_project_iam_custom_role.runtime_data.name
  member     = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_project_iam_member" "query_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = "rtc-gcp"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}
resource "google_artifact_registry_repository_iam_member" "build_writer" {
  location   = google_artifact_registry_repository.docker.location
  repository = google_artifact_registry_repository.docker.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.build.email}"
}
resource "google_project_iam_member" "build_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.build.email}"
}
resource "google_storage_bucket" "build_source" {
  name                        = "${var.project_id}-rtc-build-src"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = !var.protect_data
  lifecycle_rule {
    condition {
      age = 7
    }
    action {
      type = "Delete"
    }
  }
  depends_on = [google_project_service.apis]
}
resource "google_storage_bucket_iam_member" "build_source" {
  bucket = google_storage_bucket.build_source.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.build.email}"
}
resource "google_secret_manager_secret" "api_key" {
  secret_id = "rtc-gcp-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret" "gemini_key" {
  secret_id = "rtc-gcp-gemini-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_iam_member" "api" {
  secret_id = google_secret_manager_secret.api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_secret_manager_secret_iam_member" "gemini" {
  secret_id = google_secret_manager_secret.gemini_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
resource "google_cloud_run_v2_service" "api" {
  count               = var.deploy_service ? 1 : 0
  name                = "red-telecorp-analisis"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = var.protect_data
  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "25s"
    max_instance_request_concurrency = 8
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
    containers {
      image = var.image_uri
      ports {
        container_port = 8080
      }
      resources {
        limits = { cpu = "1", memory = "512Mi" }
        # Background OTLP export needs CPU outside request processing. Still scales to zero.
        cpu_idle = !var.enable_metrics
      }
      dynamic "env" {
        for_each = {
          GOOGLE_CLOUD_PROJECT = var.project_id
          BQ_DATASET           = var.dataset_id
          BQ_TABLE             = "incident_events"
          BQ_LOCATION          = var.bq_location
          BQ_MAX_BYTES_BILLED  = "1000000000"
          GEMINI_MODEL         = var.gemini_model
        }
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.api_key.secret_id
            version = var.api_key_version
          }
        }
      }
      dynamic "env" {
        for_each = var.enable_metrics ? {
          GRAFANA_OTLP_ENDPOINT = var.grafana_otlp_endpoint
          GRAFANA_INSTANCE_ID   = var.grafana_instance_id
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.enable_metrics ? [1] : []
        content {
          name = "GRAFANA_TOKEN"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.grafana_token.secret_id
              version = var.grafana_token_version
            }
          }
        }
      }
      dynamic "env" {
        for_each = var.enable_gemini ? [1] : []
        content {
          name = "GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.gemini_key.secret_id
              version = var.gemini_key_version
            }
          }
        }
      }
    }
  }
  depends_on = [google_bigquery_job.initialize_guard, google_bigquery_table.events,
    google_bigquery_dataset_iam_member.data, google_project_iam_member.query_jobs,
    google_secret_manager_secret_iam_member.api, google_secret_manager_secret_iam_member.gemini,
  google_secret_manager_secret_iam_member.grafana]
  lifecycle {
    precondition {
      condition = !var.enable_metrics || (
        startswith(var.grafana_otlp_endpoint, "https://") && length(var.grafana_instance_id) > 0
      )
      error_message = "Metrics require an HTTPS OTLP endpoint and Grafana instance ID."
    }
    precondition {
      condition     = length(var.image_uri) > 25
      error_message = "Set image_uri to a built image. Bootstrap alone requires deploy_service=false."
    }
  }
}
resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.deploy_service ? 1 : 0
  name     = google_cloud_run_v2_service.api[0].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
resource "google_secret_manager_secret" "grafana_token" {
  secret_id = "rtc-gcp-grafana-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}
resource "google_secret_manager_secret_iam_member" "grafana" {
  count     = var.enable_metrics ? 1 : 0
  secret_id = google_secret_manager_secret.grafana_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}
