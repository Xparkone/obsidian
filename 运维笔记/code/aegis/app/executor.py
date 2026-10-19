from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
import subprocess
from typing import Any, Protocol

from .rules import CommandAllowlist, CommandValidationError


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    mode: str
    output: str


class Executor(Protocol):
    def execute(self, server: dict[str, Any], command: str) -> ExecutionResult: ...


class CredentialProviderError(RuntimeError):
    """Raised when an SSH credential cannot be resolved safely."""


@dataclass(frozen=True)
class SSHCredential:
    identity_file: Path


class CredentialProvider(Protocol):
    def resolve(self, reference: str) -> SSHCredential: ...


class DisabledCredentialProvider:
    """Default provider; prevents SSH from falling back to user credentials."""

    def resolve(self, reference: str) -> SSHCredential:
        raise CredentialProviderError("未配置受控 SSH 凭据提供器")


class SecretDirectoryCredentialProvider:
    """Resolve opaque ``secret://name`` references from a mounted secret directory.

    This is a local boundary for Docker/Kubernetes Secret mounts. It never
    accepts private-key contents over the API and rejects path traversal,
    symlinks escaping the directory, and group/world-writable key files.
    """

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    def resolve(self, reference: str) -> SSHCredential:
        if not isinstance(reference, str) or not reference.startswith("secret://"):
            raise CredentialProviderError("credential_ref 必须使用 secret:// 引用")
        relative = reference.removeprefix("secret://").strip()
        if not relative or relative.startswith("/"):
            raise CredentialProviderError("credential_ref 不是有效的 Secret 引用")
        if ".." in Path(relative).parts:
            raise CredentialProviderError("credential_ref 不允许路径穿越片段")
        candidate = (self.root / relative).resolve()
        if self.root not in candidate.parents or not candidate.is_file():
            raise CredentialProviderError("SSH Secret 不存在或不在受控目录内")
        mode = stat.S_IMODE(candidate.stat().st_mode)
        if mode & 0o077:
            raise CredentialProviderError("SSH Secret 文件权限必须禁止组用户和其他用户访问")
        return SSHCredential(candidate)


class DryRunExecutor:
    """安全联调适配器；它不创建 SSH 连接，也不执行 shell。"""

    def execute(self, server: dict[str, Any], command: str) -> ExecutionResult:
        return ExecutionResult("accepted", "dry-run", f"would execute on {server['name']}: {command}")


class SSHExecutor:
    """通过系统 ssh 客户端执行已通过策略的命令。

    主机、用户和 known_hosts 路径来自管理员登记的服务器资产；命令先经过
    CommandAllowlist 分词并以参数数组交给 ssh。远端仍可能存在登录 Shell，
    因此生产环境还应使用专用低权限账号、短期凭据和独立跳板网络。
    """

    def __init__(self, timeout: float = 15.0, credential_provider: CredentialProvider | None = None, command_allowlist: CommandAllowlist | None = None):
        self.timeout = timeout
        self.credential_provider = credential_provider or DisabledCredentialProvider()
        self.command_allowlist = command_allowlist or CommandAllowlist.from_env()

    def execute(self, server: dict[str, Any], command: str) -> ExecutionResult:
        username = str(server.get("username") or "").strip()
        address = str(server.get("address") or "").strip()
        if not username or not address:
            return ExecutionResult("failed", "ssh", "服务器缺少 SSH 用户或地址")
        try:
            argv = self.command_allowlist.parse(command)
        except CommandValidationError as exc:
            return ExecutionResult("failed", "ssh", str(exc))
        credential_ref = str(server.get("credential_ref") or "").strip()
        known_hosts = str(server.get("known_hosts_path") or "").strip()
        if not credential_ref:
            return ExecutionResult("failed", "ssh", "服务器缺少受控 SSH 凭据引用")
        if not known_hosts or not Path(known_hosts).is_file():
            return ExecutionResult("failed", "ssh", "服务器缺少受控 known_hosts 文件")
        try:
            credential = self.credential_provider.resolve(credential_ref)
        except CredentialProviderError as exc:
            return ExecutionResult("failed", "ssh", str(exc))
        target = f"{username}@{address}"
        args = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "IdentityAgent=none",
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "PubkeyAuthentication=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", f"ConnectTimeout={max(1, int(self.timeout))}",
            "-i", str(credential.identity_file),
        ]
        args.extend(["-p", str(int(server.get("port") or 22)), target, *argv])
        try:
            completed = subprocess.run(args, capture_output=True, text=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired:
            return ExecutionResult("failed", "ssh", "SSH 执行超时")
        except OSError as exc:
            return ExecutionResult("failed", "ssh", f"SSH 客户端不可用: {type(exc).__name__}")
        output = (completed.stdout or completed.stderr or "").strip()
        return ExecutionResult("completed" if completed.returncode == 0 else "failed", "ssh", output[:12000])
