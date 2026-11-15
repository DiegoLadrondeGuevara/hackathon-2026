output "cloud_run_url" {
  value = try(google_cloud_run_v2_service.api[0].uri, null)
}
output "build_source_bucket" {
  value = google_storage_bucket.build_source.name
}
output "builder_service_account" {
  value = google_service_account.build.email
}
