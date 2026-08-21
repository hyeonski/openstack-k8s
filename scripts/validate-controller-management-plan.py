#!/usr/bin/env python3

"""Allow only the controller tag and IAP API firewall migration."""

from __future__ import annotations

import json
import sys


MIGRATION = {
    ("google_compute_firewall.iap_management_api[0]", ("update",)),
    ('google_compute_instance.hosts["controller"]', ("update",)),
}

FRESH_CREATE = {
    ("google_compute_firewall.iap_management_api[0]", ("create",)),
    ('google_compute_instance.hosts["controller"]', ("update",)),
}

RECOVERY_PLANS = (
    {("google_compute_firewall.iap_management_api[0]", ("create",))},
    {("google_compute_firewall.iap_management_api[0]", ("update",))},
    {('google_compute_instance.hosts["controller"]', ("update",))},
)

EXPECTED_PLANS = (MIGRATION, FRESH_CREATE, *RECOVERY_PLANS)


def main() -> None:
    document = json.load(sys.stdin)
    changes: set[tuple[str, tuple[str, ...]]] = set()
    for item in document.get("resource_changes", []):
        actions = tuple(item.get("change", {}).get("actions", []))
        if actions in {("no-op",), ("read",)}:
            continue
        changes.add((item.get("address", ""), actions))

    if changes not in EXPECTED_PLANS:
        raise SystemExit(
            f"unsafe controller-management plan: expected one of "
            f"{[sorted(plan) for plan in EXPECTED_PLANS]!r}, "
            f"found {sorted(changes)!r}"
        )
    print("Validated isolated controller-management network plan")


if __name__ == "__main__":
    main()
