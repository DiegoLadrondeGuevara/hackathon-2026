mock_provider "google" {}

variables {
  project_id = "gen-lang-client-0984590124"
  image_uri  = "us-central1-docker.pkg.dev/gen-lang-client-0984590124/rtc-gcp/analisis:test"
}

run "regional_private_runtime" {
  command = plan
  assert {
    condition = (
      google_bigquery_dataset.analytics.location == "us-central1" &&
      google_artifact_registry_repository.docker.location == "us-central1" &&
      google_cloud_run_v2_service.api[0].location == "us-central1"
    )
    error_message = "Keep all data processing in the agreed region."
  }
  assert {
    condition     = google_bigquery_table.events.deletion_protection && google_bigquery_table.guard.deletion_protection
    error_message = "Event history and serialization guard must be protected."
  }
  assert {
    condition = (
      google_cloud_run_v2_service.api[0].template[0].scaling[0].min_instance_count == 0 &&
      google_cloud_run_v2_service.api[0].template[0].containers[0].resources[0].cpu_idle
    )
    error_message = "Without metrics, use request-based CPU and scale to zero."
  }
}

run "metrics_background_cpu" {
  command = plan
  variables {
    enable_metrics        = true
    grafana_otlp_endpoint = "https://grafana.example/otlp"
    grafana_instance_id   = "123"
  }
  assert {
    condition     = !google_cloud_run_v2_service.api[0].template[0].containers[0].resources[0].cpu_idle
    error_message = "Background export needs CPU after the HTTP response."
  }
}

run "reject_missing_metrics_config" {
  command = plan
  variables {
    enable_metrics = true
  }
  expect_failures = [google_cloud_run_v2_service.api]
}

run "reject_unconfigured_service" {
  command = plan
  variables {
    image_uri = ""
  }
  expect_failures = [google_cloud_run_v2_service.api]
}

run "bootstrap_has_no_service" {
  command = plan
  variables {
    deploy_service = false
  }
  assert {
    condition     = length(google_cloud_run_v2_service.api) == 0
    error_message = "Bootstrap must not deploy a service before secrets and the image exist."
  }
}
