from __future__ import annotations

import json
import re
import hmac
import sqlite3
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .db import Database, utc_now
from .executor import DryRunExecutor, SSHExecutor
from .notify import WebhookNotifier
from .rules import MAX_ENABLED_RULES, RegexValidationError, built_in_rules, compile_rule_pattern
from .security import api_key_prefix, hash_api_key, issue_api_key, verify_api_key


class AegisService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.db.seed([r.__dict__ for r in built_in_rules()], settings.seed_demo)
        self.notifier = WebhookNotifier({"feishu": settings.feishu_webhook, "dingtalk": settings.dingtalk_webhook, "wecom": settings.wecom_webhook})
        self.executor = SSHExecutor(settings.ssh_timeout) if settings.executor_mode == "ssh" else DryRunExecutor()
        self.counters = {"requests": 0, "commands": 0, "blocked": 0, "alerts": 0}
        self._compiled_rules: tuple[tuple[str, re.Pattern[str], str, str], ...] = ()
        self._rules_error: str | None = None
        self.refresh_rules()

    def principal_from_key(self, api_key: str | None) -> dict[str, Any] | None:
        if not api_key:
            return None
        prefix = api_key_prefix(api_key)
        candidates = self.db.rows("SELECT * FROM principals WHERE status='active' AND key_prefix=?", (prefix,))
        # Principals created before key_prefix was added retain an empty prefix.
        if not candidates:
            candidates = self.db.rows("SELECT * FROM principals WHERE status='active' AND key_prefix=''")
        for principal in candidates:
            if verify_api_key(api_key, principal["key_hash"]):
                return principal
        return None

    def refresh_rules(self) -> None:
        compiled: list[tuple[str, re.Pattern[str], str, str]] = []
        rows = self.db.rows("SELECT id,pattern,reason,severity FROM rules WHERE enabled=1 ORDER BY id")
        if len(rows) > MAX_ENABLED_RULES:
            self._compiled_rules = ()
            self._rules_error = f"启用规则数量超过上限 {MAX_ENABLED_RULES}"
            return
        for row in rows:
            try:
                compiled.append((row["id"], compile_rule_pattern(row["pattern"]), row["reason"], row["severity"]))
            except RegexValidationError as exc:
                # Do not silently skip an invalid enabled rule: allowing a
                # command while policy data is malformed would be a bypass.
                self._compiled_rules = ()
                self._rules_error = f"规则 {row['id']} 无法加载：{exc}"
                return
        self._compiled_rules = tuple(compiled)
        self._rules_error = None

    def visible_servers(self, principal_id: int | None = None) -> list[dict[str, Any]]:
        public_columns = "id,name,address,environment,tags_json,status,username,port,created_at"
        if principal_id is None:
            servers = self.db.rows(f"SELECT {public_columns} FROM servers ORDER BY id")
        else:
            scoped_columns = ",".join(f"s.{column}" for column in public_columns.split(","))
            servers = self.db.rows(f"SELECT {scoped_columns} FROM servers s JOIN access_grants g ON g.server_id=s.id WHERE g.principal_id=? ORDER BY s.id", (principal_id,))
        for server in servers:
            try:
                tags = json.loads(server.pop("tags_json", "[]"))
            except (TypeError, json.JSONDecodeError):
                tags = []
            server["tags"] = tags if isinstance(tags, list) else []
            server.pop("credential_ref", None)
            server.pop("known_hosts_path", None)
        return servers

    def evaluate(self, command: str) -> tuple[bool, str | None, str | None, str]:
        if self._rules_error:
            return False, "__rules_invalid__", self._rules_error, "critical"
        for rule_id, pattern, reason, severity in self._compiled_rules:
            if pattern.search(command):
                return False, rule_id, reason, severity
        return True, None, None, "info"

    def audit(self, principal_id: int | None, server_id: int | None, action: str, command: str | None, decision: str, rule_id: str | None = None, reason: str | None = None, metadata: dict[str, Any] | None = None) -> int:
        return self.db.insert("INSERT INTO audit_events(principal_id,server_id,action,command,decision,rule_id,reason,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (principal_id, server_id, action, command, decision, rule_id, reason, json.dumps(metadata or {}), utc_now()))

    def dashboard(self, principal: dict[str, Any] | None = None, is_admin: bool = False) -> dict[str, Any]:
        counts = {k: self.db.row(sql)["count"] for k, sql in {
            "principals": "SELECT count(*) AS count FROM principals",
            "servers": "SELECT count(*) AS count FROM servers",
            "rules": "SELECT count(*) AS count FROM rules WHERE enabled=1",
            "audit_events": "SELECT count(*) AS count FROM audit_events",
        }.items()}
        blocked = self.db.row("SELECT count(*) AS count FROM audit_events WHERE decision='blocked'")["count"]
        events_sql = "SELECT a.*, p.name AS principal_name, s.name AS server_name FROM audit_events a LEFT JOIN principals p ON p.id=a.principal_id LEFT JOIN servers s ON s.id=a.server_id ORDER BY a.id DESC LIMIT 8"
        if principal and not is_admin:
            events_sql = "SELECT a.*, p.name AS principal_name, s.name AS server_name FROM audit_events a LEFT JOIN principals p ON p.id=a.principal_id LEFT JOIN servers s ON s.id=a.server_id WHERE a.principal_id=? ORDER BY a.id DESC LIMIT 8"
            events = self.db.rows(events_sql, (principal["id"],))
        elif is_admin:
            events = self.db.rows(events_sql)
        else:
            events = []
        return {**counts, "blocked_commands": blocked, "executor_mode": self.settings.executor_mode, "recent_events": events}

    def dispatch(self, method: str, path: str, body: dict[str, Any], api_key: str | None, admin_key: str | None = None) -> tuple[int, dict[str, Any]]:
        self.counters["requests"] += 1
        if not isinstance(body, dict):
            return 400, {"error": "请求体必须是 JSON 对象"}
        route = urlparse(path).path
        principal = self.principal_from_key(api_key)
        is_admin = bool(admin_key and self.settings.admin_token and hmac.compare_digest(admin_key, self.settings.admin_token))
        if route == "/healthz":
            return 200, {"status": "ok"}
        if route == "/readyz":
            return 200, {"status": "ready", "db": str(self.settings.db_path), "admin_token_configured": bool(self.settings.admin_token), "executor_mode": self.settings.executor_mode}
        if route == "/api/v1/dashboard" and method == "GET":
            return 200, self.dashboard(principal, is_admin)
        if route == "/api/v1/servers" and method == "GET":
            if not principal and not is_admin:
                return 401, {"error": "查看服务器资产需要身份密钥"}
            return 200, {"items": self.visible_servers(principal["id"] if principal else None)}
        if route == "/api/v1/audit" and method == "GET":
            if not principal and not is_admin:
                return 401, {"error": "查看审计需要身份密钥或管理员令牌"}
            if is_admin:
                rows = self.db.rows("SELECT a.*, p.name AS principal_name, s.name AS server_name FROM audit_events a LEFT JOIN principals p ON p.id=a.principal_id LEFT JOIN servers s ON s.id=a.server_id ORDER BY a.id DESC LIMIT 100")
            else:
                rows = self.db.rows("SELECT a.*, p.name AS principal_name, s.name AS server_name FROM audit_events a LEFT JOIN principals p ON p.id=a.principal_id LEFT JOIN servers s ON s.id=a.server_id WHERE a.principal_id=? ORDER BY a.id DESC LIMIT 100", (principal["id"],))
            return 200, {"items": rows}
        if route == "/api/v1/rules" and method == "GET":
            return 200, {"items": self.db.rows("SELECT id,name,pattern,reason,severity,enabled,created_at FROM rules ORDER BY id")}
        if route == "/api/v1/principals" and method == "GET":
            if not is_admin:
                return 401, {"error": "身份目录需要管理员令牌"}
            return 200, {"items": self.db.rows("SELECT id,name,kind,status,created_at FROM principals ORDER BY id")}
        if route == "/api/v1/metrics" and method == "GET":
            return 200, {"items": self.counters}
        if route == "/api/v1/principals" and method == "POST":
            if not is_admin:
                return 401, {"error": "管理接口需要 X-Aegis-Admin"}
            name = body.get("name")
            kind = body.get("kind")
            if not isinstance(name, str) or not name.strip() or kind not in {"user", "ai"}:
                return 400, {"error": "name 与 kind(user|ai) 必填"}
            key = issue_api_key()
            try:
                principal_id = self.db.insert("INSERT INTO principals(name,kind,key_prefix,key_hash,created_at) VALUES(?,?,?,?,?)", (name.strip(), kind, api_key_prefix(key), hash_api_key(key), utc_now()))
            except sqlite3.IntegrityError:
                return 409, {"error": "name 已存在"}
            return 201, {"id": principal_id, "name": name.strip(), "kind": kind, "api_key": key, "warning": "密钥只在本次响应显示，请立即保存"}
        if route == "/api/v1/servers" and method == "POST":
            if not is_admin:
                return 401, {"error": "管理接口需要 X-Aegis-Admin"}
            if not isinstance(body.get("name"), str) or not body["name"].strip() or not isinstance(body.get("address"), str) or not body["address"].strip():
                return 400, {"error": "name 与 address 必填"}
            name = body["name"].strip()
            address = body["address"].strip()
            username = str(body.get("username", "")).strip()
            try:
                port = int(body.get("port", 22))
            except (ValueError, TypeError):
                return 400, {"error": "port 必须是整数"}
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,253}", address) or any(char in address for char in ("/", "\\", " ")):
                return 400, {"error": "address 只能是主机名或 IP，不能包含路径和空格"}
            if username and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", username):
                return 400, {"error": "username 不是有效的 Unix 用户名"}
            if not 1 <= port <= 65535:
                return 400, {"error": "port 必须在 1 到 65535 之间"}
            try:
                server_id = self.db.insert("INSERT INTO servers(name,address,environment,tags_json,username,port,known_hosts_path,credential_ref,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (name, address, body.get("environment", "production"), json.dumps(body.get("tags", [])), username, port, str(body.get("known_hosts_path", "")), str(body.get("credential_ref", "")), utc_now()))
            except sqlite3.IntegrityError:
                return 409, {"error": "name 已存在"}
            return 201, {"id": server_id, "name": name}
        if route == "/api/v1/access-grants" and method == "POST":
            if not is_admin:
                return 401, {"error": "管理接口需要 X-Aegis-Admin"}
            principal_id = body.get("principal_id")
            server_id = body.get("server_id")
            if isinstance(principal_id, bool) or not isinstance(principal_id, int) or isinstance(server_id, bool) or not isinstance(server_id, int):
                return 400, {"error": "principal_id 与 server_id 必须是整数"}
            if principal_id <= 0 or server_id <= 0:
                return 400, {"error": "principal_id 与 server_id 必填"}
            actions = body.get("actions", ["read"])
            if not isinstance(actions, list) or not actions or any(not isinstance(action, str) or action not in {"read", "execute", "admin"} for action in actions):
                return 400, {"error": "actions 必须是 read、execute 或 admin 的非空数组"}
            if not self.db.row("SELECT id FROM principals WHERE id=?", (principal_id,)):
                return 404, {"error": "身份不存在"}
            if not self.db.row("SELECT id FROM servers WHERE id=?", (server_id,)):
                return 404, {"error": "服务器不存在"}
            try:
                self.db.insert("INSERT OR REPLACE INTO access_grants(principal_id,server_id,actions_json) VALUES(?,?,?)", (principal_id, server_id, json.dumps(actions)))
            except sqlite3.IntegrityError:
                return 404, {"error": "身份或服务器不存在"}
            return 201, {"status": "granted"}
        if route == "/api/v1/rules" and method == "POST":
            if not is_admin:
                return 401, {"error": "管理接口需要 X-Aegis-Admin"}
            required = [body.get(k) for k in ("id", "name", "pattern", "reason")]
            if not all(isinstance(value, str) and value.strip() for value in required):
                return 400, {"error": "id/name/pattern/reason 必填"}
            try:
                compile_rule_pattern(body["pattern"])
            except RegexValidationError as exc:
                return 400, {"error": str(exc)}
            enabled_count = self.db.row("SELECT count(*) AS count FROM rules WHERE enabled=1")["count"]
            if enabled_count >= MAX_ENABLED_RULES:
                return 400, {"error": f"启用规则数量不能超过 {MAX_ENABLED_RULES}"}
            try:
                self.db.insert("INSERT INTO rules(id,name,pattern,reason,severity,created_at) VALUES(?,?,?,?,?,?)", (body["id"], body["name"], body["pattern"], body["reason"], body.get("severity", "critical"), utc_now()))
            except sqlite3.IntegrityError:
                return 409, {"error": "id 已存在"}
            self.refresh_rules()
            return 201, {"id": body["id"]}
        if route == "/api/v1/execute" and method == "POST":
            self.counters["commands"] += 1
            if not principal:
                return 401, {"error": "需要在 Authorization 或 X-Aegis-Key 提供密钥"}
            server_id = body.get("server_id")
            if isinstance(server_id, bool) or not isinstance(server_id, int):
                return 400, {"error": "server_id 必须是整数"}
            raw_command = body.get("command")
            if not isinstance(raw_command, str):
                return 400, {"error": "command 必须是字符串"}
            command = raw_command.strip()
            if not command or len(command) > 4096:
                return 400, {"error": "command 必填且长度不能超过 4096"}
            server = self.db.row("SELECT * FROM servers WHERE id=?", (server_id,))
            if not server:
                return 404, {"error": "服务器不存在"}
            grant = self.db.row("SELECT * FROM access_grants WHERE principal_id=? AND server_id=?", (principal["id"], server_id))
            if not grant:
                event_id = self.audit(principal["id"], server_id, "execute", body.get("command"), "blocked", reason="身份没有该服务器的访问权限")
                self.counters["blocked"] += 1
                return 403, {"error": "身份没有该服务器的访问权限", "audit_id": event_id}
            actions = json.loads(grant.get("actions_json") or "[]")
            if "execute" not in actions and "admin" not in actions:
                event_id = self.audit(principal["id"], server_id, "execute", body.get("command"), "blocked", reason="授权不允许执行命令", metadata={"actions": actions})
                self.counters["blocked"] += 1
                return 403, {"error": "授权不允许执行命令", "audit_id": event_id}
            allowed, rule_id, reason, severity = self.evaluate(command)
            if not allowed:
                event_id = self.audit(principal["id"], server_id, "execute", command, "blocked", rule_id, reason, {"severity": severity})
                self.counters["blocked"] += 1
                results = self.notifier.send("Aegis 规则阻断", f"身份={principal['name']} 服务器={server['name']} 规则={rule_id} 命令={command[:200]}")
                self.counters["alerts"] += sum(1 for r in results if r.delivered)
                return 403, {"error": "命令被规则阻断", "rule_id": rule_id, "reason": reason, "audit_id": event_id}
            execution_id = uuid.uuid4().hex
            event_id = self.audit(principal["id"], server_id, "execute", command, "allowed", metadata={"mode": self.settings.executor_mode, "execution_id": execution_id})
            result = self.executor.execute(server, command)
            result_event_id = self.audit(principal["id"], server_id, "execute_result", command, result.status, metadata={"mode": result.mode, "execution_id": execution_id, "intent_audit_id": event_id})
            return 200, {"status": result.status, "mode": result.mode, "server": server["name"], "command": command, "audit_id": event_id, "result_audit_id": result_event_id, "execution_id": execution_id, "message": "已通过规则评估并交给执行器", "output": result.output}
        return 404, {"error": "未找到接口"}


def create_handler(service: AegisService, static_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Aegis/0.1"

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(encoded)

        def _text(self, status: int, content: str, content_type: str = "text/plain; version=0.0.4") -> None:
            encoded = content.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("请求体过大")
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode() or "{}")
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            return payload

        def _key(self) -> str | None:
            return self.headers.get("X-Aegis-Key") or self.headers.get("Authorization", "").removeprefix("Bearer ").strip() or None

        def _admin(self) -> str | None:
            return self.headers.get("X-Aegis-Admin")

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Aegis-Key, X-Aegis-Admin")
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/" or path == "/index.html":
                data = (static_dir / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if path.startswith("/static/") or path in {"/styles.css", "/app.js"}:
                relative = path.removeprefix("/static/") if path.startswith("/static/") else path.removeprefix("/")
                file = static_dir / relative
                if file.is_file() and static_dir in file.resolve().parents:
                    data = file.read_bytes()
                    content_type = "text/css" if file.suffix == ".css" else "application/javascript"
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            if path == "/metrics":
                lines = [
                    "# HELP aegis_requests_total HTTP requests received by Aegis.",
                    "# TYPE aegis_requests_total counter",
                    f"aegis_requests_total {service.counters['requests']}",
                    "# HELP aegis_commands_total Command execution requests.",
                    "# TYPE aegis_commands_total counter",
                    f"aegis_commands_total {service.counters['commands']}",
                    "# HELP aegis_blocked_commands_total Commands stopped by scope or policy.",
                    "# TYPE aegis_blocked_commands_total counter",
                    f"aegis_blocked_commands_total {service.counters['blocked']}",
                    "# HELP aegis_alerts_delivered_total Delivered webhook alerts.",
                    "# TYPE aegis_alerts_delivered_total counter",
                    f"aegis_alerts_delivered_total {service.counters['alerts']}",
                ]
                self._text(200, "\n".join(lines) + "\n")
                return
            status, payload = service.dispatch("GET", self.path, {}, self._key(), self._admin())
            self._json(status, payload)

        def do_POST(self) -> None:  # noqa: N802
            try:
                body = self._body()
                status, payload = service.dispatch("POST", self.path, body, self._key(), self._admin())
            except (ValueError, json.JSONDecodeError) as exc:
                status, payload = 400, {"error": str(exc)}
            self._json(status, payload)

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def serve(settings: Settings) -> None:
    service = AegisService(settings)
    static_dir = Path(__file__).resolve().parent.parent / "static"
    httpd = ThreadingHTTPServer((settings.host, settings.port), create_handler(service, static_dir))
    print(f"Aegis listening on http://{settings.host}:{settings.port}", flush=True)
    httpd.serve_forever()
