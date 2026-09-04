from __future__ import annotations

import json
import os
import shutil
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import ProbeConfig


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def host_status() -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {"status": "healthy", "observed_at": now(), "hostname": socket.gethostname(), "cpu_count": os.cpu_count() or 1}
    try:
        with open("/proc/loadavg", encoding="utf-8") as stream:
            result["load_1m"] = float(stream.read().split()[0])
        values: dict[str, int] = {}
        with open("/proc/meminfo", encoding="utf-8") as stream:
            for line in stream:
                key, _, value = line.partition(":")
                if key in {"MemTotal", "MemAvailable"}:
                    values[key] = int(value.strip().split()[0]) * 1024
        total, available = values.get("MemTotal", 0), values.get("MemAvailable", 0)
        if total:
            result.update(memory_total_bytes=total, memory_used_bytes=total - available, memory_usage_percent=round((total - available) * 100 / total, 2))
        usage = shutil.disk_usage("/")
        result["filesystems"] = [{"mountpoint": "/", "usage_percent": round((usage.total - usage.free) * 100 / usage.total, 2)}]
    except (OSError, ValueError, IndexError):
        result.update(status="unknown", reason="HOST_METRICS_UNAVAILABLE")
    result["latency_ms"] = int((time.monotonic() - started) * 1000)
    return result


def pod_api_path(namespace: str | None = None) -> str:
    if not namespace:
        return "/api/v1/pods"
    return f"/api/v1/namespaces/{urllib.parse.quote(namespace, safe='')}/pods"


class KubernetesClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token = os.getenv("KUBERNETES_API_TOKEN", "").strip()
        if not self.token:
            try:
                with open("/var/run/secrets/kubernetes.io/serviceaccount/token", encoding="utf-8") as stream:
                    self.token = stream.read().strip()
            except OSError:
                pass
        self.context = ssl.create_default_context()
        try:
            self.context.load_verify_locations(os.getenv("KUBERNETES_CA_FILE", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"))
        except OSError:
            pass

    def get_json(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(self.base_url + path, headers={"Authorization": f"Bearer {self.token}"} if self.token else {})
        with urllib.request.urlopen(request, context=self.context, timeout=4) as response:
            if response.status // 100 != 2:
                raise urllib.error.HTTPError(request.full_url, response.status, response.reason, response.headers, None)
            return json.loads(response.read(8 * 1024 * 1024))


    def collect(self, namespace: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        started = time.monotonic()
        cluster: dict[str, Any] = {"status": "healthy", "observed_at": now(), "node_count": 0, "ready_node_count": 0, "pod_count": 0}
        pods: dict[str, Any] = {"status": "healthy", "observed_at": now(), "total": 0, "running": 0, "pending": 0, "failed": 0, "succeeded": 0, "unknown": 0, "unhealthy": []}
        if namespace:
            pods["namespace"] = namespace
        try:
            cluster["version"] = self.get_json("/version").get("gitVersion", "")
            nodes = self.get_json("/api/v1/nodes").get("items", [])
            cluster["node_count"] = len(nodes)
            cluster["ready_node_count"] = sum(1 for node in nodes if any(c.get("type") == "Ready" and c.get("status") == "True" for c in node.get("status", {}).get("conditions", [])))
            try:
                pod_items = self.get_json(pod_api_path(namespace)).get("items", [])
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and namespace:
                    pods.update(status="unknown", reason="NAMESPACE_NOT_FOUND")
                elif exc.code == 403:
                    pods.update(status="unknown", reason="PODS_FORBIDDEN")
                else:
                    pods.update(status="degraded", reason="PODS_UNAVAILABLE")
                pod_items = []
            summarize_pods(pods, pod_items)
            cluster["pod_count"] = pods["total"]
            if cluster["ready_node_count"] < cluster["node_count"]:
                cluster.update(status="degraded", reason="NODE_NOT_READY")
        except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            cluster.update(status="unknown", reason="KUBERNETES_UNAVAILABLE")
            if pods["status"] == "healthy":
                pods.update(status="unknown", reason="KUBERNETES_UNAVAILABLE")
        latency = int((time.monotonic() - started) * 1000)
        cluster["latency_ms"] = latency
        pods["latency_ms"] = latency
        return cluster, pods


def summarize_pods(summary: dict[str, Any], items: list[dict[str, Any]]) -> None:
    summary["total"] = len(items)
    for pod in items:
        status = pod.get("status", {})
        phase = status.get("phase", "Unknown")
        key = {"Running": "running", "Pending": "pending", "Failed": "failed", "Succeeded": "succeeded"}.get(phase, "unknown")
        summary[key] += 1
        containers = status.get("containerStatuses", [])
        ready = all(container.get("ready", False) for container in containers) if containers else False
        restarts = sum(int(container.get("restartCount", 0)) for container in containers)
        reason = next((container.get("state", {}).get("waiting", {}).get("reason") for container in containers if container.get("state", {}).get("waiting")), "")
        pod_status = {"namespace": pod.get("metadata", {}).get("namespace", ""), "name": pod.get("metadata", {}).get("name", ""), "phase": phase, "ready": ready, "restart_count": restarts, "reason": reason}
        summary.setdefault("items", []).append(pod_status)
        if (phase == "Running" and not ready) or phase == "Failed" or reason:
            if len(summary["unhealthy"]) < 50:
                summary["unhealthy"].append(pod_status)
            summary.update(status="degraded", reason="POD_UNHEALTHY")


def run_probes(configs: tuple[ProbeConfig, ...]) -> list[dict[str, Any]]:
    result = []
    for config in configs:
        started = time.monotonic()
        item = {"name": config.name, "type": config.kind, "status": "healthy", "observed_at": now()}
        try:
            if config.kind.lower() in {"http", "https"}:
                request = urllib.request.Request(config.target, method="GET")
                with urllib.request.urlopen(request, timeout=2) as response:
                    if response.status >= 400:
                        raise OSError(f"HTTP {response.status}")
            elif config.kind.lower() in {"tcp", "redis", "mysql", "kafka"}:
                host, port = config.target.rsplit(":", 1)
                with socket.create_connection((host, int(port)), timeout=2):
                    pass
            else:
                raise ValueError("unsupported probe type")
        except (OSError, ValueError, urllib.error.URLError, TimeoutError):
            item.update(status="unhealthy", reason="PROBE_FAILED")
        item["latency_ms"] = int((time.monotonic() - started) * 1000)
        result.append(item)
    return result
