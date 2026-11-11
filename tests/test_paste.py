"""粘贴识别合约：BOSS 文案、事业单位公告、缺字段的极简文本各测一遍。

原则：识别不出来就留空，不能猜。这里也验证"不猜"的边界——例如没有公司名的文本
不能凭空生成公司，没有数字的"薪资面议"不能变成区间。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from engine.documents import paste  # noqa: E402

BOSS_TEXT = """数据开发工程师
20-35K·14薪
北京·朝阳区 3-5年 本科
某某科技有限公司
岗位职责：
1. 建设数据平台，支撑业务报表与指标口径
2. 维护离线与实时数仓
任职要求：
1. 熟悉 SQL、Hive、Flink
2. 有数据治理经验优先
"""

GOV_TEXT = """北京市人力资源和社会保障局所属事业单位2026年公开招聘公告

招聘单位：北京市人才服务中心
工作地点：北京市西城区
薪资待遇：按国家规定执行
学历要求：硕士研究生及以上
经验要求：2-3年

一、招聘岗位及人数
...
"""

MINIMAL_TEXT = """招前端。
会 Vue。
"""


class PasteAnalyzeTest(unittest.TestCase):
    def test_boss_style_paste(self) -> None:
        guess = paste.analyze(BOSS_TEXT)
        self.assertEqual(guess.title, "数据开发工程师")
        self.assertEqual(guess.company, "某某科技有限公司")
        self.assertEqual(guess.city, "北京")
        self.assertEqual((guess.salary_min, guess.salary_max), (20000, 35000))
        self.assertEqual(guess.experience, "3-5年")
        self.assertEqual(guess.education, "本科")
        self.assertEqual(guess.url, "")

    def test_government_notice_paste(self) -> None:
        guess = paste.analyze(GOV_TEXT)
        self.assertIn("公开招聘公告", guess.title)
        self.assertEqual(guess.company, "北京市人才服务中心")
        self.assertEqual(guess.city, "北京")
        self.assertEqual(guess.education, "硕士")
        self.assertEqual(guess.experience, "2-3年")
        self.assertEqual(guess.salary_text, "", "「按国家规定执行」不是薪资区间，不能记成数字")

    def test_minimal_text_does_not_invent_fields(self) -> None:
        guess = paste.analyze(MINIMAL_TEXT)
        self.assertEqual(guess.title, "招前端。")
        self.assertEqual(guess.company, "")
        self.assertEqual(guess.city, "")
        self.assertIsNone(guess.salary_min)
        self.assertTrue(any("公司" in item for item in guess.warnings))

    def test_url_is_extracted_and_trimmed(self) -> None:
        guess = paste.analyze(
            "Java 开发工程师\nhttps://www.zhipin.com/job_detail/abc123.html，欢迎投递")
        self.assertEqual(guess.url, "https://www.zhipin.com/job_detail/abc123.html")
        self.assertEqual(guess.title, "Java 开发工程师")

    def test_empty_text(self) -> None:
        guess = paste.analyze("   ")
        self.assertTrue(guess.warnings)
        self.assertEqual(guess.title, "")


if __name__ == "__main__":
    unittest.main()
