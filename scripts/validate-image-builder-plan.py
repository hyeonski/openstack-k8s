#!/usr/bin/env python3

"""Refuse an image-builder plan that changes anything except one builder."""

from __future__ import annotations

import json
import sys


EXPECTED_ADDRESS = "google_compute_instance.image_builder[0]"


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"create", "delete"}:
        raise SystemExit("usage: validate-image-builder-plan.py create|delete")

    document = json.load(sys.stdin)
    changes: list[tuple[str, list[str]]] = []
    for item in document.get("resource_changes", []):
        actions = item.get("change", {}).get("actions", [])
        if actions in (["no-op"], ["read"]):
            continue
        changes.append((item.get("address", ""), actions))

    expected = [(EXPECTED_ADDRESS, [sys.argv[1]])]
    if changes != expected:
        raise SystemExit(
            f"unsafe image-builder plan: expected {expected!r}, found {changes!r}"
        )
    print(f"Validated isolated image-builder {sys.argv[1]} plan")


if __name__ == "__main__":
    main()
