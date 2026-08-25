from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.config import Settings


class SettingsTests(unittest.TestCase):
    def test_deployment_identity_defaults_and_environment_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            defaults = Settings.from_env({}, root_dir=root)
            configured = Settings.from_env(
                {"APP_SLOT": "slot-b-canary", "BUILD_ID": "build-20260825.1"},
                root_dir=root,
            )
        self.assertEqual("slot-b", defaults.slot)
        self.assertEqual("development", defaults.build_id)
        self.assertEqual("slot-b-canary", configured.slot)
        self.assertEqual("build-20260825.1", configured.build_id)

    def test_unconfigured_capabilities_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings.from_env({}, root_dir=Path(temporary))
        status = settings.capabilities["vision_analyze"].public_status()
        self.assertFalse(status["configured"])
        self.assertEqual("CAPABILITY_NOT_CONFIGURED", status["error_code"])

    def test_capability_and_skill_environment_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {
                "VISION_ANALYZE_API_BASE_URL": "http://127.0.0.1:8103/v1/",
                "VISION_ANALYZE_API_MODEL": "vision-model",
                "HARNESS_SKILL_DIRS": os.pathsep.join(["skills-a", "skills-b"]),
                "PORT": "9090",
            }
            settings = Settings.from_env(env, root_dir=root)
        capability = settings.capabilities["vision_analyze"]
        self.assertEqual("http://127.0.0.1:8103/v1/chat/completions", capability.target_url)
        self.assertEqual("vision-model", capability.model)
        self.assertEqual("http://127.0.0.1:9090/mcp", settings.capability_mcp_url)
        self.assertEqual(2, len(settings.harness_skill_dirs))

    def test_default_web_search_endpoint_matches_bocha_protocol(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = Settings.from_env(
                {"WEB_SEARCH_API_BASE_URL": "https://api.bocha.cn/v1"},
                root_dir=Path(temporary),
            )
        self.assertEqual(
            "https://api.bocha.cn/v1/web-search",
            settings.capabilities["web_search"].target_url,
        )

    def test_operation_log_is_private_to_data_dir_and_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = Settings.from_env(
                {
                    "DATA_DIR": str(root / "data"),
                    "OPERATION_LOG_RETENTION_DAYS": "9",
                },
                root_dir=root,
            )
        self.assertTrue(settings.operation_log_enabled)
        self.assertEqual(9, settings.operation_log_retention_days)
        self.assertEqual(
            root / "data" / "logs" / "operations.jsonl",
            settings.operation_log_path,
        )


if __name__ == "__main__":
    unittest.main()
