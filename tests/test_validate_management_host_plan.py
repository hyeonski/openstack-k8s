#!/usr/bin/env python3

import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "validate-management-host-plan.py"
ADDRESS = 'google_compute_address.internal["management"]'
INSTANCE = "google_compute_instance.management[0]"
FIREWALL = "google_compute_firewall.iap_management_api[0]"


class ValidateManagementHostPlanTests(unittest.TestCase):
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

    def test_accepts_address_and_instance_create(self):
        result = self.run_validator(
            [
                ("google_compute_network.management", ["no-op"]),
                (INSTANCE, ["create"]),
                (ADDRESS, ["create"]),
                (FIREWALL, ["create"]),
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_firewall_and_tag_upgrade(self):
        result = self.run_validator(
            [(INSTANCE, ["update"]), (FIREWALL, ["create"])]
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_firewall_only_recovery(self):
        result = self.run_validator([(FIREWALL, ["create"])])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_existing_host_update(self):
        result = self.run_validator(
            [
                (INSTANCE, ["create"]),
                (ADDRESS, ["create"]),
                (FIREWALL, ["create"]),
                ('google_compute_instance.hosts["controller"]', ["update"]),
            ]
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
