"""简历模板库合约：静态模板可枚举、参数校验、非法模板被跳过。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from api import resume as resume_api  # noqa: E402
from core import accounts  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}
APPEARANCE_KEYS = {"template", "background", "paper", "accent", "fontSize", "spacing",
                   "headerAlign", "sidebarSide", "headerStyle", "nameColor", "headingFont"}


class ResumeTemplates(unittest.TestCase):
    def setUp(self) -> None:
        # 模板库本身是静态数据，但业务路由统一要求登录：这里覆盖依赖模拟已登录账户
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: {"id": "u-tpl", "username": "tpl"}
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app, headers=HEADER)

    def test_library_lists_valid_templates(self) -> None:
        body = self.client.get("/api/resume/templates").json()
        self.assertTrue(body["ok"])
        items = body["items"]
        self.assertGreaterEqual(len(items), 6, "模板库至少要有几个可用选项")
        for item in items:
            self.assertTrue(item["id"] and item["name"])
            self.assertEqual(set(item["appearance"]), APPEARANCE_KEYS, "下发字段必须与前端外观契约一致")
            self.assertIn(item["appearance"]["template"], ("classic", "sidebar", "compact"))
            for key in ("background", "paper", "accent"):
                self.assertRegex(item["appearance"][key], r"^#[0-9A-Fa-f]{6}$")
            self.assertIn(item["appearance"]["fontSize"], (13, 14, 16))
            self.assertIn(item["appearance"]["spacing"], (1.35, 1.6, 1.85))

    def test_templates_do_not_carry_resume_content(self) -> None:
        raw = self.client.get("/api/resume/templates").text
        for forbidden in ("markdown", "content_md", "experiences", "联系电话"):
            self.assertNotIn(forbidden, raw, "模板库不得携带任何简历正文或个人资料")

    def test_broken_entries_are_skipped_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "templates.json"
            path.write_text(json.dumps({
                "version": 1,
                "templates": [
                    {"id": "ok", "name": "正常模板", "appearance": {
                        "template": "classic", "background": "#ffffff", "paper": "#ffffff",
                        "accent": "#254264", "fontSize": 14, "spacing": 1.6}},
                    {"id": "bad-color", "name": "坏颜色", "appearance": {
                        "template": "classic", "background": "white", "paper": "#ffffff",
                        "accent": "#254264", "fontSize": 14, "spacing": 1.6}},
                    {"id": "bad-template", "name": "坏布局", "appearance": {
                        "template": "fancy", "background": "#ffffff", "paper": "#ffffff",
                        "accent": "#254264", "fontSize": 14, "spacing": 1.6}},
                    {"id": "no-appearance", "name": "缺参数"},
                    "not-a-dict",
                ],
            }, ensure_ascii=False), encoding="utf-8")
            with patch.object(resume_api, "_template_path", return_value=path):
                body = self.client.get("/api/resume/templates").json()
        self.assertEqual([item["id"] for item in body["items"]], ["ok"],
                         "单条不合规只能跳过自己，不能拖垮整个模板库")

    def test_missing_or_corrupt_file_degrades_gracefully(self) -> None:
        missing = Path(tempfile.gettempdir()) / "jobagent-no-such-templates.json"
        with patch.object(resume_api, "_template_path", return_value=missing):
            body = self.client.get("/api/resume/templates").json()
        self.assertEqual(body["items"], [])
        self.assertIn("模板库文件缺失", body["note"])

        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / "templates.json"
            broken.write_text("{not json", encoding="utf-8")
            with patch.object(resume_api, "_template_path", return_value=broken):
                body = self.client.get("/api/resume/templates").json()
        self.assertEqual(body["items"], [])
        self.assertIn("无法解析", body["note"])


if __name__ == "__main__":
    unittest.main()
