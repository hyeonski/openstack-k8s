variable "project_id" {
  description = "Existing GCP project containing the OpenStack lab."
  type        = string
  default     = "openstack-k8s"
}

variable "region" {
  description = "GCP region for the lab."
  type        = string
  default     = "asia-northeast3"
}

variable "zone" {
  description = "GCP zone for controller and compute hosts."
  type        = string
  default     = "asia-northeast3-a"
}

variable "source_image" {
  description = "Exact Ubuntu image used by the imported hosts."
  type        = string
  default     = "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-minimal-2404-noble-amd64-v20260817"
}

variable "max_run_duration_seconds" {
  description = "Cost-control runtime limit retained on every GCE host."
  type        = number
  default     = 36000
}

variable "enable_openstack_floating_ip_route" {
  description = "Create the route only after controller external networking is deployed."
  type        = bool
  default     = false
}

variable "openstack_external_cidr" {
  description = "Logical Neutron external/Floating IP range behind the controller."
  type        = string
  default     = "172.24.4.0/24"
}
