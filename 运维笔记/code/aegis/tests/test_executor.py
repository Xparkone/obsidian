import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.executor import CredentialProviderError, SecretDirectoryCredentialProvider, SSHExecutor


class CredentialIsolationTest(unittest.TestCase):
    def test_ssh_fails_closed_without_a_controlled_credential_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            known_hosts = root / "known_hosts"
            known_hosts.write_text("host ssh-ed25519 key\n", encoding="utf-8")
            result = SSHExecutor(1.0).execute(
                {
                    "name": "node",
                    "username": "ops",
                    "address": "node.example",
                    "port": 22,
                    "known_hosts_path": str(known_hosts),
                    "credential_ref": "secret://node",
                },
                "id",
            )
        self.assertEqual(result.status, "failed")
        self.assertIn("凭据提供器", result.output)

    def test_secret_directory_rejects_traversal_and_insecure_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "node"
            key.write_text("private-key-placeholder\n", encoding="utf-8")
            key.chmod(stat.S_IRUSR | stat.S_IWUSR)
            provider = SecretDirectoryCredentialProvider(root)
            self.assertEqual(provider.resolve("secret://node").identity_file, key.resolve())
            with self.assertRaises(CredentialProviderError):
                provider.resolve("secret://../node")
            with self.assertRaises(CredentialProviderError):
                provider.resolve("secret://sub/../node")
            key.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
            with self.assertRaises(CredentialProviderError):
                provider.resolve("secret://node")

    def test_ssh_uses_only_the_resolved_identity_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "node"
            key.write_text("private-key-placeholder\n", encoding="utf-8")
            key.chmod(stat.S_IRUSR | stat.S_IWUSR)
            known_hosts = root / "known_hosts"
            known_hosts.write_text("host ssh-ed25519 key\n", encoding="utf-8")
            provider = SecretDirectoryCredentialProvider(root)
            with patch("app.executor.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "ok\n"
                run.return_value.stderr = ""
                result = SSHExecutor(1.0, provider).execute(
                    {
                        "name": "node",
                        "username": "ops",
                        "address": "node.example",
                        "port": 22,
                        "known_hosts_path": str(known_hosts),
                        "credential_ref": "secret://node",
                    },
                    "id",
                )
        self.assertEqual(result.status, "completed")
        args = run.call_args.args[0]
        self.assertIn("-i", args)
        self.assertIn(str(key.resolve()), args)
        self.assertIn("IdentitiesOnly=yes", args)
        self.assertIn("IdentityAgent=none", args)
        self.assertIn("PasswordAuthentication=no", args)
        self.assertIn("KbdInteractiveAuthentication=no", args)


if __name__ == "__main__":
    unittest.main()
