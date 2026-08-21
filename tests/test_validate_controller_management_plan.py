#!/usr/bin/env python3

import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "validate-controller-management-plan.py"
FIREWALL = "google_compute_firewall.iap_management_api[0]"
CONTROLLER = 'google_compute_instance.hosts["controller"]'


class ValidateControllerManagementPlanTests(unittest.TestCase):
    def run_validator(self, changes: list[tuple[str, list[str]]]):
        document = {
            "resource_changes": [
                {"address": address, "change": {"actions": actions}}
                for address, actions in changes
            ]
        }
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(document),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_only_firewall_and_controller_updates(self):
        result = self.run_validator(
            [
                (FIREWALL, ["update"]),
                (CONTROLLER, ["update"]),
                ("google_compute_address.management[0]", ["no-op"]),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_firewall_only_recovery(self):
        result = self.run_validator([(FIREWALL, ["update"])])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_fresh_firewall_create(self):
        result = self.run_validator(
            [(FIREWALL, ["create"]), (CONTROLLER, ["update"])]
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_management_host_replacement(self):
        result = self.run_validator(
            [
                (FIREWALL, ["update"]),
                (CONTROLLER, ["update"]),
                ("google_compute_instance.management[0]", ["delete", "create"]),
            ]
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
