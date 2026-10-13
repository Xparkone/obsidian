from __future__ import annotations

from dataclasses import dataclass
import subprocess
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


class SSHExecutor:
    """通过系统 ssh 客户端执行已通过策略的命令。

    主机、用户和 known_hosts 路径来自管理员登记的服务器资产，命令不经过本地 shell。
    生产环境仍应使用专用低权限账号、短期凭据和独立跳板网络。
    """

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout

    def execute(self, server: dict[str, Any], command: str) -> ExecutionResult:
        username = str(server.get("username") or "").strip()
        address = str(server.get("address") or "").strip()
        if not username or not address:
            return ExecutionResult("failed", "ssh", "服务器缺少 SSH 用户或地址")
        target = f"{username}@{address}"
        args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", f"ConnectTimeout={max(1, int(self.timeout))}"]
        known_hosts = str(server.get("known_hosts_path") or "").strip()
        if known_hosts:
            args.extend(["-o", f"UserKnownHostsFile={known_hosts}"])
        args.extend(["-p", str(int(server.get("port") or 22)), target, command])
        try:
            completed = subprocess.run(args, capture_output=True, text=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            return ExecutionResult("failed", "ssh", "SSH 执行超时")
        except OSError as exc:
            return ExecutionResult("failed", "ssh", f"SSH 客户端不可用: {type(exc).__name__}")
        output = (completed.stdout or completed.stderr or "").strip()
        return ExecutionResult("completed" if completed.returncode == 0 else "failed", "ssh", output[:12000])
