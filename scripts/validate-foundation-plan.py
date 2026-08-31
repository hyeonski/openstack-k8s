#!/usr/bin/env python3

"""Allow only safe creates for the persistent greenfield GCP foundation."""

from __future__ import annotations

import json
import sys


EXPECTED_ADDRESSES = {
    'google_compute_address.internal["compute01"]',
    'google_compute_address.internal["compute02"]',
    'google_compute_address.internal["controller"]',
    'google_compute_address.internal["kolla_vip"]',
    "google_compute_disk_resource_policy_attachment.controller_snapshots",
    "google_compute_firewall.iap_management_api[0]",
    "google_compute_firewall.iap_ssh",
    "google_compute_firewall.internal",
    'google_compute_instance.hosts["compute01"]',
    'google_compute_instance.hosts["compute02"]',
    'google_compute_instance.hosts["controller"]',
    "google_compute_network.management",
    "google_compute_resource_policy.daily_snapshots",
    "google_compute_subnetwork.seoul",
}


def main() -> None:
    document = json.load(sys.stdin)
    changes: list[tuple[str, tuple[str, ...]]] = []
    for item in document.get("resource_changes", []):
        actions = tuple(item.get("change", {}).get("actions", []))
        if actions in {("no-op",), ("read",)}:
            continue
        changes.append((item.get("address", ""), actions))

    unsafe = [
        (address, actions)
        for address, actions in changes
        if address not in EXPECTED_ADDRESSES or actions != ("create",)
    ]
    if unsafe:
        raise SystemExit(
            f"unsafe foundation plan: only creates from "
            f"{sorted(EXPECTED_ADDRESSES)!r} are allowed; found {unsafe!r}"
        )
    print(f"Validated greenfield foundation plan with {len(changes)} create action(s)")


if __name__ == "__main__":
    main()
