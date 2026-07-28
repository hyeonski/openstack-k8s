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
    parser.add_argument("--compute-ip", required=True)
    parser.add_argument("--user", default="ubuntu")
    args = parser.parse_args()

    content = args.sample.read_text(encoding="utf-8")
    managed_groups = {
        "control": [
            "controller ansible_connection=local "
            "ansible_python_interpreter=/usr/bin/python3"
        ],
        "network": ["controller"],
        "compute": [
            f"compute01 ansible_host={args.compute_ip} ansible_user={args.user} "
            "ansible_become=true "
            f"ansible_private_key_file=/home/{args.user}/.ssh/openstack_k8s "
            "ansible_python_interpreter=/usr/bin/python3"
        ],
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
