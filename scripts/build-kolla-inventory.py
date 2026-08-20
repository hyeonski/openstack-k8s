#!/usr/bin/env python3

"""Build a valid Kolla multinode inventory from its installed sample."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def replace_group(content: str, group: str, members: list[str]) -> str:
    header = f"[{group}]"
    pattern = re.compile(rf"(?ms)^{re.escape(header)}\n.*?(?=^\[|\Z)")
    replacement = header + "\n" + "\n".join(members) + "\n\n"
    if not pattern.search(content):
        raise ValueError(f"sample inventory has no [{group}] group")
    return pattern.sub(replacement, content, count=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--compute",
        action="append",
        default=[],
        metavar="NAME=IP",
        help="repeat for each compute inventory member",
    )
    parser.add_argument("--compute-ip", help="legacy single compute01 address")
    parser.add_argument("--user", default="ubuntu")
    args = parser.parse_args()

    content = args.sample.read_text(encoding="utf-8")
    compute_specs = list(args.compute)
    if args.compute_ip:
        compute_specs.append(f"compute01={args.compute_ip}")
    if not compute_specs:
        parser.error("at least one --compute NAME=IP is required")

    compute_members = []
    for spec in compute_specs:
        try:
            name, ip_address = spec.split("=", 1)
        except ValueError:
            parser.error(f"invalid --compute value: {spec!r}")
        if not name or not ip_address:
            parser.error(f"invalid --compute value: {spec!r}")
        compute_members.append(
            f"{name} ansible_host={ip_address} ansible_user={args.user} "
            "ansible_become=true "
            f"ansible_private_key_file=/home/{args.user}/.ssh/openstack_k8s "
            "ansible_python_interpreter=/usr/bin/python3"
        )

    managed_groups = {
        "control": [
            "controller ansible_connection=local "
            "ansible_python_interpreter=/usr/bin/python3"
        ],
        "network": ["controller"],
        "compute": compute_members,
        "monitoring": ["controller"],
        "storage": [],
        "deployment": ["controller ansible_connection=local"],
    }
    for group, members in managed_groups.items():
        content = replace_group(content, group, members)

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(content, encoding="utf-8")
    args.destination.chmod(0o600)


if __name__ == "__main__":
    main()
