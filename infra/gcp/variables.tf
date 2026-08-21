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

variable "enable_management_host" {
  description = "Create the persistent host for the cloud management cluster."
  type        = bool
  default     = false
}

variable "management_host_name" {
  description = "Name of the dedicated management-cluster host."
  type        = string
  default     = "osk8s-management"
}

variable "management_host_address" {
  description = "Reserved internal IPv4 address of the management host."
  type        = string
  default     = "10.20.0.30"
}

variable "management_host_machine_type" {
  description = "Machine type for the management-cluster host."
  type        = string
  default     = "e2-standard-2"
}

variable "management_host_disk_size_gb" {
  description = "Boot and container storage disk size for the management host."
  type        = number
  default     = 60
}
