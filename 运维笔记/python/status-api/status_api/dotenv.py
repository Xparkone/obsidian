from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path, optional: bool = True) -> None:
    """Load simple KEY=VALUE entries without overriding process variables."""
    file_path = Path(path)
    if not file_path.exists():
        if optional:
            return
        raise FileNotFoundError(file_path)
    for number, raw_line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"invalid env file {file_path} line {number}")
        key, value = (part.strip() for part in line.split("=", 1))
        if not key:
            raise ValueError(f"invalid env file {file_path} line {number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_configured_env() -> None:
    configured = os.getenv("STATUS_API_ENV_FILE")
    if configured:
        load_env_file(configured, optional=False)
    else:
        load_env_file(".env")
