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

# 真实 BOSS 直聘岗位截图里的文字（薪资被平台脱敏成 **-***元）。
# 回得去的原因：职责里那句含 `Workflow`，单个 `k` 曾被当成“K”读出 min=max=2。
BOSS_SCREENSHOT_TEXT = """AI应用开发工程师-JAVA **-***元
北京 3-5年 本科
职位描述
Java Hadoop Spring AI应用开发
岗位职责:
1.设计与开发智能应用系统，整合文本、图像、音频等多模态能力，实现业务智能化。
2.构建并优化多智能体协作框架(A2A)与工作流(Workflow)，提升复杂业务场景的自动化和效率。
3.应用模型交互协议(MCP、FunctionCall)，实现多智能体与工具的统一调用与协作。
4.设计和优化上下文工程，实现多轮对话和复杂任务的上下文管理，结合 RAG 技术进行知识检索与信息增强。
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

    # ---- 薪资不能从职责正文里 "撞" 出来 ----

    def test_salary_is_not_read_from_responsibility_line(self) -> None:
        guess = paste.analyze(BOSS_SCREENSHOT_TEXT)
        self.assertEqual(guess.salary_text, "", "职责里的 Workflow 带一个 k，不能当薪资")
        self.assertIsNone(guess.salary_min)
        self.assertIsNone(guess.salary_max)

    def test_masked_salary_is_left_blank_with_warning(self) -> None:
        guess = paste.analyze(BOSS_SCREENSHOT_TEXT)
        self.assertEqual(guess.salary_text, "")
        self.assertTrue(any("脱敏" in item for item in guess.warnings))

    def test_title_drops_trailing_salary_fragment(self) -> None:
        guess = paste.analyze(BOSS_SCREENSHOT_TEXT)
        self.assertEqual(guess.title, "AI应用开发工程师-JAVA")
        self.assertEqual(guess.city, "北京")
        self.assertEqual(guess.experience, "3-5年")
        self.assertEqual(guess.education, "本科")

    def test_number_in_prose_with_unit_is_not_salary(self) -> None:
        guess = paste.analyze(chr(10).join([
            "产品经理",
            "岗位职责",
            "1.负责把转化率提升 30% - 50%，月活 100 万",
        ]))
        self.assertEqual(guess.salary_text, "")
        self.assertIsNone(guess.salary_min)

    def test_salary_line_with_keyword_still_works(self) -> None:
        guess = paste.analyze(chr(10).join(["数据开发工程师", "薪资：25-40K·14薪，六险一金"]))
        self.assertIn("25-40K", guess.salary_text)
        self.assertEqual((guess.salary_min, guess.salary_max), (25000, 40000))


if __name__ == "__main__":
    unittest.main()
