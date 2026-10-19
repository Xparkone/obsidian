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
    database_url: str | None = None
    audit_archive_path: Path | None = None
    audit_archive_required: bool = False
    audit_archive_s3_bucket: str | None = None
    audit_archive_s3_prefix: str = "aegis-audit"
    audit_archive_s3_retention_days: int = 365
    audit_archive_s3_endpoint_url: str | None = None
    ssh_credential_dir: Path | None = None


def _load_local_env() -> None:
    """读取项目目录 .env；非空 shell/container 环境变量优先。"""
    env_file = Path.cwd() / ".env"
    if not env_file.is_file():
        return
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        if key and not os.environ.get(key):
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
        database_url=os.getenv("AEGIS_DATABASE_URL") or None,
        audit_archive_path=(Path(os.getenv("AEGIS_AUDIT_ARCHIVE_PATH")).expanduser() if os.getenv("AEGIS_AUDIT_ARCHIVE_PATH") else None),
        audit_archive_required=os.getenv("AEGIS_AUDIT_ARCHIVE_REQUIRED", "false").lower() in {"1", "true", "yes"},
        audit_archive_s3_bucket=os.getenv("AEGIS_AUDIT_ARCHIVE_S3_BUCKET") or None,
        audit_archive_s3_prefix=os.getenv("AEGIS_AUDIT_ARCHIVE_S3_PREFIX", "aegis-audit"),
        audit_archive_s3_retention_days=int(os.getenv("AEGIS_AUDIT_ARCHIVE_S3_RETENTION_DAYS", "365")),
        audit_archive_s3_endpoint_url=os.getenv("AEGIS_AUDIT_ARCHIVE_S3_ENDPOINT_URL") or None,
        ssh_credential_dir=(Path(os.getenv("AEGIS_SSH_CREDENTIAL_DIR")).expanduser() if os.getenv("AEGIS_SSH_CREDENTIAL_DIR") else None),
    )
