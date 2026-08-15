from __future__ import annotations

import importlib.util
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "select-autoscaler-cpu.py"
SPEC = importlib.util.spec_from_file_location("select_autoscaler_cpu", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SelectAutoscalerCpuTests(unittest.TestCase):
    def test_selects_request_that_fits_once(self) -> None:
        node = {"status": {"allocatable": {"cpu": "2"}}}
        pods = {
            "items": [
                {
                    "spec": {
                        "containers": [
                            {"resources": {"requests": {"cpu": "100m"}}}
                        ]
                    },
                    "status": {"phase": "Running"},
                },
                {
                    "spec": {
                        "containers": [
                            {"resources": {"requests": {"cpu": "900m"}}}
                        ]
                    },
                    "status": {"phase": "Succeeded"},
                },
            ]
        }

        allocatable, requested, available, selected = module.select(node, pods)

        self.assertEqual((allocatable, requested, available), (2000, 100, 1900))
        self.assertLessEqual(selected, available)
        self.assertGreater(selected * 2, available)

    def test_accounts_for_init_container_maximum(self) -> None:
        pod = {
            "spec": {
                "containers": [{"resources": {"requests": {"cpu": "100m"}}}],
                "initContainers": [
                    {"resources": {"requests": {"cpu": "250m"}}}
                ],
                "overhead": {"cpu": "10m"},
            }
        }
        self.assertEqual(module.pod_cpu_request(pod), 260)


if __name__ == "__main__":
    unittest.main()
