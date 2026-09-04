from __future__ import annotations

import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .collectors import KubernetesClient, host_status, now, run_probes
from .config import Settings


def aggregate(data: dict[str, Any]) -> str:
    states = [data["host"].get("status"), data["kubernetes"].get("status"), data["pods"].get("status")]
    states.extend(item.get("status") for item in data["middlewares"])
    states.extend(item.get("status") for item in data.get("services", []))
    if "unhealthy" in states:
        return "unhealthy"
    if any(state in {"degraded", "unknown"} for state in states):
        return "degraded"
    return "healthy"


class StatusHandler(BaseHTTPRequestHandler):
    settings: Settings
    kube: KubernetesClient

    def log_message(self, fmt: str, *args: Any) -> None:
        # 不记录 Authorization Header，避免把 token 写入日志。
        return

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path)
        if path.path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return
        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return
        query = parse_qs(path.query)
        namespace = query.get("namespace", [None])[0]
        if path.path == "/api/v1/status":
            kubernetes, pods = self.kube.collect(namespace)
            data = {"host": host_status(), "kubernetes": kubernetes, "pods": pods, "services": run_probes(self.settings.services), "middlewares": run_probes(self.settings.probes)}
            self.send_json(200, {"schema_version": "v1", "request_id": str(time.time_ns()), "status": aggregate(data), "observed_at": now(), "data": data, "errors": []})
        elif path.path == "/api/v1/host":
            self.send_json(200, host_status())
        elif path.path == "/api/v1/k8s":
            self.send_json(200, self.kube.collect(namespace)[0])
        elif path.path == "/api/v1/k8s/pods":
            self.send_json(200, self.kube.collect(namespace)[1])
        elif path.path == "/api/v1/middlewares":
            self.send_json(200, run_probes(self.settings.probes))
        elif path.path == "/api/v1/services":
            self.send_json(200, run_probes(self.settings.services))
        else:
            self.send_json(404, {"error": "not found"})

    def authorized(self) -> bool:
        value = self.headers.get("Authorization", "")
        return bool(self.settings.token) and value.startswith("Bearer ") and hmac.compare_digest(value[7:].strip(), self.settings.token)

    def send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(settings: Settings) -> None:
    StatusHandler.settings = settings
    StatusHandler.kube = KubernetesClient(settings.kubernetes_api_url)
    server = ThreadingHTTPServer((settings.host, settings.port), StatusHandler)
    print(f"status API listening on http://{settings.host}:{settings.port}")
    server.serve_forever()
