"""把 Aegis 暴露成 MCP stdio 工具服务器。

兼容支持 MCP 的 Codex 类 Agent、Claude Code、Cursor 和自研 Agent Host。
配置通过环境变量注入：AEGIS_URL、AEGIS_AGENT_KEY。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
from ai_agent import AegisClient, AegisError  # noqa: E402


TOOLS = [
    {
        "name": "aegis_list_servers",
        "description": "列出当前 AI 身份被授权可见的服务器。不要猜测或构造 server_id。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "aegis_execute",
        "description": "通过 Aegis 策略网关执行命令。403 表示权限或规则阻断，禁止修改命令绕过规则后重试。",
        "inputSchema": {
            "type": "object",
            "properties": {"server_id": {"type": "integer"}, "command": {"type": "string", "maxLength": 4096}},
            "required": ["server_id", "command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "aegis_get_audit",
        "description": "查看当前 AI 身份自己的审计事件。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def client_from_env() -> AegisClient:
    key = os.getenv("AEGIS_AGENT_KEY", "")
    if not key:
        raise AegisError(0, "AEGIS_AGENT_KEY 未配置")
    return AegisClient(os.getenv("AEGIS_URL", "http://127.0.0.1:8080"), key)


def text_result(value: Any, is_error: bool = False) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    client = client_from_env()
    if name == "aegis_list_servers":
        return text_result(client.visible_servers())
    if name == "aegis_execute":
        if not isinstance(arguments.get("server_id"), int) or not isinstance(arguments.get("command"), str):
            return text_result("server_id 必须是整数，command 必须是字符串", True)
        return text_result(client.execute(arguments["server_id"], arguments["command"]))
    if name == "aegis_get_audit":
        return text_result(client._request("GET", "/api/v1/audit"))
    return text_result(f"未知工具: {name}", True)


def handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """处理一条 MCP JSON-RPC 消息；通知不返回响应。"""
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None and method and method.startswith("notifications/"):
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "aegis-mcp", "version": "0.1.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = call_tool(str(params.get("name", "")), params.get("arguments") or {})
        except AegisError as exc:
            result = text_result(str(exc), True)
        except Exception as exc:  # noqa: BLE001 - return tool failure to the host
            result = text_result(f"Aegis MCP tool failed: {type(exc).__name__}: {exc}", True)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle_message(json.loads(line))
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
