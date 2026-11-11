"""信源适配器合约：RSS/Atom 解析、列表页抽取、正文纯文本、入库去重与失败状态。

全部离线：解析用固定样本，抓取函数用 Mock 替换，不发起任何网络请求。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from core import accounts  # noqa: E402
from engine.sources import base as sources_base  # noqa: E402
from engine.sources import html_list, rss  # noqa: E402

RSS_DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>某省人社厅公告</title>
  <item>
    <title>某市事业单位2026年公开招聘公告</title>
    <link>https://hr.example.gov.cn/notice/1.html</link>
    <description>&lt;p&gt;招聘&lt;b&gt;数据管理岗&lt;/b&gt;3人，报名截止2026-12-01。&lt;/p&gt;</description>
    <pubDate>Mon, 10 Nov 2026 08:00:00 GMT</pubDate>
  </item>
  <item>
    <title>国有企业校园招聘（第二批）</title>
    <link>https://hr.example.gov.cn/notice/2.html</link>
    <pubDate>2026-11-09T09:30:00Z</pubDate>
  </item>
</channel></rss>"""

ATOM_DOCUMENT = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>校招公告</title>
  <entry>
    <title>2026 届毕业生双选会</title>
    <link rel="alternate" href="https://job.example.edu.cn/a/1"/>
    <updated>2026-11-08T02:00:00Z</updated>
    <summary>参会单位 120 家</summary>
  </entry>
</feed>"""

LIST_DOCUMENT = """<html><body>
<nav><a href="/">首页</a></nav>
<ul class="list">
  <li><a href="/notice/2026/001.html">某市事业单位2026年公开招聘公告</a></li>
  <li><a href="/notice/2026/002.html">2026年国有企业校园招聘岗位表</a></li>
  <li><a href="/notice/2026/003.html">关于开展安全生产检查的通知</a></li>
  <li><a href="/notice/2026/001.html">某市事业单位2026年公开招聘公告</a></li>
</ul>
</body></html>"""

DETAIL_DOCUMENT = """<html><head><style>.x{color:red}</style></head><body>
<nav><a href="/">首页</a></nav>
<script>var tracking = 1;</script>
<div class="content"><p>岗位职责：负责数据平台建设。</p><p>任职要求：熟悉 SQL 与数据仓库。</p></div>
<footer>版权所有</footer>
</body></html>"""


def spec(**config) -> sources_base.SourceSpec:
    return sources_base.SourceSpec(
        id="src-demo", name="某省人社厅", kind="html_list",
        url="https://hr.example.gov.cn/list/index.html", tier=1,
        license_note="政府公开信息", config=config,
    )


class RssTest(unittest.TestCase):
    def test_rss2_items_keep_link_title_and_date(self) -> None:
        items = rss.items(RSS_DOCUMENT, limit=10)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].url, "https://hr.example.gov.cn/notice/1.html")
        self.assertIn("公开招聘", items[0].title)
        self.assertIn("数据管理岗", items[0].summary)
        self.assertNotIn("<b>", items[0].summary)
        self.assertIsNotNone(items[0].published_at)
        self.assertIsNotNone(items[1].published_at, "ISO 时间也要能解析")

    def test_rss_respects_limit(self) -> None:
        self.assertEqual(len(rss.items(RSS_DOCUMENT, limit=1)), 1)

    def test_atom_entry_uses_alternate_link(self) -> None:
        items = rss.items(ATOM_DOCUMENT, limit=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://job.example.edu.cn/a/1")
        self.assertEqual(items[0].title, "2026 届毕业生双选会")

    def test_broken_feed_raises(self) -> None:
        with self.assertRaises(Exception):
            rss.items("<rss><channel>", limit=5)


class HtmlListTest(unittest.TestCase):
    def test_items_absolutize_filter_and_dedupe(self) -> None:
        items = html_list.items(LIST_DOCUMENT, spec=spec())
        urls = [item.url for item in items]
        self.assertEqual(urls, [
            "https://hr.example.gov.cn/notice/2026/001.html",
            "https://hr.example.gov.cn/notice/2026/002.html",
        ], "应补全绝对地址、过滤非招聘公告、去重")

    def test_max_items_caps_results(self) -> None:
        items = html_list.items(LIST_DOCUMENT, spec=spec(max_items=1))
        self.assertEqual(len(items), 1)

    def test_custom_include_keywords(self) -> None:
        items = html_list.items(LIST_DOCUMENT, spec=spec(include_keywords=["安全生产"]))
        self.assertEqual(len(items), 1)
        self.assertIn("安全生产", items[0].title)

    def test_invalid_regex_is_reported(self) -> None:
        with self.assertRaises(ValueError):
            html_list.items(LIST_DOCUMENT, spec=spec(item_regex="([unclosed"))

    def test_readable_text_drops_script_and_navigation(self) -> None:
        body = html_list.readable_text(DETAIL_DOCUMENT)
        self.assertIn("数据平台建设", body)
        self.assertIn("数据仓库", body)
        for noise in ("tracking", "color:red", "首页", "版权所有"):
            self.assertNotIn(noise, body)


class HtmlListFilterTest(unittest.TestCase):
    def test_min_title_length_and_exclude_keywords(self) -> None:
        document = """<ul>
          <li><a href="/a.html">招聘信息</a></li>
          <li><a href="/b.html">某市事业单位2026年公开招聘公告</a></li>
          <li><a href="/c.html">2026年公开招聘公告查看更多</a></li>
        </ul>"""
        items = html_list.items(document, spec=spec(min_title_length=10,
                                                   exclude_keywords=["查看更多"]))
        self.assertEqual([item.url for item in items], ["https://hr.example.gov.cn/b.html"])


class ProvinceTemplateTest(unittest.TestCase):
    def test_templates_cover_provinces_and_mark_verification(self) -> None:
        from engine.sources import provinces

        listing = provinces.list_provinces()
        self.assertEqual(len(listing), 31)
        verified = [item for item in listing if item["verified"]]
        self.assertGreaterEqual(len(verified), 20)
        for item in listing:
            self.assertIn("code", item)
            self.assertIn("name", item)
            if not item["verified"]:
                self.assertTrue(item.get("note"), "未验证的省份必须说明原因")

    def test_build_spec_uses_template_url_and_rejects_empty(self) -> None:
        from engine.sources import provinces

        spec_beijing = provinces.build_spec("11")
        self.assertEqual(spec_beijing.id, "prov-11")
        self.assertEqual(spec_beijing.kind, "html_list")
        self.assertIn("人社厅", spec_beijing.name)
        self.assertIn("min_title_length", spec_beijing.config)
        with self.assertRaises(ValueError):
            provinces.build_spec("54")  # 西藏：模板里没有可用地址
        with self.assertRaises(ValueError):
            provinces.build_spec("99")

    def test_enable_is_idempotent_and_records_url_override(self) -> None:
        from engine.sources import provinces

        with accounts.connection() as db:
            first = provinces.enable(db, "11")
            second = provinces.enable(db, "11", url="https://rsj.beijing.gov.cn/col/rsks/")
            rows = db.execute("SELECT * FROM feed_sources WHERE id = ?", (first.id,)).fetchall()

        self.assertEqual(len(rows), 1, "重复启用只能有一条记录")
        self.assertEqual(second.url, "https://rsj.beijing.gov.cn/col/rsks/")
        self.assertEqual(rows[0]["tier"], 1)
        self.assertEqual(rows[0]["enabled"], 1)


class SourceRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(accounts, "DATABASE_PATH", Path(self.tmp.name) / "sources.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.spec = spec()
        with accounts.connection() as db:
            sources_base.upsert_spec(db, self.spec)

    def test_upsert_spec_roundtrip(self) -> None:
        with accounts.connection() as db:
            row = db.execute("SELECT * FROM feed_sources WHERE id = ?", (self.spec.id,)).fetchone()
        loaded = sources_base.spec_from_row(row)
        self.assertEqual((loaded.id, loaded.kind, loaded.tier), ("src-demo", "html_list", 1))
        self.assertEqual(loaded.max_items, sources_base.DEFAULT_MAX_ITEMS)

    def test_run_source_stores_public_pool_and_dedupes(self) -> None:
        body = ("薪资：8-12K\n招聘数据管理岗。岗位职责：负责数据平台建设与指标口径维护。\n"
                + "任职要求：熟悉 SQL 与数据仓库建模，了解调度系统。" * 3)
        found = [sources_base.RawItem(url="https://hr.example.gov.cn/a.html",
                                      title="某市公开招聘公告",
                                      summary=body)]
        with patch("engine.sources.base.fetch_items", return_value=found):
            with accounts.connection() as db:
                first = sources_base.run_source(db, self.spec)
            with accounts.connection() as db:
                second = sources_base.run_source(db, self.spec)
                rows = db.execute("SELECT * FROM documents").fetchall()
                status = db.execute("SELECT last_status FROM feed_sources WHERE id = ?",
                                    (self.spec.id,)).fetchone()["last_status"]

        self.assertTrue(first["ok"])
        self.assertEqual((first["created"], first["updated"]), (1, 0))
        self.assertEqual((second["created"], second["updated"]), (0, 1))
        self.assertEqual(len(rows), 1, "同一链接重复抓取只能有一条")
        self.assertIsNone(rows[0]["user_id"], "采集结果进公共岗位池")
        self.assertEqual(rows[0]["visibility"], "public")
        self.assertEqual((rows[0]["salary_min"], rows[0]["salary_max"]), (8000, 12000))
        self.assertTrue(status.startswith("ok"))

    def test_short_content_is_skipped_as_portal_link(self) -> None:
        found = [sources_base.RawItem(url="https://hr.example.gov.cn/portal.html",
                                     title="事业单位公开招聘考试报名平台", summary="报名平台")]
        with patch("engine.sources.base.fetch_items", return_value=found):
            with accounts.connection() as db:
                result = sources_base.run_source(db, self.spec)
                rows = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        self.assertTrue(result["ok"])
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(rows, 0, "正文不足 80 字的入口页不应入库")

    def test_salary_without_digits_is_not_recorded(self) -> None:
        boilerplate = "受聘人员工资待遇按国家和本单位有关规定执行。" * 4
        found = [sources_base.RawItem(url="https://hr.example.gov.cn/b.html",
                                      title="某单位2026年公开招聘公告", summary=boilerplate)]
        with patch("engine.sources.base.fetch_items", return_value=found):
            with accounts.connection() as db:
                sources_base.run_source(db, self.spec)
                row = db.execute("SELECT * FROM documents").fetchone()
        self.assertEqual(row["salary_text"], "", "没有数字的政策话术不算薪资")
        self.assertIsNone(row["salary_min"])

    def test_run_source_failure_keeps_data_and_records_status(self) -> None:
        with patch("engine.sources.base.fetch_items", side_effect=RuntimeError("连接超时")):
            with accounts.connection() as db:
                result = sources_base.run_source(db, self.spec)
            with accounts.connection() as db:
                status = db.execute("SELECT last_status FROM feed_sources WHERE id = ?",
                                    (self.spec.id,)).fetchone()["last_status"]

        self.assertFalse(result["ok"])
        self.assertIn("连接超时", result["error"])
        self.assertTrue(status.startswith("error"), "失败要写进 last_status 供后台查看")


if __name__ == "__main__":
    unittest.main()
