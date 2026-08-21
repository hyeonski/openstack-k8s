locals {
  network_name    = "osk8s-mgmt"
  subnetwork_name = "osk8s-seoul"

  hosts = {
    controller = {
      name                       = "osk8s-controller"
      machine_type               = "e2-standard-4"
      address                    = "10.20.0.10"
      disk_size_gb               = 80
      nested_kvm                 = false
      alias_ip_range             = "10.20.0.250/32"
      nic_type                   = "VIRTIO_NET"
      key_revocation_action_type = "NONE"
      metadata = {
        enable-osconfig = "TRUE"
      }
      labels = {
        env                   = "cloud-gcp-amd64"
        goog-ops-agent-policy = "v2-template-1-7-0"
        role                  = "controller"
      }
    }
    compute01 = {
      name                       = "osk8s-compute01"
      machine_type               = "n2-standard-4"
      address                    = "10.20.0.21"
      disk_size_gb               = 120
      nested_kvm                 = true
      alias_ip_range             = null
      nic_type                   = null
      key_revocation_action_type = null
      metadata                   = {}
      labels = {
        env  = "cloud-gcp-amd64"
        role = "compute"
      }
    }
    compute02 = {
      name                       = "osk8s-compute02"
      machine_type               = "n2-standard-4"
      address                    = "10.20.0.22"
      disk_size_gb               = 120
      nested_kvm                 = true
      alias_ip_range             = null
      nic_type                   = null
      key_revocation_action_type = null
      metadata                   = {}
      labels = {
        env  = "cloud-gcp-amd64"
        role = "compute"
      }
    }
  }

  internal_addresses = merge(
    { for key, host in local.hosts : key => host.address },
    { kolla_vip = "10.20.0.250" }
  )
}

resource "google_compute_network" "management" {
  name                                      = local.network_name
  description                               = "OpenStack Kolla controller and compute management network"
  auto_create_subnetworks                   = false
  mtu                                       = 1500
  routing_mode                              = "REGIONAL"
  enable_ula_internal_ipv6                  = false
  network_firewall_policy_enforcement_order = "AFTER_CLASSIC_FIREWALL"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_compute_subnetwork" "seoul" {
  name                     = local.subnetwork_name
  description              = "OpenStack Kolla hosts in Seoul"
  region                   = var.region
  network                  = google_compute_network.management.id
  ip_cidr_range            = "10.20.0.0/24"
  private_ip_google_access = true
  stack_type               = "IPV4_ONLY"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_compute_firewall" "iap_ssh" {
  name      = "osk8s-allow-iap-ssh"
  network   = google_compute_network.management.name
  direction = "INGRESS"
  priority  = 1000

  source_ranges = ["35.235.240.0/20"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "iap_management_api" {
  count = 1

  name      = "osk8s-allow-iap-management-api"
  network   = google_compute_network.management.name
  direction = "INGRESS"
  priority  = 1000

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["osk8s-controller-management"]

  allow {
    protocol = "tcp"
    ports    = ["16443"]
  }
}

resource "google_compute_firewall" "internal" {
  name      = "osk8s-allow-internal"
  network   = google_compute_network.management.name
  direction = "INGRESS"
  priority  = 1000

  source_ranges = ["10.20.0.0/24"]

  allow {
    protocol = "all"
  }
}

resource "google_compute_address" "internal" {
  for_each = local.internal_addresses

  name         = each.key == "kolla_vip" ? "osk8s-kolla-vip" : "osk8s-${each.key}-ip"
  region       = var.region
  subnetwork   = google_compute_subnetwork.seoul.id
  address_type = "INTERNAL"
  address      = each.value
  purpose      = "GCE_ENDPOINT"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_compute_instance" "hosts" {
  for_each = local.hosts

  name                       = each.value.name
  zone                       = var.zone
  machine_type               = each.value.machine_type
  can_ip_forward             = true
  deletion_protection        = false
  enable_display             = false
  key_revocation_action_type = each.value.key_revocation_action_type
  resource_policies          = []
  tags = each.key == "controller" ? [
    "osk8s-controller-management",
    "osk8s-node",
  ] : ["osk8s-node"]
  labels   = each.value.labels
  metadata = each.value.metadata

  boot_disk {
    auto_delete = true
    device_name = each.value.name
    mode        = "READ_WRITE"

    initialize_params {
      image             = var.source_image
      size              = each.value.disk_size_gb
      type              = "pd-balanced"
      resource_policies = each.key == "controller" ? [google_compute_resource_policy.daily_snapshots.self_link] : []
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.seoul.id
    network_ip = google_compute_address.internal[each.key].address
    stack_type = "IPV4_ONLY"
    nic_type   = each.value.nic_type

    dynamic "alias_ip_range" {
      for_each = each.value.alias_ip_range == null ? [] : [each.value.alias_ip_range]
      content {
        ip_cidr_range = alias_ip_range.value
      }
    }

    access_config {
      network_tier = "PREMIUM"
    }
  }

  dynamic "advanced_machine_features" {
    for_each = each.value.nested_kvm ? [true] : []
    content {
      enable_nested_virtualization = true
    }
  }

  dynamic "confidential_instance_config" {
    for_each = each.key == "controller" ? [true] : []
    content {
      enable_confidential_compute = false
    }
  }

  dynamic "reservation_affinity" {
    for_each = each.key == "controller" ? [true] : []
    content {
      type = "ANY_RESERVATION"
    }
  }

  scheduling {
    automatic_restart           = true
    on_host_maintenance         = "MIGRATE"
    preemptible                 = false
    provisioning_model          = "STANDARD"
    instance_termination_action = "STOP"

    max_run_duration {
      seconds = var.max_run_duration_seconds
      nanos   = 0
    }
  }

  shielded_instance_config {
    enable_secure_boot          = false
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  lifecycle {
    prevent_destroy = true
    # Provider import exposes existing labels through effective_labels but
    # leaves labels empty. GCP remains the source of truth during adoption.
    ignore_changes = [labels]
  }
}

resource "google_compute_resource_policy" "daily_snapshots" {
  name   = "default-schedule-1"
  region = var.region

  snapshot_schedule_policy {
    schedule {
      daily_schedule {
        days_in_cycle = 1
        start_time    = "05:00"
      }
    }

    retention_policy {
      max_retention_days    = 14
      on_source_disk_delete = "KEEP_AUTO_SNAPSHOTS"
    }

    snapshot_properties {
      guest_flush = false
    }
  }
}

resource "google_compute_disk_resource_policy_attachment" "controller_snapshots" {
  name = google_compute_resource_policy.daily_snapshots.name
  disk = google_compute_instance.hosts["controller"].name
  zone = var.zone
}

resource "google_compute_route" "openstack_floating_ips" {
  count = var.enable_openstack_floating_ip_route ? 1 : 0

  name                   = "osk8s-openstack-floating-ips"
  network                = google_compute_network.management.name
  dest_range             = var.openstack_external_cidr
  priority               = 1000
  next_hop_instance      = google_compute_instance.hosts["controller"].self_link
  next_hop_instance_zone = var.zone
}

resource "google_compute_instance" "image_builder" {
  count = var.enable_image_builder ? 1 : 0

  name                = var.image_builder_name
  zone                = var.zone
  machine_type        = var.image_builder_machine_type
  can_ip_forward      = false
  deletion_protection = false
  enable_display      = false
  tags                = ["osk8s-node"]
  labels = {
    env  = "cloud-gcp-amd64"
    role = "image-builder"
  }

  boot_disk {
    auto_delete = true
    device_name = var.image_builder_name
    mode        = "READ_WRITE"

    initialize_params {
      image = var.source_image
      size  = var.image_builder_disk_size_gb
      type  = "pd-balanced"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.seoul.id
    stack_type = "IPV4_ONLY"

    access_config {
      network_tier = "PREMIUM"
    }
  }

  advanced_machine_features {
    enable_nested_virtualization = true
  }

  scheduling {
    automatic_restart           = true
    on_host_maintenance         = "MIGRATE"
    preemptible                 = false
    provisioning_model          = "STANDARD"
    instance_termination_action = "STOP"

    max_run_duration {
      seconds = var.max_run_duration_seconds
      nanos   = 0
    }
  }

  shielded_instance_config {
    enable_secure_boot          = false
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
}
