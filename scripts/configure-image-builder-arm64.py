#!/usr/bin/env python3

"""Adapt Image Builder's supported MaaS ARM64 QEMU builder for OpenStack.

The upstream ARM64 builder already contains the correct aarch64 QEMU, UEFI,
containerd and crictl paths.  MaaS-only archive conversion and fstab removal
are intentionally removed so the retained artifact is a normal QCOW2 image.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def configure(document: dict) -> dict:
    document["post-processors"] = [
        item
        for item in document.get("post-processors", [])
        if item.get("name") != "convert-to-maas"
    ]

    configured_provisioners = []
    for provisioner in document.get("provisioners", []):
        if provisioner.get("inline") == ["sudo rm -f /etc/fstab"]:
            continue
        vars_inline = provisioner.get("vars_inline")
        if isinstance(vars_inline, dict):
            vars_inline["ARCH"] = "arm64"
            # Upstream's OpenStack Goss profile assumes the amd64-only
            # linux-cloud-tools-virtual package.  The maas-arm64 profile has
            # the same QEMU/cloud-init checks with the correct ARM64 package
            # set; Nova-specific behavior is verified after Glance upload.
            vars_inline["PROVIDER"] = "maas-arm64"
        configured_provisioners.append(provisioner)
    document["provisioners"] = configured_provisioners

    variables = document.setdefault("variables", {})
    variables["runc_url"] = (
        "https://github.com/opencontainers/runc/releases/download/"
        "v{{user `runc_version`}}/runc.arm64"
    )
    return document


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packer_json", type=Path)
    args = parser.parse_args()

    document = json.loads(args.packer_json.read_text(encoding="utf-8"))
    configured = configure(document)
    args.packer_json.write_text(
        json.dumps(configured, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
