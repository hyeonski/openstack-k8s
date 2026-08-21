#!/usr/bin/env python3

import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "validate-image-builder-plan.py"
BUILDER = "google_compute_instance.image_builder[0]"


class ValidateImageBuilderPlanTests(unittest.TestCase):
    def run_validator(self, action: str, changes: list[tuple[str, list[str]]]):
        document = {
            "resource_changes": [
                {"address": address, "change": {"actions": actions}}
                for address, actions in changes
            ]
        }
        return subprocess.run(
            [sys.executable, str(SCRIPT), action],
            input=json.dumps(document),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_isolated_create(self):
        result = self.run_validator(
            "create",
            [("google_compute_network.management", ["no-op"]), (BUILDER, ["create"])],
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_isolated_delete(self):
        result = self.run_validator("delete", [(BUILDER, ["delete"])])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_builder_replacement(self):
        result = self.run_validator("create", [(BUILDER, ["delete", "create"])])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe image-builder plan", result.stderr)

    def test_rejects_unrelated_change(self):
        result = self.run_validator(
            "create",
            [
                (BUILDER, ["create"]),
                ("google_compute_instance.hosts[\"controller\"]", ["update"]),
            ],
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe image-builder plan", result.stderr)


if __name__ == "__main__":
    unittest.main()
