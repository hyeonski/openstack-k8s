from __future__ import annotations

import pathlib
import re
import unittest


PROJECT_ROOT = pathlib.Path(__file__).parents[1]
MAKEFILE = PROJECT_ROOT / "Makefile"


class ScriptRoutingTests(unittest.TestCase):
    def test_make_script_references_exist(self) -> None:
        text = MAKEFILE.read_text()
        referenced = set(re.findall(r"scripts/[A-Za-z0-9_./-]+\.(?:sh|py)", text))

        self.assertTrue(referenced)
        for relative in referenced:
            self.assertTrue((PROJECT_ROOT / relative).is_file(), relative)

    def test_all_make_targets_are_phony(self) -> None:
        text = MAKEFILE.read_text()
        logical_text = text.replace("\\\n", " ")
        phony_match = re.search(r"(?m)^\.PHONY:\s*(.+)$", logical_text)

        self.assertIsNotNone(phony_match)
        phony = set(phony_match.group(1).split())
        targets = set(re.findall(r"(?m)^([A-Za-z0-9_.-]+):", text))
        targets.discard(".PHONY")
        self.assertEqual(set(), targets - phony)

    def test_public_targets_route_to_consolidated_commands(self) -> None:
        text = MAKEFILE.read_text()

        expected = {
            "bootstrap-preflight": "scripts/gcp-preflight.sh bootstrap",
            "gcp-wait-ssh": "scripts/gcp-hosts.sh wait-ssh",
            "gcp-controller-management-prepare": (
                "scripts/gcp-iac.sh controller-management"
            ),
            "host-prepare": "scripts/run-controller.sh prepare-hosts",
            "openstack-verification-cleanup": "scripts/openstack-verify.sh cleanup",
        }
        for target, command in expected.items():
            target_body = re.search(
                rf"(?ms)^{re.escape(target)}:.*?(?=^[A-Za-z0-9_.-]+:|\Z)",
                text,
            )
            self.assertIsNotNone(target_body, target)
            self.assertIn(command, target_body.group(0), target)

    def test_removed_wrappers_are_absent(self) -> None:
        removed = {
            "gcp-bootstrap-preflight.sh",
            "gcp-controller-management-iac.sh",
            "gcp-wait-ssh.sh",
            "openstack-verification-cleanup.sh",
            "run-host-prepare.sh",
        }

        existing = {path.name for path in (PROJECT_ROOT / "scripts").glob("*.sh")}
        self.assertTrue(removed.isdisjoint(existing))

    def test_local_script_calls_do_not_depend_on_working_directory(self) -> None:
        relative_call = re.compile(
            r"(?m)(?:^\s*|[|;&]\s*)scripts/[A-Za-z0-9_.-]+"
        )

        for script in (PROJECT_ROOT / "scripts").glob("*.sh"):
            self.assertIsNone(relative_call.search(script.read_text()), script.name)


if __name__ == "__main__":
    unittest.main()
