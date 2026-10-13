import json
import os
import tempfile
import unittest
from pathlib import Path

from app.config import Settings, load_settings
from app.executor import SSHExecutor
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
            (root / ".env").write_text("AEGIS_ADMIN_TOKEN=from-dotenv\nAEGIS_DATA_DIR=./local-data\n", encoding="utf-8")
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

    def test_admin_token_required_for_control_plane_writes(self):
        status, response = self.service.dispatch("POST", "/api/v1/principals", {"name": "blocked", "kind": "ai"}, None)
        self.assertEqual(status, 401)
        self.assertIn("X-Aegis-Admin", response["error"])


if __name__ == "__main__":
    unittest.main()
