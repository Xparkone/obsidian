from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    mode: str
    output: str


class Executor(Protocol):
    def execute(self, server: dict[str, Any], command: str) -> ExecutionResult: ...


class DryRunExecutor:
    """安全联调适配器；它不创建 SSH 连接，也不执行 shell。"""

    def execute(self, server: dict[str, Any], command: str) -> ExecutionResult:
        return ExecutionResult("accepted", "dry-run", f"would execute on {server['name']}: {command}")
