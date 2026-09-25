#!/usr/bin/env python3
"""Read-only Cloud Monitoring/Logging coverage check for a UTC run interval."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

UTC = dt.timezone.utc
METRIC_PREFIXES = {
    "system_cpu": "system_cpu", "system_memory": "system_memory",
    "system_disk": "system_disk", "system_network": "system_network",
    "k8s_node": "k8s_node", "k8s_pod": "k8s_pod",
    "k8s_container": "container_",
    "k8s_node_ready": "k8s_node_condition_ready",
    "k8s_pod_phase": "k8s_pod_phase",
    "k8s_deployment_available": "k8s_deployment_available",
}
K8S_CLUSTERS = {"management", "osk8s-workload"}
HOST_INSTANCES = {"osk8s-controller", "osk8s-compute01", "osk8s-compute02"}


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("UTC offset required")
    return parsed.astimezone(UTC)


def iso(value: dt.datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def token() -> str:
    return subprocess.check_output(["gcloud", "auth", "print-access-token"],
                                   text=True, stderr=subprocess.DEVNULL).strip()


def get_json(path: str, params: dict, access_token: str) -> dict:
    url = "https://monitoring.googleapis.com/v3/" + path + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + access_token})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def descriptors(project: str, access_token: str) -> list[str]:
    names = []
    page_token = ""
    while True:
        response = get_json(f"projects/{project}/metricDescriptors", {
            "filter": 'metric.type = starts_with("prometheus.googleapis.com/")',
            "activeOnly": "true", "pageSize": "1000", "pageToken": page_token,
        }, access_token)
        names.extend(row["type"] for row in response.get("metricDescriptors", []))
        page_token = response.get("nextPageToken", "")
        if not page_token:
            return names


def metric_coverage(project: str, start: dt.datetime, end: dt.datetime,
                    access_token: str) -> dict:
    available = descriptors(project, access_token)
    results = {}
    for category, prefix in METRIC_PREFIXES.items():
        matches = sorted(name for name in available if name.startswith("prometheus.googleapis.com/" + prefix))
        preferred = {"system_cpu": "system_cpu_time", "system_network": "system_network_io"}.get(category)
        if preferred:
            matches.sort(key=lambda name: not name.startswith("prometheus.googleapis.com/" + preferred))
        if not matches:
            results[category] = {"metric": None, "series": 0, "targets": []}
            continue
        name = matches[0]
        series = []
        for candidate in matches[:8]:
            name = candidate
            series = []
            page_token = ""
            while True:
                response = get_json(f"projects/{project}/timeSeries", {
                    "filter": f'metric.type = "{name}"', "interval.startTime": iso(start),
                    "interval.endTime": iso(end), "view": "FULL", "pageSize": "1000",
                    "pageToken": page_token,
                }, access_token)
                series.extend(response.get("timeSeries", []))
                page_token = response.get("nextPageToken", "")
                if not page_token:
                    break
            if any(row.get("points") for row in series):
                break
        targets = {}
        for row in series:
            labels = row.get("resource", {}).get("labels", {})
            key = (labels.get("cluster", "?"), labels.get("instance", "?"))
            points = {p["interval"]["endTime"] for p in row.get("points", [])}
            targets.setdefault(key, set()).update(points)
        latest = max((point for points in targets.values() for point in points), default=None)
        results[category] = {"metric": name, "series": sum(bool(row.get("points")) for row in series),
                             "latest_utc": latest,
                             "targets": [{"cluster": cluster, "instance": instance,
                                          "sample_times": sorted(points),
                                          "latest_utc": max(points, default=None)}
                                         for (cluster, instance), points in sorted(targets.items())]}
    return results


def log_coverage(project: str, region: str, start: dt.datetime, end: dt.datetime, node_targets=()) -> dict:
    base = f'log_id("osk8s-otel") AND timestamp>="{iso(start)}" AND timestamp<="{iso(end)}"'

    def read(extra: str, limit: int) -> list[dict]:
        raw = subprocess.check_output([
            "gcloud", "logging", "read", base + (" AND " + extra if extra else ""),
            "--project=" + project, "--bucket=osk8s-observability",
            "--location=" + region, "--view=_AllLogs",
            f"--limit={limit}", "--format=json"], text=True, stderr=subprocess.PIPE, timeout=90)
        return json.loads(raw)

    rows = read("", 1000)
    categories = {
        "heartbeat": 'jsonPayload.kind="collector_source_heartbeat"',
        "nova_inventory": 'jsonPayload.kind="nova_server"',
        "kolla": 'labels."log.file.name"="nova-api.log"',
        "pod_logs": 'labels."k8s.pod.uid":*',
        "events": 'labels."event.domain"="k8s"',
    }
    sources = {}
    for name, expression in categories.items():
        sample = read(expression, 1)
        sources[name] = {"present": bool(sample),
                         "latest_utc": sample[0].get("timestamp") if sample else None}
    periodic = {}
    for host in sorted(HOST_INSTANCES):
        samples = read('jsonPayload.kind="collector_source_heartbeat" AND jsonPayload.host="' + host + '"', 10000)
        periodic["heartbeat:" + host] = {"sample_times": sorted({r["timestamp"] for r in samples}),
                                        "truncated": len(samples) == 10000}
    for cluster, node in sorted(set(node_targets)):
        samples = read('textPayload:"collector_path_heartbeat" AND labels."k8s.cluster.name"=' + json.dumps(cluster) +
                       ' AND labels."service.instance.id"=' + json.dumps(node), 10000)
        periodic["node-heartbeat:" + cluster + "/" + node] = {
            "sample_times": sorted({r["timestamp"] for r in samples}), "truncated": len(samples) == 10000}
    for query in ("compute_service", "hypervisor", "nova_server"):
        samples = read('jsonPayload.kind="query_status" AND jsonPayload.query="' + query + '"', 10000)
        periodic["nova:" + query] = {"sample_times": sorted({r["timestamp"] for r in samples}),
                                    "failed_samples": sum(r.get("jsonPayload", {}).get("ok") is not True for r in samples),
                                    "truncated": len(samples) == 10000}
    detail_errors = read('jsonPayload.kind="nova_server" AND jsonPayload.detail_error:*', 1)
    return {"periodic": periodic, "nova_detail_errors": bool(detail_errors), "sampled_count": len(rows), "sample_limit": 1000,
            "latest_utc": max((row.get("timestamp", "") for row in rows), default=None),
            "sources": sources}


def gaps(times, start, end, maximum_gap):
    points = sorted({parse_time(value) for value in times if start <= parse_time(value) <= end})
    if not points:
        return {"state": "absent", "max_gap_seconds": (end - start).total_seconds(), "samples": 0}
    edges = [start, *points, end]
    largest = max((b - a).total_seconds() for a, b in zip(edges, edges[1:]))
    return {"state": "gap" if largest > maximum_gap else "complete",
            "max_gap_seconds": largest, "samples": len(points),
            "first_utc": iso(points[0]), "latest_utc": iso(points[-1])}


def assess(metrics, logs, start, end, maximum_gap=300, expected=None, host_cluster="cloud-gcp-amd64-hosts"):
    missing = []
    expected = expected or []
    bounds = {(r["cluster"], r["instance"]):
              (max(start, parse_time(r["start_utc"])) if r.get("start_utc") else start,
               min(end, parse_time(r["end_utc"])) if r.get("end_utc") else end)
              for r in expected}
    for category, row in metrics.items():
        seen = set()
        for target in row["targets"]:
            key = (target["cluster"], target["instance"])
            # A supplied inventory defines active lifetimes, including retired nodes.
            first, last = bounds.get(key, (start, end))
            if last <= first:
                continue
            seen.add(key)
            target["coverage"] = gaps(target.pop("sample_times", []), first, last, maximum_gap)
            if target["coverage"]["state"] != "complete":
                missing.append(category + ":" + "/".join(key) + ":" + target["coverage"]["state"])
        if not seen:
            missing.append(category)
        if category.startswith("system_"):
            required = {(host_cluster, h) for h in HOST_INSTANCES}
            required |= {key for key, (first, last) in bounds.items() if last > first}
            missing.extend(category + ":" + "/".join(key) + ":absent" for key in sorted(required - seen))
        else:
            missing.extend(category + ":" + cluster + ":absent" for cluster in sorted(K8S_CLUSTERS - {k[0] for k in seen}))
    for name, row in logs.get("periodic", {}).items():
        first, last = bounds.get(tuple(name.removeprefix("node-heartbeat:").split("/", 1)), (start, end)) if name.startswith("node-heartbeat:") else (start, end)
        if last <= first:
            continue
        row["coverage"] = gaps(row.pop("sample_times", []), first, last, maximum_gap)
        if row["coverage"]["state"] != "complete" or row.get("truncated") or row.get("failed_samples"):
            missing.append("logs:" + name + ":incomplete")
    required_logs = {"heartbeat:" + h for h in HOST_INSTANCES} | {"nova:" + q for q in ("compute_service", "hypervisor", "nova_server")}
    node_keys = {key for key, (first, last) in bounds.items() if last > first and key[0] in K8S_CLUSTERS}
    node_keys |= {(t["cluster"], t["instance"]) for t in metrics["system_cpu"]["targets"] if t["cluster"] in K8S_CLUSTERS}
    required_logs |= {"node-heartbeat:" + "/".join(key) for key in node_keys}
    missing.extend("logs:" + name + ":absent" for name in sorted(required_logs - set(logs.get("periodic", {}))))
    if logs.get("nova_detail_errors"):
        missing.append("logs:nova_detail_errors")
    if not logs["sampled_count"]:
        missing.append("logs")
    # Application and Event streams may be legitimately quiet; periodic sources
    # above establish collection health. Keep their presence as separate evidence.
    return sorted(set(missing))


def manifest_targets(manifest, cluster):
    return [{"cluster": cluster, "instance": row["node"],
             "start_utc": row.get("node_first_seen_utc") or row.get("first_seen_utc"),
             "end_utc": row.get("last_seen_utc") if row.get("retired_at_utc") else manifest.get("end_utc")}
            for row in manifest.get("resources", []) if row.get("node")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="openstack-k8s")
    parser.add_argument("--region", default="asia-northeast3")
    parser.add_argument("--start", type=parse_time)
    parser.add_argument("--end", type=parse_time)
    parser.add_argument("--max-gap-seconds", type=int, default=300)
    parser.add_argument("--expected-targets", type=Path, help="JSON with explicit target identities/lifetimes")
    parser.add_argument("--manifest", type=Path, help="schema v2 run manifest for retired worker lifetimes")
    parser.add_argument("--host-cluster", default="cloud-gcp-amd64-hosts")
    parser.add_argument("--workload-cluster", default="osk8s-workload")
    args = parser.parse_args()
    if args.max_gap_seconds <= 0:
        parser.error("max gap must be positive")
    expected = json.loads(args.expected_targets.read_text())["targets"] if args.expected_targets else []
    if args.manifest:
        manifest = json.loads(args.manifest.read_text())
        if manifest.get("schema_version", 0) < 2:
            parser.error("schema v2 manifest required for target lifetimes")
        expected += manifest_targets(manifest, args.workload_cluster)
    end = args.end or dt.datetime.now(UTC)
    start = args.start or end - dt.timedelta(minutes=30)
    if start >= end:
        parser.error("start must precede end")
    try:
        access_token = token()
        metrics = metric_coverage(args.project, start, end, access_token)
        node_targets = {(t["cluster"], t["instance"]) for t in metrics["system_cpu"]["targets"] if t["cluster"] in K8S_CLUSTERS}
        node_targets |= {(t["cluster"], t["instance"]) for t in expected if t["cluster"] in K8S_CLUSTERS}
        logs = log_coverage(args.project, args.region, start, end, node_targets)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, urllib.error.URLError, ValueError) as exc:
        print(json.dumps({"state": "query_failed", "error": type(exc).__name__}), file=sys.stderr)
        return 2
    missing = assess(metrics, logs, start, end, args.max_gap_seconds, expected, args.host_cluster)
    print(json.dumps({"state": "complete" if not missing else "missing_data",
                      "start_utc": iso(start), "end_utc": iso(end),
                      "max_gap_seconds": args.max_gap_seconds, "expected_target_count": len(expected),
                      "metrics": metrics, "logs": logs, "missing": missing}, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
