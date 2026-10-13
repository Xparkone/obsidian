from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    host: str
    port: int
    seed_demo: bool
    feishu_webhook: str | None
    dingtalk_webhook: str | None
    wecom_webhook: str | None
    admin_token: str
    executor_mode: str
    ssh_timeout: float


def load_settings() -> Settings:
    data_dir = Path(os.getenv("AEGIS_DATA_DIR", "/var/lib/aegis"))
    db_path = Path(os.getenv("AEGIS_DB_PATH", str(data_dir / "aegis.db")))
    return Settings(
        data_dir=data_dir,
        db_path=db_path,
        host=os.getenv("AEGIS_HOST", "0.0.0.0"),
        port=int(os.getenv("AEGIS_PORT", "8080")),
        seed_demo=os.getenv("AEGIS_SEED_DEMO", "true").lower() in {"1", "true", "yes"},
        feishu_webhook=os.getenv("AEGIS_FEISHU_WEBHOOK") or None,
        dingtalk_webhook=os.getenv("AEGIS_DINGTALK_WEBHOOK") or None,
        wecom_webhook=os.getenv("AEGIS_WECOM_WEBHOOK") or None,
        admin_token=os.getenv("AEGIS_ADMIN_TOKEN", ""),
        executor_mode=os.getenv("AEGIS_EXECUTOR_MODE", "dry-run").lower(),
        ssh_timeout=float(os.getenv("AEGIS_SSH_TIMEOUT", "15")),
    )
