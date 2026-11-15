variable "project_id" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Invalid GCP project ID."
  }
}
variable "region" {
  type    = string
  default = "us-central1"
}
variable "dataset_id" {
  type    = string
  default = "redtelecorp"
  validation {
    condition     = can(regex("^[A-Za-z_][A-Za-z0-9_]{0,63}$", var.dataset_id))
    error_message = "Invalid dataset ID."
  }
}
variable "bq_location" {
  type    = string
  default = "us-central1"
}
variable "deploy_service" {
  type        = bool
  default     = true
  description = "False only for the initial bootstrap; never for an existing service."
}
variable "image_uri" {
  type    = string
  default = ""
}
variable "enable_gemini" {
  type    = bool
  default = false
}
variable "gemini_model" {
  type    = string
  default = "gemini-3.5-flash-lite"
}
variable "api_key_version" {
  type    = string
  default = "1"
}
variable "gemini_key_version" {
  type    = string
  default = "1"
}
variable "protect_data" {
  type        = bool
  default     = true
  description = "Explicitly disable before an approved teardown; protects tables and service."
}
variable "enable_metrics" {
  type    = bool
  default = false
}
variable "grafana_otlp_endpoint" {
  type    = string
  default = ""
}
variable "grafana_instance_id" {
  type    = string
  default = ""
}
variable "grafana_token_version" {
  type    = string
  default = "1"
}
