"""省份巡检脚本：三态判断与写回口径（不打真实网络）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from tools import audit_provinces as audit  # noqa: E402


class VerdictRules(unittest.TestCase):
    def test_transport_failure_is_unusable(self) -> None:
        self.assertEqual(audit._verdict({"ok": False, "error": "403 Forbidden"}), "unusable")
        self.assertEqual(audit._verdict({"ok": True, "error": "connect timeout"}), "unusable")

    def test_ok_with_items_is_usable(self) -> None:
        self.assertEqual(audit._verdict({"ok": True, "created": 2, "updated": 0}), "usable")

    def test_ok_without_items_is_inconclusive(self) -> None:
        """今天没新公告不等于源不可用，不能因此把可用源标成 false。"""
        self.assertEqual(audit._verdict({"ok": True, "created": 0, "updated": 0, "skipped": 0}),
                         "inconclusive")

    def test_reason_maps_common_failures_to_actions(self) -> None:
        self.assertIn("403", audit._reason({"ok": False, "error": "HTTPStatusError 403 Forbidden"}))
        self.assertIn("404", audit._reason({"ok": False, "error": "404 Not Found"}))
        self.assertIn("证书", audit._reason({"ok": False, "error": "SSL: CERTIFICATE_VERIFY_FAILED"}))
        self.assertIn("导航页", audit._reason({"ok": True, "created": 0, "updated": 0, "skipped": 3}))
        self.assertEqual(audit._reason({"ok": True, "created": 1, "updated": 0, "skipped": 0}), "")


class WriteBack(unittest.TestCase):
    def test_only_verified_and_note_are_touched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "province_sources.json"
            path.write_text(json.dumps({"provinces": [
                {"code": "11", "name": "北京", "url": "https://a.example/", "verified": False},
                {"code": "12", "name": "天津", "url": "https://b.example/", "verified": True},
                {"code": "13", "name": "河北", "url": "https://c.example/", "verified": True},
                {"code": "14", "name": "山西", "url": "https://d.example/", "verified": True, "note": "旧备注"},
            ]}, ensure_ascii=False), encoding="utf-8")
            reports = [
                {"code": "11", "ok": True, "created": 3, "updated": 0, "reason": "", "verdict": "usable"},
                {"code": "12", "ok": True, "created": 0, "updated": 0, "reason": "", "verdict": "inconclusive"},
                {"code": "13", "ok": False, "created": 0, "updated": 0,
                 "reason": "站点返回 412（反爬校验），需人工确认可用地址", "verdict": "unusable"},
                {"code": "14", "ok": True, "created": 0, "updated": 2, "reason": "", "verdict": "usable"},
            ]
            written = audit.write_back(reports, path)
            data = json.loads(written.read_text(encoding="utf-8"))
            items = {item["code"]: item for item in data["provinces"]}
            self.assertTrue(items["11"]["verified"], "抓到公告要标可用")
            self.assertNotIn("note", items["11"])
            self.assertTrue(items["12"]["verified"], "判不出来时保留原状态")
            self.assertIn("没有新公告", items["12"]["note"])
            self.assertFalse(items["13"]["verified"], "抓不到要标不可用")
            self.assertIn("412", items["13"]["note"])
            self.assertTrue(items["14"]["verified"])
            self.assertNotIn("note", items["14"], "可用时清掉旧备注")
            self.assertEqual(items["11"]["url"], "https://a.example/", "地址不能被改写")


if __name__ == "__main__":
    unittest.main()
