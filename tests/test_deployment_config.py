"""部署配置合约：隔离环境和临时配置，不读取真实密钥。"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import config


class DeploymentConfigTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="jobagent-config-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.backend = self.root / "backend"
        self.cwd = self.root / "cwd"
        self.backend.mkdir()
        self.cwd.mkdir()
        for mocked in (
            patch.dict(os.environ, {}, clear=True),
            patch.object(config, "BACKEND_ROOT", self.backend),
            patch.object(config, "PROJECT_ROOT", self.root),
            patch("core.config.os.getcwd", return_value=str(self.cwd)),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)
        config.settings.cache_clear()
        self.addCleanup(config.settings.cache_clear)

    def write_env(self, path, content):
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_explicit_file_and_process_environment_priority(self):
        self.write_env(self.backend / ".env", "MODEL=wrong-local\n")
        os.environ["JOBAGENT_ENV_FILE"] = self.write_env(
            self.root / "server.env",
            'MODEL="server-model"\nOPENAI_API_KEY="synthetic # key"\nJOBAGENT_PORT=8123\nJOBAGENT_HOST=0.0.0.0\n',
        )
        os.environ["MODEL"] = "process-model"
        settings = config.settings()
        self.assertEqual(settings["model"], "process-model")
        self.assertEqual(settings["api_key"], "synthetic # key")
        self.assertEqual(settings["host"], "0.0.0.0")
        self.assertEqual(settings["port"], 8123)

    def test_explicit_missing_file_does_not_fall_back(self):
        self.write_env(self.backend / ".env", "MODEL=wrong-local\n")
        os.environ["JOBAGENT_ENV_FILE"] = str(self.root / "missing.env")
        with self.assertRaises(FileNotFoundError):
            config.settings()
        self.assertNotIn("MODEL", os.environ)

    def test_explicit_unreadable_file_does_not_fall_back(self):
        os.environ["JOBAGENT_ENV_FILE"] = self.write_env(self.root / "server.env", "MODEL=server\n")
        with patch.object(Path, "open", side_effect=PermissionError("permission denied")):
            with self.assertRaises(PermissionError):
                config.settings()
        self.assertNotIn("MODEL", os.environ)

    def test_explicit_directory_is_rejected(self):
        os.environ["JOBAGENT_ENV_FILE"] = str(self.root)
        with self.assertRaises(OSError):
            config.settings()

    def test_default_search_order(self):
        paths = [self.backend / ".env", self.cwd / ".env", self.root / ".env"]
        for index, path in enumerate(paths):
            self.write_env(path, f"MODEL=source-{index}\n")
        for index, path in enumerate(paths):
            with self.subTest(source=index):
                os.environ.pop("MODEL", None)
                config.settings.cache_clear()
                self.assertEqual(config.settings()["model"], f"source-{index}")
                path.unlink()

    def test_defaults_without_config_file(self):
        settings = config.settings()
        self.assertEqual(settings["host"], "127.0.0.1")
        self.assertEqual(settings["port"], 8000)
        self.assertEqual(settings["api_key"], "")

    def test_invalid_ports_are_rejected(self):
        for port in ("0", "-1", "65536", "not-a-port"):
            with self.subTest(port=port):
                os.environ["JOBAGENT_PORT"] = port
                config.settings.cache_clear()
                with self.assertRaisesRegex(ValueError, "JOBAGENT_PORT"):
                    config.settings()

    def test_port_boundaries(self):
        for port in (1, 65535):
            with self.subTest(port=port):
                os.environ["JOBAGENT_PORT"] = str(port)
                config.settings.cache_clear()
                self.assertEqual(config.settings()["port"], port)


if __name__ == "__main__":
    unittest.main()
