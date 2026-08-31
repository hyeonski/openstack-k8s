from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate-floating-ip-route-plan.py"
ROUTE = "google_compute_route.openstack_floating_ips[0]"


class ValidateFloatingIpRoutePlanTests(unittest.TestCase):
    def run_validator(
        self, changes: list[tuple[str, list[str]]]
    ) -> subprocess.CompletedProcess[str]:
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

    def test_accepts_route_create(self) -> None:
        result = self.run_validator([(ROUTE, ["create"])])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_accepts_empty_plan(self) -> None:
        result = self.run_validator([(ROUTE, ["no-op"])])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_route_delete(self) -> None:
        result = self.run_validator([(ROUTE, ["delete"])])
        self.assertNotEqual(result.returncode, 0)

    def test_rejects_unrelated_change(self) -> None:
        result = self.run_validator(
            [(ROUTE, ["create"]), ("google_compute_network.management", ["update"])]
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
