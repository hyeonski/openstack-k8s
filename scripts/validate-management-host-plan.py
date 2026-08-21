#!/usr/bin/env python3

"""Refuse a management-host plan that changes unrelated GCP resources."""

from __future__ import annotations

import json
import sys


FRESH_CREATE = {
    ("google_compute_address.internal[\"management\"]", ("create",)),
    ("google_compute_firewall.iap_management_api[0]", ("create",)),
    ("google_compute_instance.management[0]", ("create",)),
}

UPGRADE_CREATE = {
    ("google_compute_firewall.iap_management_api[0]", ("create",)),
    ("google_compute_instance.management[0]", ("update",)),
}

RECOVERY_CREATE = {
    ("google_compute_firewall.iap_management_api[0]", ("create",)),
}

EXPECTED_PLANS = (FRESH_CREATE, UPGRADE_CREATE, RECOVERY_CREATE)


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
            f"unsafe management-host plan: expected one of "
            f"{[sorted(plan) for plan in EXPECTED_PLANS]!r}, "
            f"found {sorted(changes)!r}"
        )
    print("Validated isolated management-host create plan")


if __name__ == "__main__":
    main()
