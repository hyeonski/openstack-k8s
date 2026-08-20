output "host_internal_ips" {
  value = { for key, host in local.hosts : key => host.address }
}

output "kolla_internal_vip" {
  value = try(google_compute_address.internal["kolla_vip"].address, null)
}

output "automatic_stop_after_seconds" {
  value = var.max_run_duration_seconds
}

output "floating_ip_route_enabled" {
  value = var.enable_openstack_floating_ip_route
}
