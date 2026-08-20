from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "build-ansible-inventory.py"


class BuildAnsibleInventoryTest(unittest.TestCase):
    def test_builds_two_compute_controller_local_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "hosts.ini"
            subprocess.run(
                [
                    str(BUILDER),
                    str(destination),
                    "--controller-ip",
                    "10.20.0.10",
                    "--controller-hostname",
                    "osk8s-controller",
                    "--user",
                    "operator",
                    "--compute",
                    "compute01,10.20.0.21,osk8s-compute01",
                    "--compute",
                    "compute02,10.20.0.22,osk8s-compute02",
                ],
                check=True,
            )
            content = destination.read_text(encoding="utf-8")

        self.assertIn("controller ansible_host=10.20.0.10", content)
        self.assertIn("node_hostname=osk8s-controller", content)
        self.assertIn("compute01 ansible_host=10.20.0.21", content)
        self.assertIn("compute02 ansible_host=10.20.0.22", content)
        self.assertIn("ansible_private_key_file=/home/operator/.ssh/openstack_k8s", content)
        self.assertIn("[compute]\ncompute01\ncompute02", content)


if __name__ == "__main__":
    unittest.main()
