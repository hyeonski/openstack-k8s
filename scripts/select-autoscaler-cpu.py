#!/usr/bin/env python3
"""Select a CPU request that fits once, but not twice, on one worker."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, ROUND_CEILING
from pathlib import Path


def cpu_millicores(value: str | int | float | None) -> int:
    if value in (None, ""):
        return 0
    text = str(value)
    suffixes = {"n": Decimal("0.000001"), "u": Decimal("0.001"), "m": Decimal(1)}
    if text[-1:] in suffixes:
        result = Decimal(text[:-1]) * suffixes[text[-1]]
    else:
        result = Decimal(text) * 1000
    return int(result.to_integral_value(rounding=ROUND_CEILING))


def pod_cpu_request(pod: dict) -> int:
    spec = pod.get("spec", {})
    regular = sum(
        cpu_millicores(item.get("resources", {}).get("requests", {}).get("cpu"))
        for item in spec.get("containers", [])
    )
    init_max = max(
        (
            cpu_millicores(item.get("resources", {}).get("requests", {}).get("cpu"))
            for item in spec.get("initContainers", [])
        ),
        default=0,
    )
    overhead = cpu_millicores(spec.get("overhead", {}).get("cpu"))
    return max(regular, init_max) + overhead


def select(node: dict, pods: dict) -> tuple[int, int, int, int]:
    allocatable = cpu_millicores(node["status"]["allocatable"]["cpu"])
    requested = sum(
        pod_cpu_request(pod)
        for pod in pods.get("items", [])
        if pod.get("status", {}).get("phase") not in {"Succeeded", "Failed"}
    )
    available = allocatable - requested
    if available < 2:
        raise ValueError(
            f"worker has too little unrequested CPU: allocatable={allocatable}m "
            f"requested={requested}m"
        )
    # Sixty percent leaves a scheduling margin while proving two replicas
    # cannot coexist on the original worker.
    selected = (available * 3 + 4) // 5
    if selected > available or selected * 2 <= available:
        raise ValueError(
            f"cannot select a valid request from available CPU: {available}m"
        )
    return allocatable, requested, available, selected


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("node", type=Path)
    parser.add_argument("pods", type=Path)
    args = parser.parse_args()
    node = json.loads(args.node.read_text(encoding="utf-8"))
    pods = json.loads(args.pods.read_text(encoding="utf-8"))
    allocatable, requested, available, selected = select(node, pods)
    print(f"allocatable_millicpu={allocatable}")
    print(f"existing_requested_millicpu={requested}")
    print(f"available_millicpu={available}")
    print(f"selected_request_millicpu={selected}")


if __name__ == "__main__":
    main()
