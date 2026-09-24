#!/usr/bin/env python3
"""Read-only, bounded Nova inventory. Emits whitelisted JSONL, never credentials."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

UTC = dt.timezone.utc
TIME = dt.datetime.now(UTC).isoformat()
ENV = os.environ.get("OSK8S_ENV", "cloud-gcp-amd64")
CLI = "/opt/kolla-venv/bin/openstack"


def emit(kind: str, **fields: object) -> None:
    print(json.dumps({"time": TIME, "environment": ENV, "source": "openstack",
                      "kind": kind, **fields}, separators=(",", ":")), flush=True)


def query(*args: str) -> list[dict]:
    result = subprocess.run([CLI, "--os-cloud", "kolla-admin", *args, "-f", "json"],
                            capture_output=True, text=True, timeout=20, check=True)
    parsed = json.loads(result.stdout)
    return parsed if isinstance(parsed, list) else [parsed]


def pick(row: dict, *names: str) -> object:
    normalized = {key.lower().replace(" ", "_"): value for key, value in row.items()}
    for name in names:
        if name.lower() in normalized:
            return normalized[name.lower()]
    return None


def collect() -> int:
    failed = False
    for kind, args, fields in (
        ("compute_service", ("compute", "service", "list"),
         {"host": ("host",), "binary": ("binary",), "state": ("state",), "status": ("status",)}),
        ("hypervisor", ("hypervisor", "list", "--long"),
         {"host": ("hypervisor_hostname",), "state": ("state",), "status": ("status",),
          "vcpus": ("vcpus",), "vcpus_used": ("vcpus_used",),
          "memory_mb": ("memory_mb",), "memory_mb_used": ("memory_mb_used",),
          "local_gb": ("local_gb",), "local_gb_used": ("local_gb_used",)}),
        ("nova_server", ("server", "list", "--all-projects", "--long"),
         {"id": ("id",), "name": ("name",), "status": ("status",),
          "host": ("host", "os-ext-srv-attr:host"), "created": ("created_at",),
          "updated": ("updated_at",), "flavor": ("flavor",)}),
    ):
        try:
            rows = query(*args)
            for row in rows:
                selected = {out: pick(row, *aliases) for out, aliases in fields.items()}
                if kind == "nova_server" and selected["id"]:
                    try:
                        detail = query("server", "show", str(selected["id"]))[0]
                        selected["host"] = pick(detail, "os-ext-srv-attr:host", "host")
                        selected["vm_state"] = pick(detail, "os-ext-sts:vm_state")
                        selected["task_state"] = pick(detail, "os-ext-sts:task_state")
                        selected["power_state"] = pick(detail, "os-ext-sts:power_state")
                    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                            json.JSONDecodeError, OSError) as exc:
                        selected["detail_error"] = type(exc).__name__
                        failed = True
                emit(kind, **selected)
            emit("query_status", query=kind, ok=True, count=len(rows))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                json.JSONDecodeError, OSError) as exc:
            # Command stderr can contain credentials or tenant details; only the type leaves this process.
            emit("query_status", query=kind, ok=False, error=type(exc).__name__)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(collect())
