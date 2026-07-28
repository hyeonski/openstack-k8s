#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER = PROJECT_ROOT / "scripts" / "build-kolla-inventory.py"

SAMPLE = """[control]
control01
control02

[network]
network01

[compute]
compute01

[monitoring]
monitoring01

[storage]
storage01

[deployment]
localhost ansible_connection=local

[nova:children]
control
compute
"""


class BuildKollaInventoryTest(unittest.TestCase):
    def test_replaces_primary_groups_and_preserves_children(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sample = root / "multinode"
            destination = root / "generated"
            sample.write_text(SAMPLE, encoding="utf-8")

            subprocess.run(
                [
                    str(BUILDER),
                    str(sample),
                    str(destination),
                    "--compute-ip",
                    "192.0.2.22",
                    "--user",
                    "ubuntu",
                ],
                check=True,
            )
            content = destination.read_text(encoding="utf-8")

        self.assertIn("controller ansible_connection=local", content)
        self.assertIn("compute01 ansible_host=192.0.2.22", content)
        self.assertIn("ansible_private_key_file=/home/ubuntu/.ssh/openstack_k8s", content)
        self.assertIn("[nova:children]\ncontrol\ncompute", content)
        self.assertNotIn("control01", content)
        self.assertNotIn("storage01", content)


if __name__ == "__main__":
    unittest.main()
