#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "configure-image-builder-arm64.py"
SPEC = importlib.util.spec_from_file_location("configure_image_builder_arm64", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfigureImageBuilderArm64Test(unittest.TestCase):
    def test_removes_maas_only_steps_and_sets_arm64_validation(self) -> None:
        document = {
            "post-processors": [
                {"name": "custom-post-processor"},
                {"name": "convert-to-maas"},
            ],
            "provisioners": [
                {"inline": ["sudo rm -f /etc/fstab"], "type": "shell"},
                {
                    "type": "goss",
                    "vars_inline": {"ARCH": "amd64", "PROVIDER": "openstack"},
                },
            ],
            "variables": {"runc_url": "runc.amd64"},
        }

        configured = MODULE.configure(document)

        self.assertEqual(
            [item["name"] for item in configured["post-processors"]],
            ["custom-post-processor"],
        )
        self.assertEqual(len(configured["provisioners"]), 1)
        self.assertEqual(
            configured["provisioners"][0]["vars_inline"],
            {"ARCH": "arm64", "PROVIDER": "maas-arm64"},
        )
        self.assertTrue(configured["variables"]["runc_url"].endswith("runc.arm64"))


if __name__ == "__main__":
    unittest.main()
