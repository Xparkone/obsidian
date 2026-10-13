"""Aegis AI Agent 最小客户端。

运行前先设置：
    export AEGIS_AGENT_KEY='aegis_...'
    python3 examples/ai_agent.py

这个客户端只调用 Aegis，不接触 SSH 私钥，也不直接连接服务器。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class AegisError(RuntimeError):
    status: int
    message: str
    payload: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"Aegis API {self.status}: {self.message}"


class AegisClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json", "X-Aegis-Key": self.api_key},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read().decode())
            except json.JSONDecodeError:
                result = {"error": exc.reason}
            raise AegisError(exc.code, result.get("error", "request failed"), result) from exc
        except urllib.error.URLError as exc:
            raise AegisError(0, f"无法连接 Aegis: {exc.reason}") from exc
        return result

    def visible_servers(self) -> list[dict[str, Any]]:
        """只返回该 AI 被授权可见的服务器。"""
        return self._request("GET", "/api/v1/servers").get("items", [])

    def execute(self, server_id: int, command: str) -> dict[str, Any]:
        """提交命令；403 表示权限或规则阻断，不能自行重试绕过。"""
        return self._request("POST", "/api/v1/execute", {"server_id": server_id, "command": command})


def main() -> int:
    api_key = os.getenv("AEGIS_AGENT_KEY")
    if not api_key:
        print("请先设置 AEGIS_AGENT_KEY（管理员创建身份时返回的 aegis_... 密钥）", file=sys.stderr)
        return 2
    client = AegisClient(os.getenv("AEGIS_URL", "http://127.0.0.1:8080"), api_key)
    try:
        servers = client.visible_servers()
        print("AI 可见服务器：")
        for server in servers:
            print(f"- id={server['id']} name={server['name']} address={server['address']} environment={server['environment']}")
        if not servers:
            print("没有可见服务器，请管理员创建 access grant。")
            return 0
        result = client.execute(servers[0]["id"], "uname -a")
        print("执行结果：")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except AegisError as exc:
        print(str(exc), file=sys.stderr)
        if exc.payload:
            print(json.dumps(exc.payload, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
