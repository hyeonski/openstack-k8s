#!/usr/bin/env python3
"""Index existing autoscaler evidence by UTC interval and immutable resource ID."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


def read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
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


def merge_observation(index, key, row, timestamp):
    if not key:
        return
    previous = index.get(key, {})
    merged = {**previous, **{k: v for k, v in row.items() if v is not None and v != ""}}
    times = [t for t in (previous.get("first_seen_utc"), previous.get("last_seen_utc"), timestamp) if t]
    node_time = row.get("node_first_seen_utc") or timestamp
    if row.get("node") and node_time:
        merged["node_first_seen_utc"] = min(previous.get("node_first_seen_utc") or node_time, node_time)
    if times:
        merged.update(first_seen_utc=min(times), last_seen_utc=max(times))
    index[key] = merged


def build(path: Path) -> dict:
    ownership = read(path / "ownership.json")
    # Baseline probes can exist before the load Deployment ownership file.
    owner = ownership.get("run") or read(path.parent / "run.json").get("owner_id")
    result = read(path / "result.json")
    stages, all_resources, all_pods = [], {}, {}
    for stage in sorted(p for p in path.iterdir() if p.is_dir() and (p / "started.json").exists()):
        started = read(stage / "started.json")
        passed = read(stage / "passed.json")
        timed_out = read(stage / "timeout.json")
        snapshots = sorted(stage.glob("[0-9][0-9][0-9][0-9]/snapshot.json"))
        resources, pods, errors, last = {}, {}, {}, {}
        for snapshot in snapshots:
            last = read(snapshot)
            timestamp = last.get("time")
            errors.update(last.get("errors", {}))
            for row in identities(last):
                merge_observation(resources, row.get("machine_uid"), row, timestamp)
            for row in owned_pods(last, owner):
                merge_observation(pods, row.get("pod_uid"), row, timestamp)
        for row in passed.get("identities", []):
            row = normalize(row)
            merge_observation(resources, row.get("machine_uid"), row, passed.get("time"))
        for removed in passed.get("removed", []):
            row = {**normalize(removed), "retired_at_utc": passed.get("time")}
            merge_observation(resources, row.get("machine_uid"), row, None)
        for key, row in resources.items():
            merge_observation(all_resources, key, row, row.get("first_seen_utc"))
            merge_observation(all_resources, key, row, row.get("last_seen_utc"))
        for key, row in pods.items():
            merge_observation(all_pods, key, row, row.get("first_seen_utc"))
            merge_observation(all_pods, key, row, row.get("last_seen_utc"))
        stages.append({"name": stage.name, "start_utc": started.get("time"),
                       "end_utc": passed.get("time") or timed_out.get("time") or last.get("time"),
                       "target_workers": started.get("target_workers"),
                       "state": "passed" if passed else "timeout" if timed_out else "incomplete",
                       "snapshot_count": len(snapshots), "query_errors": sorted(errors),
                       "resources": list(resources.values()), "pods": list(pods.values())})
    # Include short-lived probes, which may be created and deleted between polls.
    for source in sorted(path.rglob("*.json")):
        if source.name in ("observability-manifest.json", "requested-deployment.json"):
            continue
        obj = read(source)
        if obj.get("kind") != "Pod":
            continue
        timestamp = obj.get("metadata", {}).get("creationTimestamp")
        for row in owned_pods({"pods": {"items": [obj]}}, owner):
            merge_observation(all_pods, row.get("pod_uid"), row, timestamp)
    return {"schema_version": 2, "run_id": path.name, "workload_owner_id": owner,
            "start_utc": stages[0]["start_utc"] if stages else None,
            "end_utc": result.get("time"), "state": result.get("state", "incomplete"),
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
    fd, temporary = tempfile.mkstemp(prefix=".manifest-", dir=path)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(build(path), stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)  # atomic, and fails if another writer published
        directory = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(temporary)
    print(destination)


if __name__ == "__main__":
    main()
