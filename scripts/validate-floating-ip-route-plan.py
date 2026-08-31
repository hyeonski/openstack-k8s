#!/usr/bin/env python3

"""Allow only creation of the post-host OpenStack Floating IP route."""

from __future__ import annotations

import json
import sys


ROUTE = "google_compute_route.openstack_floating_ips[0]"


def main() -> None:
    document = json.load(sys.stdin)
    changes: list[tuple[str, tuple[str, ...]]] = []
    for item in document.get("resource_changes", []):
        actions = tuple(item.get("change", {}).get("actions", []))
        if actions in {("no-op",), ("read",)}:
            continue
        changes.append((item.get("address", ""), actions))

    expected = [] if not changes else [(ROUTE, ("create",))]
    if changes != expected:
        raise SystemExit(
            f"unsafe Floating IP route plan: expected {expected!r}, "
            f"found {changes!r}"
        )
    print("Validated isolated Floating IP route plan")


if __name__ == "__main__":
    main()
