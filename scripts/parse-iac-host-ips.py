#!/usr/bin/env python3

"""Read requested host IPs from an OpenTofu host_internal_ips output."""

from __future__ import annotations

import ipaddress
import json
import sys


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: parse-iac-host-ips.py KEY [KEY ...]")
    document = json.load(sys.stdin)
    if not isinstance(document, dict):
        raise SystemExit("host_internal_ips output must be an object")

    for key in sys.argv[1:]:
        value = document.get(key)
        if not isinstance(value, str):
            raise SystemExit(f"missing OpenTofu host IP output: {key}")
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise SystemExit(f"invalid OpenTofu host IP output for {key}: {value}") from error
        if address.version != 4:
            raise SystemExit(f"IPv4 is required for {key}: {value}")
        print(address)


if __name__ == "__main__":
    main()
