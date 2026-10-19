from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ArchiveUnavailable(RuntimeError):
    """Raised when the configured audit archive cannot accept an event."""


class AuditArchive(Protocol):
    """Append-only audit archive contract.

    A production implementation must map this contract to an object store
    bucket with retention/object-lock enabled. Local JSONL is only a test or
    staging adapter and must not be described as immutable storage.
    """

    def append(self, event: dict[str, Any]) -> str: ...


@dataclass
class JsonlAuditArchive:
    """Write a hash-linked JSONL copy of audit events.

    The hash chain detects ordinary edits, but the local file remains mutable
    by the host administrator. It is not a WORM or object-lock guarantee.
    """

    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._previous_hash = self._read_previous_hash()

    def _read_previous_hash(self) -> str:
        if not self.path.exists():
            return ""
        try:
            with self.path.open("rb") as stream:
                last = b""
                for line in stream:
                    if line.strip():
                        last = line
            if not last:
                return ""
            record = json.loads(last.decode("utf-8"))
            return str(record.get("record_hash", ""))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveUnavailable(f"审计归档文件不可读取: {self.path}") from exc

    def append(self, event: dict[str, Any]) -> str:
        body = {
            "archived_at": utc_now(),
            "event": event,
            "previous_hash": self._previous_hash,
        }
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        record = {**body, "record_hash": record_hash}
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise ArchiveUnavailable(f"审计归档写入失败: {self.path}") from exc
        self._previous_hash = record_hash
        return record_hash


@dataclass
class S3ObjectLockAuditArchive:
    """Store each audit event in an Object Lock protected S3 object.

    The bucket must already have versioning and Object Lock enabled. The
    provider is injected in tests; production lazily imports boto3 so local
    SQLite-only use does not require cloud credentials.
    """

    bucket: str
    prefix: str = "aegis-audit"
    retention_days: int = 365
    endpoint_url: str | None = None
    client: Any | None = None

    def __post_init__(self) -> None:
        if not self.bucket.strip():
            raise ValueError("Object Lock archive bucket is required")
        if self.retention_days <= 0:
            raise ValueError("Object Lock retention_days must be positive")
        if self.client is None:
            try:
                import boto3
                self.client = boto3.client("s3", endpoint_url=self.endpoint_url)
            except ImportError as exc:
                raise ArchiveUnavailable("S3 Object Lock 归档需要安装 boto3") from exc

    def append(self, event: dict[str, Any]) -> str:
        archived_at = utc_now()
        body = {"archived_at": archived_at, "event": event}
        canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload = (canonical + "\n").encode("utf-8")
        event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        day = archived_at[:10]
        key = f"{self.prefix.strip('/')}/{day}/{event.get('id', 'unknown')}-{event_hash}.json"
        retain_until = datetime.now(timezone.utc) + timedelta(days=self.retention_days)
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=payload,
                ContentMD5=base64.b64encode(hashlib.md5(payload).digest()).decode("ascii"),
                ContentType="application/json",
                ObjectLockMode="COMPLIANCE",
                ObjectLockRetainUntilDate=retain_until,
            )
        except Exception as exc:  # provider errors must be handled by the caller's policy
            raise ArchiveUnavailable(f"S3 Object Lock 归档写入失败: {type(exc).__name__}") from exc
        return f"s3://{self.bucket}/{key}"

