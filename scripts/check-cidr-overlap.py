#!/usr/bin/env python3
"""Check candidate IPv4 networks against addresses configured on macOS."""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess


INET_RE = re.compile(
    r"\binet\s+(?P<ip>\d+\.\d+\.\d+\.\d+)\s+netmask\s+(?P<mask>0x[0-9a-fA-F]+)"
)


def mask_from_hex(value: str) -> str:
    number = int(value, 16)
    return ".".join(str((number >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def configured_networks() -> list[ipaddress.IPv4Network]:
    output = subprocess.run(
        ["ifconfig"], check=True, capture_output=True, text=True
    ).stdout
    result: list[ipaddress.IPv4Network] = []
    for match in INET_RE.finditer(output):
        ip = match.group("ip")
        if ip.startswith("127."):
            continue
        mask = mask_from_hex(match.group("mask"))
        result.append(ipaddress.ip_network(f"{ip}/{mask}", strict=False))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("cidr", nargs="+")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Configured CIDR that is expected and should not count as a collision",
    )
    args = parser.parse_args()

    candidates = [ipaddress.ip_network(value, strict=False) for value in args.cidr]
    allowed = {ipaddress.ip_network(value, strict=False) for value in args.allow}
    found = configured_networks()
    collisions: list[tuple[ipaddress.IPv4Network, ipaddress.IPv4Network]] = []

    for candidate in candidates:
        for existing in found:
            if candidate.overlaps(existing) and existing not in allowed:
                collisions.append((candidate, existing))

    if collisions:
        for candidate, existing in collisions:
            print(f"collision: requested {candidate} overlaps configured {existing}")
        raise SystemExit(1)

    for candidate in candidates:
        print(f"available: {candidate}")


if __name__ == "__main__":
    main()

