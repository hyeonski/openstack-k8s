#!/usr/bin/env python3
"""Index existing autoscaler evidence by UTC interval and immutable resource ID."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def identities(snapshot: dict) -> list[dict]:
    machines = snapshot.get("machines", {}).get("items", [])
    nodes = {n.get("metadata", {}).get("name"): n.get("metadata", {}).get("uid")
             for n in snapshot.get("nodes", {}).get("items", [])}
    osmachines = {n.get("metadata", {}).get("name"): n.get("metadata", {}).get("uid")
                  for n in snapshot.get("osmachines", {}).get("items", [])}
    result = []
    for machine in machines:
        meta, spec, status = (machine.get(part, {}) for part in ("metadata", "spec", "status"))
        node = status.get("nodeRef", {}).get("name")
        osmachine = spec.get("infrastructureRef", {}).get("name")
        server = spec.get("providerID") or status.get("providerID") or ""
        result.append({"machine_uid": meta.get("uid"), "machine": meta.get("name"),
                       "osmachine_uid": osmachines.get(osmachine), "osmachine": osmachine,
                       "node_uid": nodes.get(node), "node": node,
                       "nova_server_id": server.removeprefix("openstack:///"),
                       "control_plane": "cluster.x-k8s.io/control-plane" in meta.get("labels", {})})
    return result


def normalize(row: dict) -> dict:
    return {"machine_uid": row.get("machine_uid"), "machine": row.get("machine"),
            "osmachine_uid": row.get("osmachine_uid"), "osmachine": row.get("osmachine"),
            "node_uid": row.get("node_uid"), "node": row.get("node"),
            "nova_server_id": row.get("nova_server_id") or row.get("server"),
            "control_plane": bool(row.get("control_plane"))}


def owned_pods(snapshot: dict, run_owner: str) -> list[dict]:
    if not run_owner:
        return []
    rows = []
    for pod in snapshot.get("pods", {}).get("items", []):
        meta = pod.get("metadata", {})
        if meta.get("labels", {}).get("test.openstack-k8s.io/run") != run_owner:
            continue
        rows.append({"pod_uid": meta.get("uid"), "pod": meta.get("name"),
                     "namespace": meta.get("namespace"),
                     "node": pod.get("spec", {}).get("nodeName"),
                     "phase": pod.get("status", {}).get("phase")})
    return rows


def build(path: Path) -> dict:
    ownership = read(path / "ownership.json")
    result = read(path / "result.json")
    stages = []
    all_resources: dict[str, dict] = {}
    all_pods: dict[str, dict] = {}
    for stage in sorted(p for p in path.iterdir() if p.is_dir() and (p / "started.json").exists()):
        started = read(stage / "started.json")
        passed = read(stage / "passed.json")
        timed_out = read(stage / "timeout.json")
        snapshots = sorted(stage.glob("[0-9][0-9][0-9][0-9]/snapshot.json"))
        last = read(snapshots[-1]) if snapshots else {}
        current = [normalize(row) for row in (passed.get("identities") or identities(last))]
        pods = owned_pods(last, ownership.get("run", ""))
        for pod in pods:
            if pod["pod_uid"]:
                all_pods[pod["pod_uid"]] = pod
        for row in current:
            key = row.get("machine_uid") or row.get("machine")
            if key:
                all_resources[key] = row
        for removed in passed.get("removed", []):
            row = normalize(removed)
            key = row.get("machine_uid") or row.get("machine")
            if key:
                all_resources[key] = row
        errors = {}
        for snapshot in snapshots:
            errors.update(read(snapshot).get("errors", {}))
        stages.append({"name": stage.name, "start_utc": started.get("time"),
                       "end_utc": passed.get("time") or timed_out.get("time") or last.get("time"),
                       "target_workers": started.get("target_workers"),
                       "state": "passed" if passed else "timeout" if timed_out else "incomplete",
                       "snapshot_count": len(snapshots),
                       "query_errors": sorted(errors), "resources": current, "pods": pods})
    return {"schema_version": 1, "run_id": path.name,
            "workload_owner_id": ownership.get("run"),
            "start_utc": stages[0]["start_utc"] if stages else None,
            "end_utc": result.get("time"),
            "state": result.get("state", "incomplete"),
            "stages": stages,
            "resources": sorted(all_resources.values(), key=lambda x: x.get("machine_uid") or ""),
            "pods": sorted(all_pods.values(), key=lambda x: x.get("pod_uid") or ""),
            "missing_data": sorted({key for stage in stages for key in stage["query_errors"]})}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    path = args.run_dir.resolve()
    if not path.is_dir() or not path.name.startswith("autoscaler-cycle-"):
        parser.error("expected an autoscaler-cycle evidence directory")
    destination = path / "observability-manifest.json"
    if destination.exists():
        parser.error("manifest already exists; existing evidence is immutable")
    destination.write_text(json.dumps(build(path), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    destination.chmod(0o600)
    print(destination)


if __name__ == "__main__":
    main()
