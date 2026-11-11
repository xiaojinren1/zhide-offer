"""岗位收件箱接口与 Agent 工具合约：临时数据库、Mock 模型，不联网。

覆盖四条边界：
- 模型解析失败仍然入库，并把原因放进 warnings
- 导入去重（同一 URL 两次只留一条）
- 账号隔离（A 的私有资料对 B 不可见）
- 工具失败以 `{"error": ...}` 返回，不把异常抛给模型
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient  # noqa: E402

from core import accounts, document_tools  # noqa: E402
from engine.sources import base as sources_base  # noqa: E402
from main import app  # noqa: E402

HEADER = {"X-Requested-With": "XMLHttpRequest"}
JD_TEXT = """数据开发工程师
某科技公司 · 上海
薪资：25-40K·14薪

岗位职责
负责数据平台建设，支撑业务报表与指标口径。

任职要求
熟悉 SQL 与数据仓库建模，了解调度系统。
"""


class JobsApiContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "jobs.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)

        with accounts.connection() as db:
            for user_id, name in (("u-alice", "alice"), ("u-bob", "bob")):
                db.execute(
                    "INSERT INTO users(id,username,password_hash,created_at) VALUES(?,?,?,0)",
                    (user_id, name, "pbkdf2_sha256$1$00$00"),
                )

        self.current_user = {"id": "u-alice", "username": "alice"}
        previous = dict(app.dependency_overrides)
        app.dependency_overrides[accounts.require_user] = lambda: self.current_user
        self.addCleanup(lambda: (app.dependency_overrides.clear(), app.dependency_overrides.update(previous)))
        self.client = TestClient(app)

    def _import(self, **overrides):
        payload = {"text": JD_TEXT, "parse": False, **overrides}
        return self.client.post("/api/jobs/import", json=payload, headers=HEADER)

    # ---- 导入 ----

    def test_import_without_model_parses_salary_from_text(self) -> None:
        response = self._import()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["created"])
        document = body["document"]
        self.assertEqual((document["salary_min"], document["salary_max"]), (25000, 40000))
        self.assertEqual(document["kind"], "job")
        self.assertEqual(document["visibility"], "private")

    def test_model_failure_still_stores_document(self) -> None:
        with patch("api.jobs.parse_jd", side_effect=RuntimeError("模型超时")):
            response = self._import(parse=True, title="数据开发工程师")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["warnings"], "解析失败必须给出提示")
        self.assertEqual(body["document"]["title"], "数据开发工程师")
        self.assertTrue(body["document"]["content_md"].startswith("数据开发工程师"))

    def test_same_url_updates_instead_of_duplicating(self) -> None:
        first = self._import(url="https://jobs.example.com/1?utm_source=x").json()
        second = self._import(url="https://jobs.example.com/1").json()
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(second["created"])
        listing = self.client.get("/api/jobs").json()
        self.assertEqual(listing["total"], 1)

    def test_blank_text_is_rejected(self) -> None:
        response = self.client.post("/api/jobs/import", json={"text": "   "}, headers=HEADER)
        self.assertEqual(response.status_code, 422)

    # ---- 读取与删除 ----

    def test_list_search_and_detail(self) -> None:
        doc_id = self._import().json()["id"]
        listing = self.client.get("/api/jobs").json()
        self.assertEqual(len(listing["items"]), 1)
        self.assertEqual(listing["items"][0]["id"], doc_id)

        found = self.client.get("/api/jobs", params={"q": "数据仓库"}).json()
        self.assertEqual(found["total"], 1)
        self.assertIn("数据仓库", found["items"][0]["matched_excerpt"])

        none = self.client.get("/api/jobs", params={"q": "核电焊工"}).json()
        self.assertEqual(none["total"], 0)

        detail = self.client.get(f"/api/jobs/{doc_id}").json()
        self.assertTrue(detail["ok"])
        self.assertTrue(detail["chunks"])
        self.assertEqual(detail["chunks"][0]["index"], 0)

    def test_delete_then_detail_is_404(self) -> None:
        doc_id = self._import().json()["id"]
        self.assertEqual(self.client.delete(f"/api/jobs/{doc_id}", headers=HEADER).status_code, 200)
        self.assertEqual(self.client.get(f"/api/jobs/{doc_id}").status_code, 404)

    # ---- 账号隔离 ----

    def test_other_account_cannot_see_private_document(self) -> None:
        doc_id = self._import().json()["id"]
        self.current_user = {"id": "u-bob", "username": "bob"}
        self.assertEqual(self.client.get(f"/api/jobs/{doc_id}").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs").json()["total"], 0)
        self.assertEqual(self.client.delete(f"/api/jobs/{doc_id}", headers=HEADER).status_code, 404)

    # ---- Agent 工具 ----

    def test_tools_search_get_and_import(self) -> None:
        executor, names = document_tools.build_executor(user_id="u-alice")
        self.assertEqual(names, ["search_jobs", "get_job", "import_document"])

        imported = executor("import_document", {"text": JD_TEXT, "title": "数据开发工程师"})
        self.assertTrue(imported["created"], imported)
        job_id = imported["job_id"]

        found = executor("search_jobs", {"query": "数据仓库"})
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["items"][0]["job_id"], job_id)

        detail = executor("get_job", {"job_id": job_id})
        self.assertIn("SQL", detail["content_md"])
        self.assertEqual(detail["title"], "数据开发工程师")

    # ---- 信源管理（管理员） ----

    def _grant_admin(self) -> None:
        with accounts.connection() as db:
            db.execute("INSERT INTO user_roles(user_id, role) VALUES(?, 'admin')", ("u-alice",))

    def test_sources_require_admin(self) -> None:
        self.assertEqual(self.client.get("/api/jobs/sources").status_code, 403)

    def test_admin_can_register_and_list_source(self) -> None:
        self._grant_admin()
        payload = {
            "id": "src-gov", "name": "某省人社厅公告", "kind": "html_list",
            "url": "https://hr.example.gov.cn/list/", "tier": 1,
            "license_note": "政府公开信息",
            "config": {"include_keywords": ["招聘", "公告"], "max_items": 5},
        }
        self.assertEqual(self.client.post("/api/jobs/sources", json=payload, headers=HEADER).status_code, 200)
        listing = self.client.get("/api/jobs/sources").json()
        self.assertEqual([item["id"] for item in listing["items"]], ["src-gov"])
        self.assertEqual(listing["items"][0]["tier"], 1)

    def test_admin_source_fetch_writes_public_jobs(self) -> None:
        self._grant_admin()
        self.client.post("/api/jobs/sources", json={
            "id": "src-gov", "name": "某省人社厅公告", "kind": "rss",
            "url": "https://hr.example.gov.cn/rss.xml", "tier": 1, "config": {},
        }, headers=HEADER)
        body = "薪资：10-15K\n" + "事业单位公开招聘公告。岗位职责：负责数据平台建设与指标口径维护。" * 4
        found = [sources_base.RawItem(url="https://hr.example.gov.cn/1.html",
                                     title="事业单位公开招聘公告", summary=body)]
        with patch("engine.sources.base.fetch_items", return_value=found):
            result = self.client.post("/api/jobs/sources/src-gov/fetch", headers=HEADER).json()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["created"], 1)
        # 采集结果进公共池：另一个账号也能看到
        self.current_user = {"id": "u-bob", "username": "bob"}
        listing = self.client.get("/api/jobs").json()
        self.assertEqual(listing["total"], 1)

    def test_source_fetch_missing_source_is_404(self) -> None:
        self._grant_admin()
        self.assertEqual(
            self.client.post("/api/jobs/sources/nope/fetch", headers=HEADER).status_code, 404)

    # ---- 粘贴识别 ----

    def test_analyze_extracts_fields_without_model(self) -> None:
        text = chr(10).join([
            "数据开发工程师",
            "20-35K·14薪",
            "北京·朝阳区 3-5年 本科",
            "某某科技有限公司",
            "职责：建设数据平台",
        ])
        response = self.client.post("/api/jobs/analyze", json={"text": text}, headers=HEADER)
        self.assertEqual(response.status_code, 200, response.text)
        guess = response.json()["guess"]
        self.assertEqual(guess["title"], "数据开发工程师")
        self.assertEqual(guess["company"], "某某科技有限公司")
        self.assertEqual(guess["city"], "北京")
        self.assertEqual((guess["salary_min"], guess["salary_max"]), (20000, 35000))
        self.assertIsNone(response.json()["duplicate"])

    def test_analyze_flags_same_url_as_duplicate(self) -> None:
        text = chr(10).join([
            "Java 开发工程师",
            "https://www.zhipin.com/job_detail/abc123.html",
            "职责：负责后端服务。" * 5,
        ])
        first = self._import(text=text, url="https://www.zhipin.com/job_detail/abc123.html").json()
        self.assertTrue(first["created"])

        result = self.client.post("/api/jobs/analyze", json={"text": text}, headers=HEADER).json()
        self.assertIsNotNone(result["duplicate"], "同一个链接再粘一次要提示已存在")
        self.assertEqual(result["duplicate"]["id"], first["id"])

    def test_analyze_does_not_invent_company(self) -> None:
        result = self.client.post("/api/jobs/analyze",
                                  json={"text": chr(10).join(["招前端。", "会 Vue。"])},
                                  headers=HEADER).json()
        self.assertEqual(result["guess"]["company"], "")
        self.assertTrue(result["guess"]["warnings"])

    # ---- 一键全抓（人工触发） ----

    def _create_source(self, source_id: str, name: str) -> None:
        response = self.client.post("/api/jobs/sources", json={
            "id": source_id, "name": name, "kind": "rss",
            "url": f"https://hr.example.gov.cn/{source_id}.xml", "tier": 1, "config": {},
        }, headers=HEADER)
        self.assertEqual(response.status_code, 200, response.text)

    def test_fetch_all_requires_admin(self) -> None:
        self.assertEqual(self.client.post("/api/jobs/sources/fetch-all", headers=HEADER).status_code, 403)

    def test_fetch_all_runs_enabled_sources_and_isolates_failures(self) -> None:
        self._grant_admin()
        self._create_source("src-a", "可用源")
        self._create_source("src-b", "会失败的源")
        body = "薪资：12-18K。" + "事业单位公开招聘公告，岗位职责与任职要求详见正文。" * 4

        def fake_fetch(spec, *, client=None):
            if spec.id == "src-b":
                raise RuntimeError("连接超时")
            return [sources_base.RawItem(url="https://hr.example.gov.cn/a1.html",
                                         title="某市2026年公开招聘公告", summary=body)]

        with patch("engine.sources.base.fetch_items", side_effect=fake_fetch):
            result = self.client.post("/api/jobs/sources/fetch-all", headers=HEADER).json()

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["sources"], 2)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(len(result["items"]), 2)
        statuses = {item["source"]: item["ok"] for item in result["items"]}
        self.assertEqual(statuses, {"src-a": True, "src-b": False}, "单源失败不能影响其它源")

        # 抓取停了，服务还活着，收件箱能读到那一条
        self.assertEqual(self.client.get("/api/jobs").json()["total"], 1)

    def test_fetch_all_skips_disabled_sources(self) -> None:
        self._grant_admin()
        self._create_source("src-a", "启用源")
        self._create_source("src-b", "停用源")
        with accounts.connection() as db:
            db.execute("UPDATE feed_sources SET enabled = 0 WHERE id = 'src-b'")
        body = "薪资：12-18K。" + "事业单位公开招聘公告。" * 8
        with patch("engine.sources.base.fetch_items", return_value=[
                sources_base.RawItem(url="https://hr.example.gov.cn/a1.html",
                                     title="某市2026年公开招聘公告", summary=body)]):
            result = self.client.post("/api/jobs/sources/fetch-all", headers=HEADER).json()
        self.assertEqual(result["sources"], 1)

    # ---- 省份选择器 ----

    def test_provinces_require_admin(self) -> None:
        self.assertEqual(self.client.get("/api/jobs/provinces").status_code, 403)

    def test_admin_sees_all_provinces(self) -> None:
        self._grant_admin()
        listing = self.client.get("/api/jobs/provinces").json()
        self.assertEqual(len(listing["items"]), 31)
        beijing = next(item for item in listing["items"] if item["code"] == "11")
        self.assertTrue(beijing["verified"])
        self.assertFalse(beijing["enabled"])
        self.assertEqual(beijing["source_id"], "prov-11")

    def test_enable_and_disable_province(self) -> None:
        self._grant_admin()
        enabled = self.client.post("/api/jobs/provinces/11/enable", json={"url": ""}, headers=HEADER)
        self.assertEqual(enabled.status_code, 200, enabled.text)
        self.assertEqual(enabled.json()["source_id"], "prov-11")

        listing = self.client.get("/api/jobs/provinces").json()
        self.assertTrue(next(i for i in listing["items"] if i["code"] == "11")["enabled"])

        self.assertEqual(
            self.client.post("/api/jobs/provinces/11/disable", headers=HEADER).status_code, 200)
        self.assertEqual(
            self.client.post("/api/jobs/provinces/11/disable", headers=HEADER).status_code, 404)

    def test_enable_unverified_province_without_url_is_422(self) -> None:
        self._grant_admin()
        response = self.client.post("/api/jobs/provinces/54/enable", json={"url": ""}, headers=HEADER)
        self.assertEqual(response.status_code, 422)
        with_url = self.client.post("/api/jobs/provinces/54/enable",
                                    json={"url": "https://example.gov.cn/jobs/"}, headers=HEADER)
        self.assertEqual(with_url.status_code, 200, with_url.text)

    def test_tools_fail_softly(self) -> None:
        executor, _ = document_tools.build_executor(user_id="u-alice")
        self.assertIn("error", executor("search_jobs", {"query": "  "}))
        self.assertIn("error", executor("get_job", {"job_id": "不存在"}))
        self.assertIn("error", executor("unknown_tool", {}))


if __name__ == "__main__":
    unittest.main()
