from __future__ import annotations

import os
from dataclasses import dataclass

from .dotenv import load_configured_env


@dataclass(frozen=True)
class ProbeConfig:
    name: str
    kind: str
    target: str


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8080
    token: str = ""
    kubernetes_api_url: str = "https://kubernetes.default.svc"
    services: tuple[ProbeConfig, ...] = ()
    probes: tuple[ProbeConfig, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        load_configured_env()

        def parse_probes(key: str) -> tuple[ProbeConfig, ...]:
            values: list[ProbeConfig] = []
            for item in os.getenv(key, "").split(","):
                parts = item.strip().split("|", 2)
                if len(parts) == 3 and all(parts):
                    values.append(ProbeConfig(*parts))
            return tuple(values)

        return cls(
            host=os.getenv("STATUS_API_HOST", "0.0.0.0"),
            port=int(os.getenv("STATUS_API_PORT", "8080")),
            token=os.getenv("STATUS_API_TOKEN", ""),
            kubernetes_api_url=os.getenv("KUBERNETES_API_URL", "https://kubernetes.default.svc").rstrip("/"),
            services=parse_probes("STATUS_SERVICES"),
            probes=parse_probes("STATUS_MIDDLEWARES"),
        )
