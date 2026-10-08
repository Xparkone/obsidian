from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    prometheus_url: str = "http://prometheus.monitoring.svc:9090"
    prometheus_token: str = ""
    request_timeout_seconds: float = 5.0
    service_namespace: str = ""
    service_names: tuple[str, ...] = ()
    disk_mountpoints: tuple[str, ...] = ("/",)
    load_per_cpu_warn: float = 1.0
    load_per_cpu_critical: float = 2.0
    memory_warn_percent: float = 80.0
    memory_critical_percent: float = 90.0
    disk_warn_percent: float = 80.0
    disk_critical_percent: float = 90.0
    rules_dir: str = ""
    report_dir: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        # 默认读取当前工作目录下的 .env；已存在的系统环境变量优先。
        load_dotenv(override=False)

        def csv(name: str) -> tuple[str, ...]:
            return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())

        root = project_root()
        return cls(
            prometheus_url=os.getenv("PROMETHEUS_URL", cls.prometheus_url).rstrip("/"),
            prometheus_token=os.getenv("PROMETHEUS_TOKEN", "").strip(),
            request_timeout_seconds=float(os.getenv("PROMETHEUS_TIMEOUT_SECONDS", "5")),
            service_namespace=os.getenv("K8S_SERVICE_NAMESPACE", "").strip(),
            service_names=csv("K8S_SERVICE_NAMES"),
            disk_mountpoints=csv("DISK_MOUNTPOINTS") or ("/",),
            load_per_cpu_warn=float(os.getenv("LOAD_PER_CPU_WARN", "1.0")),
            load_per_cpu_critical=float(os.getenv("LOAD_PER_CPU_CRITICAL", "2.0")),
            memory_warn_percent=float(os.getenv("MEMORY_WARN_PERCENT", "80")),
            memory_critical_percent=float(os.getenv("MEMORY_CRITICAL_PERCENT", "90")),
            disk_warn_percent=float(os.getenv("DISK_WARN_PERCENT", "80")),
            disk_critical_percent=float(os.getenv("DISK_CRITICAL_PERCENT", "90")),
            rules_dir=os.getenv("INSPECTION_RULES_DIR", str(root / "rules")).strip(),
            report_dir=os.getenv("INSPECTION_REPORT_DIR", str(root / "reports")).strip(),
        )
