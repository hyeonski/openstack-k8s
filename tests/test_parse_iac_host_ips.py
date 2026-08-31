from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "parse-iac-host-ips.py"


class ParseIacHostIpsTests(unittest.TestCase):
    def run_parser(self, document: object, *keys: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *keys],
            input=json.dumps(document),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_returns_requested_addresses_in_order(self) -> None:
        result = self.run_parser(
            {
                "compute02": "10.20.0.22",
                "controller": "10.20.0.10",
                "compute01": "10.20.0.21",
            },
            "controller",
            "compute01",
            "compute02",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["10.20.0.10", "10.20.0.21", "10.20.0.22"],
        )

    def test_rejects_missing_key(self) -> None:
        result = self.run_parser({"controller": "10.20.0.10"}, "compute01")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing OpenTofu host IP output", result.stderr)

    def test_rejects_invalid_address(self) -> None:
        result = self.run_parser({"controller": "not-an-ip"}, "controller")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid OpenTofu host IP output", result.stderr)


if __name__ == "__main__":
    unittest.main()
