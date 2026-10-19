import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.config import Settings, load_settings
from app.db import Database
from app.executor import SSHExecutor
from app.rules import CommandAllowlist, CommandValidationError, MAX_ENABLED_RULES, MAX_RULE_PATTERN_LENGTH, built_in_rules, compile_rule_pattern
from app.server import AegisService
from app.security import hash_api_key, verify_api_key


class AegisCoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        settings = Settings(root, root / "aegis.db", "127.0.0.1", 0, False, None, None, None, "test-admin", "dry-run", 1.0)
        self.service = AegisService(settings)

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_default_data_dir_is_writable_project_relative_path(self):
        previous = os.environ.pop("AEGIS_DATA_DIR", None)
        previous_cwd = Path.cwd()
        temporary = tempfile.TemporaryDirectory()
        temporary_cwd = temporary.name
        try:
            os.chdir(temporary_cwd)
            settings = load_settings()
            self.assertEqual(settings.data_dir.resolve(), (Path(temporary_cwd) / "data").resolve())
            self.assertEqual(settings.db_path.resolve(), (Path(temporary_cwd) / "data" / "aegis.db").resolve())
        finally:
            os.chdir(previous_cwd)
            temporary.cleanup()
            if previous is not None:
                os.environ["AEGIS_DATA_DIR"] = previous

    def test_dotenv_is_loaded_for_local_startup(self):
        previous_env = os.environ.copy()
        previous_cwd = Path.cwd()
        temporary = tempfile.TemporaryDirectory()
        try:
            root = Path(temporary.name)
            (root / ".env").write_text("export AEGIS_ADMIN_TOKEN=from-dotenv # local\nAEGIS_DATA_DIR=./local-data\n", encoding="utf-8")
            os.chdir(root)
            os.environ.pop("AEGIS_ADMIN_TOKEN", None)
            os.environ.pop("AEGIS_DATA_DIR", None)
            settings = load_settings()
            self.assertEqual(settings.admin_token, "from-dotenv")
            self.assertEqual(settings.data_dir, (root / "local-data").resolve())
        finally:
            os.chdir(previous_cwd)
            os.environ.clear()
            os.environ.update(previous_env)
            temporary.cleanup()

    def test_key_hash_is_verifiable_but_not_plaintext(self):
        key = "aegis_secret"
        encoded = hash_api_key(key)
        self.assertNotIn(key, encoded)
        self.assertTrue(verify_api_key(key, encoded))
        self.assertFalse(verify_api_key("aegis_other", encoded))

    def test_login_session_lifecycle_and_secret_storage(self):
        root = Path(self.tmp.name) / "auth"
        settings = Settings(root, root / "aegis.db", "127.0.0.1", 0, False, None, None, None, "test-admin", "dry-run", 1.0, auth_username="admin", auth_password="correct-password")
        service = AegisService(settings)

        status, response = service.dispatch("POST", "/api/v1/auth/login", {"username": "admin", "password": "wrong"}, None)
        self.assertEqual(status, 401)
        self.assertNotIn("__session_token", response)

        status, response = service.dispatch("POST", "/api/v1/auth/login", {"username": "admin", "password": "correct-password"}, None)
        self.assertEqual(status, 200)
        token = response["__session_token"]
        self.assertNotIn(token, service.db.row("SELECT token_hash FROM sessions")['token_hash'])
        self.assertNotIn("correct-password", service.db.row("SELECT password_hash FROM users")['password_hash'])

        status, current = service.dispatch("GET", "/api/v1/auth/me", {}, None, None, token)
        self.assertEqual(status, 200)
        self.assertEqual(current["user"]["username"], "admin")
        status, created = service.dispatch("POST", "/api/v1/principals", {"name": "session-admin", "kind": "user"}, None, None, token)
        self.assertEqual(status, 201)
        self.assertEqual(created["name"], "session-admin")

        service.dispatch("POST", "/api/v1/auth/logout", {}, None, None, token)
        status, response = service.dispatch("GET", "/api/v1/auth/me", {}, None, None, token)
        self.assertEqual(status, 401)

    def test_bootstrap_login_does_not_overwrite_existing_password(self):
        root = Path(self.tmp.name) / "bootstrap"
        first = Settings(root, root / "aegis.db", "127.0.0.1", 0, False, None, None, None, "test-admin", "dry-run", 1.0, auth_username="admin", auth_password="first-password")
        AegisService(first)
        second = Settings(root, root / "aegis.db", "127.0.0.1", 0, False, None, None, None, "test-admin", "dry-run", 1.0, auth_username="admin", auth_password="second-password")
        service = AegisService(second)
        self.assertEqual(service.dispatch("POST", "/api/v1/auth/login", {"username": "admin", "password": "first-password"}, None)[0], 200)
        self.assertEqual(service.dispatch("POST", "/api/v1/auth/login", {"username": "admin", "password": "second-password"}, None)[0], 401)

    def test_new_principal_stores_only_a_lookup_prefix(self):
        status, created = self.service.dispatch(
            "POST", "/api/v1/principals", {"name": "prefix-agent", "kind": "ai"}, None, "test-admin"
        )
        self.assertEqual(status, 201)
        stored = self.service.db.row("SELECT key_prefix,key_hash FROM principals WHERE id=?", (created["id"],))
        self.assertIsNotNone(stored)
        self.assertEqual(stored["key_prefix"], created["api_key"][:22])
        self.assertNotIn(created["api_key"], stored["key_hash"])
        self.assertEqual(self.service.principal_from_key(created["api_key"])["id"], created["id"])

    def test_database_migration_adds_lookup_prefix_to_existing_principals(self):
        legacy_path = Path(self.tmp.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                """
                CREATE TABLE principals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL CHECK(kind IN ('user','ai')),
                    key_hash TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                )
                """
            )

        database = Database(legacy_path)
        columns = {row["name"] for row in database.rows("PRAGMA table_info(principals)")}
        self.assertIn("key_prefix", columns)

    def test_rule_blocks_command_and_writes_audit(self):
        status, created = self.service.dispatch("POST", "/api/v1/principals", {"name": "agent-1", "kind": "ai"}, None, "test-admin")
        self.assertEqual(status, 201)
        key = created["api_key"]
        status, server = self.service.dispatch("POST", "/api/v1/servers", {"name": "test", "address": "10.0.0.1"}, None, "test-admin")
        self.assertEqual(status, 201)
        self.service.dispatch("POST", "/api/v1/access-grants", {"principal_id": created["id"], "server_id": server["id"], "actions": ["execute"]}, None, "test-admin")
        status, response = self.service.dispatch("POST", "/api/v1/execute", {"server_id": server["id"], "command": "rm -rf /"}, key)
        self.assertEqual(status, 403)
        self.assertEqual(response["rule_id"], "dangerous-filesystem")
        events = self.service.db.rows("SELECT * FROM audit_events")
        self.assertEqual(events[-1]["decision"], "blocked")

        status, response = self.service.dispatch("POST", "/api/v1/execute", {"server_id": server["id"], "command": "uname -a"}, key)
        self.assertEqual(status, 200)
        self.assertIn("result_audit_id", response)
        self.assertEqual(self.service.db.row("SELECT action FROM audit_events ORDER BY id DESC LIMIT 1")["action"], "execute_result")

    def test_scope_blocks_unlisted_server(self):
        status, principal = self.service.dispatch("POST", "/api/v1/principals", {"name": "user-1", "kind": "user"}, None, "test-admin")
        status, server = self.service.dispatch("POST", "/api/v1/servers", {"name": "private", "address": "10.0.0.2"}, None, "test-admin")
        status, response = self.service.dispatch("POST", "/api/v1/execute", {"server_id": server["id"], "command": "ls"}, principal["api_key"])
        self.assertEqual(status, 403)
        self.assertIn("访问权限", response["error"])

    def test_dashboard_shape(self):
        status, dashboard = self.service.dispatch("GET", "/api/v1/dashboard", {}, None)
        self.assertEqual(status, 200)
        self.assertIn("recent_events", dashboard)

    def test_server_inventory_requires_identity_scope(self):
        status, response = self.service.dispatch("GET", "/api/v1/servers", {}, None)
        self.assertEqual(status, 401)
        self.assertIn("身份密钥", response["error"])

    def test_server_registration_keeps_connection_fields_private(self):
        status, created = self.service.dispatch("POST", "/api/v1/servers", {"name": "ssh-host", "address": "node.example", "username": "ops", "port": 2201, "known_hosts_path": "/tmp/known_hosts", "credential_ref": "secret://node"}, None, "test-admin")
        self.assertEqual(status, 201)
        status, response = self.service.dispatch("GET", "/api/v1/servers", {}, None, "test-admin")
        self.assertEqual(status, 200)
        server = next(item for item in response["items"] if item["id"] == created["id"])
        self.assertEqual(server["port"], 2201)
        self.assertNotIn("credential_ref", server)
        self.assertNotIn("known_hosts_path", server)

    def test_read_only_grant_cannot_execute(self):
        _, principal = self.service.dispatch("POST", "/api/v1/principals", {"name": "read-only", "kind": "user"}, None, "test-admin")
        _, server = self.service.dispatch("POST", "/api/v1/servers", {"name": "read-only-host", "address": "10.0.0.8"}, None, "test-admin")
        self.service.dispatch("POST", "/api/v1/access-grants", {"principal_id": principal["id"], "server_id": server["id"], "actions": ["read"]}, None, "test-admin")
        status, response = self.service.dispatch("POST", "/api/v1/execute", {"server_id": server["id"], "command": "ls"}, principal["api_key"])
        self.assertEqual(status, 403)
        self.assertIn("不允许执行", response["error"])

    def test_ssh_executor_fails_closed_without_asset_identity(self):
        result = SSHExecutor(0.1).execute({"name": "missing"}, "id")
        self.assertEqual(result.status, "failed")

    def test_command_allowlist_rejects_shell_syntax_and_unknown_commands(self):
        allowlist = CommandAllowlist()
        self.assertEqual(allowlist.parse("uname -a"), ("uname", "-a"))
        for command in ("uname -a; id", "uname $(id)", "ls /tmp/*", "cat /etc/passwd", "bash -c id", "/bin/sh -c id"):
            with self.assertRaises(CommandValidationError):
                allowlist.parse(command)

    def test_command_allowlist_can_be_extended_with_explicit_command_names(self):
        allowlist = CommandAllowlist(frozenset({"kubectl"}))
        self.assertEqual(allowlist.parse("kubectl get pods --namespace=ops"), ("kubectl", "get", "pods", "--namespace=ops"))
        with self.assertRaises(CommandValidationError):
            CommandAllowlist(frozenset({"bash"})).parse("bash -c id")

    def test_execute_blocks_command_outside_allowlist_and_audits_it(self):
        _, principal = self.service.dispatch("POST", "/api/v1/principals", {"name": "allowlist-agent", "kind": "ai"}, None, "test-admin")
        _, server = self.service.dispatch("POST", "/api/v1/servers", {"name": "allowlist-host", "address": "10.0.0.11"}, None, "test-admin")
        self.service.dispatch("POST", "/api/v1/access-grants", {"principal_id": principal["id"], "server_id": server["id"], "actions": ["execute"]}, None, "test-admin")
        status, response = self.service.dispatch("POST", "/api/v1/execute", {"server_id": server["id"], "command": "cat /etc/passwd"}, principal["api_key"])
        self.assertEqual(status, 403)
        self.assertEqual(response["rule_id"], "__command_allowlist__")
        self.assertEqual(self.service.db.row("SELECT decision FROM audit_events ORDER BY id DESC LIMIT 1")["decision"], "blocked")

    def test_admin_token_required_for_control_plane_writes(self):
        status, response = self.service.dispatch("POST", "/api/v1/principals", {"name": "blocked", "kind": "ai"}, None)
        self.assertEqual(status, 401)
        self.assertIn("X-Aegis-Admin", response["error"])

    def test_dispatch_rejects_non_object_request_body(self):
        status, response = self.service.dispatch("POST", "/api/v1/principals", [], None, "test-admin")
        self.assertEqual(status, 400)
        self.assertEqual(response["error"], "请求体必须是 JSON 对象")

    def test_access_grant_validates_ids_and_actions(self):
        status, response = self.service.dispatch(
            "POST",
            "/api/v1/access-grants",
            {"principal_id": "invalid", "server_id": 1},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("必须是整数", response["error"])

        status, response = self.service.dispatch(
            "POST",
            "/api/v1/access-grants",
            {"principal_id": 999, "server_id": 999},
            None,
            "test-admin",
        )
        self.assertEqual(status, 404)
        self.assertIn("身份不存在", response["error"])

        _, principal = self.service.dispatch(
            "POST", "/api/v1/principals", {"name": "grant-test", "kind": "user"}, None, "test-admin"
        )
        _, server = self.service.dispatch(
            "POST", "/api/v1/servers", {"name": "grant-test", "address": "10.0.0.9"}, None, "test-admin"
        )
        status, response = self.service.dispatch(
            "POST",
            "/api/v1/access-grants",
            {"principal_id": principal["id"], "server_id": server["id"], "actions": "execute"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("actions", response["error"])

    def test_duplicate_rule_returns_conflict(self):
        duplicate = {
            "id": "dangerous-filesystem",
            "name": "duplicate",
            "pattern": "duplicate",
            "reason": "duplicate",
        }
        status, response = self.service.dispatch("POST", "/api/v1/rules", duplicate, None, "test-admin")
        self.assertEqual(status, 409)
        self.assertEqual(response["error"], "id 已存在")

    def test_rule_rejects_non_string_pattern(self):
        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "invalid-pattern", "name": "invalid", "pattern": [], "reason": "invalid"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("pattern", response["error"])

    def test_new_rule_is_used_without_restarting_service(self):
        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "deny-echo", "name": "禁止 echo", "pattern": r"\becho\b", "reason": "测试规则"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 201)

        _, principal = self.service.dispatch(
            "POST", "/api/v1/principals", {"name": "rule-test", "kind": "ai"}, None, "test-admin"
        )
        _, server = self.service.dispatch(
            "POST", "/api/v1/servers", {"name": "rule-test", "address": "10.0.0.10"}, None, "test-admin"
        )
        self.service.dispatch(
            "POST",
            "/api/v1/access-grants",
            {"principal_id": principal["id"], "server_id": server["id"], "actions": ["execute"]},
            None,
            "test-admin",
        )

        status, response = self.service.dispatch(
            "POST", "/api/v1/execute", {"server_id": server["id"], "command": "echo hello"}, principal["api_key"]
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["rule_id"], "deny-echo")

    def test_new_rule_is_compiled_once_and_used_for_evaluation(self):
        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "deny-test-command", "name": "测试规则", "pattern": r"\bforbidden\b", "reason": "测试阻断"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 201)
        self.assertEqual(self.service.evaluate("echo forbidden")[1:], ("deny-test-command", "测试阻断", "critical"))

    def test_new_rule_rejects_regex_backtracking_shapes(self):
        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "redos", "name": "危险正则", "pattern": r"(a+)+$", "reason": "测试"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("重复结构", response["error"])

        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "optional-loop", "name": "可空重复", "pattern": r"(a?)*b", "reason": "测试"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("重复结构", response["error"])

        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "ambiguous", "name": "歧义正则", "pattern": r"(a|aa)+$", "reason": "测试"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("重复结构", response["error"])

        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "backref", "name": "反向引用", "pattern": r"(a)\1", "reason": "测试"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn("反向引用", response["error"])

    def test_new_rule_rejects_oversized_pattern(self):
        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "long-pattern", "name": "超长正则", "pattern": "a" * (MAX_RULE_PATTERN_LENGTH + 1), "reason": "测试"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn(str(MAX_RULE_PATTERN_LENGTH), response["error"])

    def test_new_rule_rejects_excessive_enabled_rule_count(self):
        with self.service.db.connect() as connection:
            connection.executemany(
                "INSERT INTO rules(id,name,pattern,reason,severity,created_at) VALUES(?,?,?,?,?,?)",
                [
                    (f"limit-{index}", "数量上限", "safe", "测试", "critical", "now")
                    for index in range(MAX_ENABLED_RULES)
                ],
            )
        status, response = self.service.dispatch(
            "POST",
            "/api/v1/rules",
            {"id": "over-limit", "name": "超出上限", "pattern": "safe", "reason": "测试"},
            None,
            "test-admin",
        )
        self.assertEqual(status, 400)
        self.assertIn(str(MAX_ENABLED_RULES), response["error"])

    def test_built_in_rules_pass_regex_safety_validation(self):
        for rule in built_in_rules():
            compile_rule_pattern(rule.pattern)

    def test_invalid_enabled_legacy_rule_fails_closed(self):
        self.service.db.insert(
            "INSERT INTO rules(id,name,pattern,reason,severity,created_at) VALUES(?,?,?,?,?,?)",
            ("legacy-redos", "旧危险正则", r"(a+)+$", "测试", "critical", "now"),
        )
        self.service.refresh_rules()
        allowed, rule_id, reason, severity = self.service.evaluate("uname -a")
        self.assertFalse(allowed)
        self.assertEqual(rule_id, "__rules_invalid__")
        self.assertIn("legacy-redos", reason)
        self.assertEqual(severity, "critical")
        status, response = self.service.dispatch("GET", "/readyz", {}, None)
        self.assertEqual(status, 503)
        self.assertEqual(response["status"], "not_ready")


if __name__ == "__main__":
    unittest.main()
