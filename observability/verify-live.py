#!/usr/bin/env python3
"""Read-only Cloud Monitoring/Logging coverage check for a UTC run interval."""
from __future__ import annotations

import argparse
import datetime as dt
import json
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
        matches = [name for name in available if name.startswith("prometheus.googleapis.com/" + prefix)]
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
        targets = sorted({(row.get("resource", {}).get("labels", {}).get("cluster", "?"),
                           row.get("resource", {}).get("labels", {}).get("instance", "?"))
                          for row in series if row.get("points")})
        latest = max((point.get("interval", {}).get("endTime", "")
                      for row in series for point in row.get("points", [])), default="")
        results[category] = {"metric": name, "series": sum(bool(row.get("points")) for row in series),
                           "latest_utc": latest or None,
                           "targets": [{"cluster": cluster, "instance": instance}
                                       for cluster, instance in targets]}
    return results


def log_coverage(project: str, region: str, start: dt.datetime, end: dt.datetime) -> dict:
    base = f'log_id("osk8s-otel") AND timestamp>="{iso(start)}" AND timestamp<="{iso(end)}"'

    def read(extra: str, limit: int) -> list[dict]:
        raw = subprocess.check_output([
            "gcloud", "logging", "read", base + (" AND " + extra if extra else ""),
            "--project=" + project, "--bucket=osk8s-observability",
            "--location=" + region, "--view=_AllLogs",
            f"--limit={limit}", "--format=json"], text=True, stderr=subprocess.PIPE)
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
    return {"sampled_count": len(rows), "sample_limit": 1000,
            "latest_utc": max((row.get("timestamp", "") for row in rows), default=None),
            "sources": sources}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="openstack-k8s")
    parser.add_argument("--region", default="asia-northeast3")
    parser.add_argument("--start", type=parse_time)
    parser.add_argument("--end", type=parse_time)
    args = parser.parse_args()
    end = args.end or dt.datetime.now(UTC)
    start = args.start or end - dt.timedelta(minutes=30)
    if start >= end:
        parser.error("start must precede end")
    try:
        access_token = token()
        metrics = metric_coverage(args.project, start, end, access_token)
        logs = log_coverage(args.project, args.region, start, end)
    except (subprocess.CalledProcessError, urllib.error.URLError, ValueError) as exc:
        print(json.dumps({"state": "query_failed", "error": type(exc).__name__}), file=sys.stderr)
        return 2
    missing = [category for category, row in metrics.items() if row["series"] == 0]
    for category in ("system_cpu", "system_memory", "system_disk", "system_network"):
        seen_hosts = {target["instance"] for target in metrics[category]["targets"]
                      if target["cluster"] == "cloud-gcp-amd64-hosts"}
        missing.extend(f"{category}:{host}" for host in sorted(HOST_INSTANCES - seen_hosts))
    for category in ("k8s_node", "k8s_pod", "k8s_container", "k8s_node_ready",
                     "k8s_pod_phase", "k8s_deployment_available"):
        seen = {target["cluster"] for target in metrics[category]["targets"]}
        missing.extend(f"{category}:{cluster}" for cluster in sorted(K8S_CLUSTERS - seen))
    for category, row in metrics.items():
        if row.get("latest_utc") and parse_time(row["latest_utc"]) < end - dt.timedelta(minutes=5):
            missing.append(f"{category}:stale")
    if not logs["sampled_count"]:
        missing.append("logs")
    for source in ("heartbeat", "nova_inventory", "kolla", "pod_logs"):
        if not logs["sources"][source]["present"]:
            missing.append(f"logs:{source}")
    print(json.dumps({"state": "complete" if not missing else "missing_data",
                      "start_utc": iso(start), "end_utc": iso(end),
                      "metrics": metrics, "logs": logs, "missing": missing}, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
