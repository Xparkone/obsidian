from __future__ import annotations

import os
from dataclasses import dataclass


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
    probes: tuple[ProbeConfig, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        probes: list[ProbeConfig] = []
        for item in os.getenv("STATUS_MIDDLEWARES", "").split(","):
            parts = item.strip().split("|", 2)
            if len(parts) == 3 and all(parts):
                probes.append(ProbeConfig(*parts))
        return cls(
            host=os.getenv("STATUS_API_HOST", "0.0.0.0"),
            port=int(os.getenv("STATUS_API_PORT", "8080")),
            token=os.getenv("STATUS_API_TOKEN", ""),
            kubernetes_api_url=os.getenv("KUBERNETES_API_URL", "https://kubernetes.default.svc").rstrip("/"),
            probes=tuple(probes),
        )
