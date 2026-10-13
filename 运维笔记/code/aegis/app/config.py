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


def _load_local_env() -> None:
    """读取项目目录 .env；不覆盖已经由 shell 或容器注入的变量。"""
    env_file = Path.cwd() / ".env"
    if not env_file.is_file():
        return
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_settings() -> Settings:
    _load_local_env()
    # 本地直接运行时不能假设用户有权限写 /var/lib；容器通过环境变量覆盖为挂载卷。
    default_data_dir = Path.cwd() / "data"
    data_dir = Path(os.getenv("AEGIS_DATA_DIR", str(default_data_dir))).expanduser()
    if not data_dir.is_absolute():
        data_dir = Path.cwd() / data_dir
    db_path = Path(os.getenv("AEGIS_DB_PATH", str(data_dir / "aegis.db"))).expanduser()
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
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
