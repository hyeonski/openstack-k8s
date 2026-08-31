variable "project_id" {
  description = "Existing billed GCP project that will contain the OpenStack lab."
  type        = string
  default     = "openstack-k8s"
}

variable "environment_name" {
  description = "Stable environment label used to scope lifecycle operations."
  type        = string
  default     = "cloud-gcp-amd64"
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
  description = "Exact Ubuntu image used by provisioned or adopted hosts."
  type        = string
  default     = "https://www.googleapis.com/compute/v1/projects/ubuntu-os-cloud/global/images/ubuntu-minimal-2404-noble-amd64-v20260817"
}

variable "max_run_duration_seconds" {
  description = "Cost-control runtime limit retained on every GCE host."
  type        = number
  default     = 36000
}

variable "target_ssh_user" {
  description = "Linux account that receives the project-scoped deployment SSH key."
  type        = string
  default     = ""
}

variable "deployment_ssh_public_key" {
  description = "Public half of the controller-to-compute deployment SSH key."
  type        = string
  default     = ""
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

variable "enable_image_builder" {
  description = "Create the disposable nested-KVM Kubernetes image builder."
  type        = bool
  default     = false
}

variable "image_builder_name" {
  description = "Name of the disposable Kubernetes image builder."
  type        = string
  default     = "osk8s-image-builder"
}

variable "image_builder_machine_type" {
  description = "Nested-KVM capable machine type for the disposable image builder."
  type        = string
  default     = "n2-standard-4"
}

variable "image_builder_disk_size_gb" {
  description = "Boot and workspace disk size for the disposable image builder."
  type        = number
  default     = 80
}
