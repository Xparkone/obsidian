from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Query

from .config import Settings
from .prometheus import PrometheusClient, PrometheusError, labels, value

settings = Settings.from_env()
prom = PrometheusClient(settings.prometheus_url, settings.request_timeout_seconds, settings.prometheus_token)
app = FastAPI(title="Kubernetes Prometheus Status API", version="1.0.0")


def observed_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def level(number: float, warn: float, critical: float) -> str:
    if number >= critical:
        return "unhealthy"
    if number >= warn:
        return "degraded"
    return "healthy"


def check(name: str, status: str, value_: Any = None, reason: str | None = None, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "status": status}
    if value_ is not None:
        result["value"] = value_
    if reason:
        result["reason"] = reason
    result.update(extra)
    return result


async def safe_query(name: str, query: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        return await prom.query(query), None
    except PrometheusError as exc:
        return [], check(name, "unknown", reason="PROMETHEUS_QUERY_FAILED", detail=str(exc))


async def node_checks() -> list[dict[str, Any]]:
    ready_q = 'kube_node_status_condition{condition="Ready",status="true"}'
    unschedulable_q = "kube_node_spec_unschedulable"
    results, error = await safe_query("k8s_nodes", ready_q)
    if error:
        return [error]
    unschedulable, _ = await safe_query("k8s_nodes_unschedulable", unschedulable_q)
    blocked = {labels(item).get("node") for item in unschedulable if value(item) > 0}
    nodes = []
    for item in results:
        node = labels(item).get("node", labels(item).get("instance", "unknown"))
        ready = value(item) == 1
        nodes.append(check(f"node:{node}", "healthy" if ready else "unhealthy", ready=ready, unschedulable=node in blocked, node=node))
    if not nodes:
        return [check("k8s_nodes", "unknown", reason="NO_NODE_METRICS")]
    return nodes


def service_selector(namespace: str | None, service: str | None) -> str:
    clauses = []
    if namespace:
        clauses.append(f'namespace="{re.escape(namespace)}"')
    if service:
        clauses.append(f'service="{re.escape(service)}"')
    elif settings.service_names:
        names = "|".join(re.escape(item) for item in settings.service_names)
        clauses.append(f'service=~"{names}"')
    return "{" + ",".join(clauses) + "}" if clauses else ""


async def service_checks(namespace: str | None, service: str | None) -> list[dict[str, Any]]:
    selector = service_selector(namespace, service)
    # kube_endpoint_address_available 由 kube-state-metrics 提供；没有该指标时会返回 unknown。
    query = f"kube_endpoint_address_available{selector}"
    results, error = await safe_query("k8s_services", query)
    if error:
        return [error]
    grouped: dict[tuple[str, str], float] = {}
    for item in results:
        metric = labels(item)
        key = (metric.get("namespace", ""), metric.get("service", metric.get("endpoint", "")))
        grouped[key] = grouped.get(key, 0) + value(item)
    if not grouped:
        return [check("k8s_services", "unknown", reason="NO_SERVICE_ENDPOINT_METRICS")]
    return [
        check(f"service:{ns}/{name}", "healthy" if count > 0 else "unhealthy", endpoint_count=int(count), namespace=ns, service=name)
        for (ns, name), count in sorted(grouped.items())
    ]


async def host_checks() -> list[dict[str, Any]]:
    load_q = "node_load1"
    cpu_q = 'count by(instance) (node_cpu_seconds_total{mode="idle"})'
    mem_q = "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)"
    disk_q = '100 * (1 - node_filesystem_avail_bytes / node_filesystem_size_bytes)'
    results, load_error = await safe_query("host_load", load_q)
    cpus, _ = await safe_query("host_cpu_count", cpu_q)
    mems, mem_error = await safe_query("host_memory", mem_q)
    disks, disk_error = await safe_query("host_disk", disk_q)
    checks: list[dict[str, Any]] = []
    cpu_counts = {labels(item).get("instance", "unknown"): max(value(item), 1) for item in cpus}
    if load_error:
        checks.append(load_error)
    elif not results:
        checks.append(check("host_load", "unknown", reason="NO_NODE_EXPORTER_METRICS"))
    else:
        for item in results:
            metric = labels(item)
            instance = metric.get("instance", "unknown")
            load = value(item)
            per_cpu = load / cpu_counts.get(instance, 1)
            checks.append(check(f"load:{instance}", level(per_cpu, settings.load_per_cpu_warn, settings.load_per_cpu_critical), load_1m=round(load, 3), load_per_cpu=round(per_cpu, 3), instance=instance))
    if mem_error:
        checks.append(mem_error)
    else:
        for item in mems:
            metric = labels(item); percent = value(item); instance = metric.get("instance", "unknown")
            checks.append(check(f"memory:{instance}", level(percent, settings.memory_warn_percent, settings.memory_critical_percent), usage_percent=round(percent, 2), instance=instance))
    if disk_error:
        checks.append(disk_error)
    else:
        wanted = set(settings.disk_mountpoints)
        for item in disks:
            metric = labels(item); mountpoint = metric.get("mountpoint", "")
            if wanted and mountpoint not in wanted:
                continue
            percent = value(item); instance = metric.get("instance", "unknown")
            checks.append(check(f"disk:{instance}:{mountpoint}", level(percent, settings.disk_warn_percent, settings.disk_critical_percent), usage_percent=round(percent, 2), instance=instance, mountpoint=mountpoint, device=metric.get("device", "")))
    return checks or [check("host", "unknown", reason="NO_HOST_METRICS")]


def aggregate(checks: list[dict[str, Any]]) -> str:
    statuses = {item.get("status") for item in checks}
    if "unhealthy" in statuses:
        return "unhealthy"
    if "degraded" in statuses or "unknown" in statuses:
        return "degraded"
    return "healthy"


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/status")
async def status(namespace: str | None = Query(None), service: str | None = Query(None)) -> dict[str, Any]:
    ns = namespace or settings.service_namespace or None
    svc = service or None
    checks = [item for group in await asyncio.gather(node_checks(), service_checks(ns, svc), host_checks()) for item in group]
    return {"status": aggregate(checks), "observed_at": observed_at(), "prometheus_url": settings.prometheus_url, "checks": checks}


@app.get("/api/v1/kubernetes/nodes")
async def nodes() -> dict[str, Any]:
    checks = await node_checks()
    return {"status": aggregate(checks), "observed_at": observed_at(), "checks": checks}


@app.get("/api/v1/kubernetes/services")
async def services(namespace: str | None = Query(None), service: str | None = Query(None)) -> dict[str, Any]:
    checks = await service_checks(namespace or settings.service_namespace or None, service)
    return {"status": aggregate(checks), "observed_at": observed_at(), "checks": checks}


@app.get("/api/v1/host")
async def host() -> dict[str, Any]:
    checks = await host_checks()
    return {"status": aggregate(checks), "observed_at": observed_at(), "checks": checks}
