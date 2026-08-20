#!/usr/bin/env python3

"""Build the controller-local Ansible inventory for an environment profile."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def parse_compute(value: str) -> tuple[str, str, str]:
    try:
        inventory_name, ip_address, node_hostname = value.split(",", 2)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "compute must be INVENTORY_NAME,IP_ADDRESS,NODE_HOSTNAME"
        ) from error
    if not all((inventory_name, ip_address, node_hostname)):
        raise argparse.ArgumentTypeError("compute fields must not be empty")
    return inventory_name, ip_address, node_hostname


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    parser.add_argument("--controller-ip", required=True)
    parser.add_argument("--controller-hostname", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--compute", action="append", type=parse_compute, required=True)
    args = parser.parse_args()

    key = f"/home/{args.user}/.ssh/openstack_k8s"
    all_members = [
        "controller "
        f"ansible_host={args.controller_ip} "
        "ansible_connection=local "
        "ansible_python_interpreter=/usr/bin/python3 "
        f"node_hostname={args.controller_hostname}"
    ]
    compute_names: list[str] = []
    for inventory_name, ip_address, node_hostname in args.compute:
        compute_names.append(inventory_name)
        all_members.append(
            f"{inventory_name} ansible_host={ip_address} "
            f"ansible_user={args.user} ansible_become=true "
            f"ansible_private_key_file={key} "
            "ansible_python_interpreter=/usr/bin/python3 "
            f"node_hostname={node_hostname}"
        )

    content = "\n".join(
        [
            "[all]",
            *all_members,
            "",
            "[control]",
            "controller",
            "",
            "[network]",
            "controller",
            "",
            "[compute]",
            *compute_names,
            "",
            "[monitoring]",
            "controller",
            "",
            "[storage]",
            "",
        ]
    )

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(content, encoding="utf-8")
    os.chmod(args.destination, 0o600)


if __name__ == "__main__":
    main()
