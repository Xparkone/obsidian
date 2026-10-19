import json
import tempfile
import unittest
from pathlib import Path

from app.archive import JsonlAuditArchive, S3ObjectLockAuditArchive
from app.config import Settings
from app.db import PostgresDatabase
from app.server import AegisService


class AuditArchiveTest(unittest.TestCase):
    def test_jsonl_archive_is_hash_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            archive = JsonlAuditArchive(path)
            first = archive.append({"id": 1, "decision": "allowed"})
            second = archive.append({"id": 2, "decision": "blocked"})
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["record_hash"], first)
            self.assertEqual(records[1]["record_hash"], second)
            self.assertEqual(records[1]["previous_hash"], first)

    def test_postgres_sql_adapter_translates_sqlite_placeholders(self):
        statement = PostgresDatabase._sql("INSERT OR IGNORE INTO rules(id,name) VALUES(?,?)")
        self.assertIn("INSERT INTO rules", statement)
        self.assertIn("%s", statement)
        self.assertIn("ON CONFLICT DO NOTHING", statement)

    def test_service_copies_audit_event_to_configured_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "audit.jsonl"
            settings = Settings(
                root,
                root / "aegis.db",
                "127.0.0.1",
                0,
                False,
                None,
                None,
                None,
                "test-admin",
                "dry-run",
                1.0,
                audit_archive_path=archive_path,
                audit_archive_required=True,
            )
            service = AegisService(settings)
            event_id = service.audit(None, None, "test", "true", "allowed")
            record = json.loads(archive_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(record["event"]["id"], event_id)
            self.assertEqual(record["event"]["decision"], "allowed")

    def test_required_archive_without_adapter_fails_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = Settings(
                root,
                root / "aegis.db",
                "127.0.0.1",
                0,
                False,
                None,
                None,
                None,
                "test-admin",
                "dry-run",
                1.0,
                audit_archive_required=True,
            )
            with self.assertRaises(RuntimeError):
                AegisService(settings)

    def test_s3_archive_requests_compliance_object_lock(self):
        class FakeS3:
            def __init__(self):
                self.kwargs = None

            def put_object(self, **kwargs):
                self.kwargs = kwargs

        client = FakeS3()
        archive = S3ObjectLockAuditArchive("audit-bucket", client=client, retention_days=30)
        location = archive.append({"id": 7, "decision": "blocked"})
        self.assertTrue(location.startswith("s3://audit-bucket/"))
        self.assertEqual(client.kwargs["ObjectLockMode"], "COMPLIANCE")
        self.assertEqual(client.kwargs["Bucket"], "audit-bucket")
        self.assertTrue(client.kwargs["ContentMD5"])


if __name__ == "__main__":
    unittest.main()
