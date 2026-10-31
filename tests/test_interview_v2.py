"""真实账户/SQLite，Mock 模型；与真实服务商联调分开记录。"""
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from fastapi.testclient import TestClient
from core import accounts
from core.llm import LLMError
from api import interview_store as store
from engine import interview_v2 as engine
from main import app
from tests.interview_v2_fixtures import PROFILE, OTHER_PROFILE, RICH_PROFILE, model_reply

HEADER = {"X-Requested-With": "XMLHttpRequest"}


class ContinuousInterviewContract(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="zhide-interview-v2-")
        self.addCleanup(folder.cleanup)
        db_patch = patch.object(accounts, "DATABASE_PATH", Path(folder.name) / "accounts.sqlite3")
        db_patch.start(); self.addCleanup(db_patch.stop)
        self.a = TestClient(app, headers=HEADER)
        self.b = TestClient(app, headers=HEADER)
        self.addCleanup(self.a.close); self.addCleanup(self.b.close)
        self.uid = self.a.post("/api/auth/register", json={"username": "interview_a", "password": "fake-password-123"}).json()["user"]["id"]
        self.other_uid = self.b.post("/api/auth/register", json={"username": "interview_b", "password": "fake-password-123"}).json()["user"]["id"]
        mock_patch = patch.object(engine, "chat_json", side_effect=model_reply)
        self.model = mock_patch.start(); self.addCleanup(mock_patch.stop)

    def body(self, **kwargs):
        return {"expected_user_id": self.uid, "request_id": str(uuid4()), **kwargs}

    def post(self, route, body):
        return self.a.post("/api/interview/" + route, json=body)

    def bank_body(self, profile=None, jd="Python 后端工程师；负责并发接口与自动化测试"):
        return self.body(resume_profile=profile or PROFILE, resume_markdown="# 虚构简历", jd_text=jd)

    def bank(self):
        response = self.post("bank", self.bank_body())
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["bank"]

    def start(self):
        bank = self.bank()
        req = self.body(bank_id=bank["id"])
        response = self.post("start", req)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["session"]

    def answer_body(self, session, answer="我使用 Python 编写预约冲突检查，通过测试用例验证并发预约。", **kwargs):
        return self.body(session_id=session["id"], version=session["version"], answer=answer, elapsed_seconds=70, **kwargs)

    def end_body(self, session, final_answer=""):
        return self.body(session_id=session["id"], version=session["version"], elapsed_seconds=930, final_answer=final_answer)

    def test_two_materials_have_distinct_sourced_banks_and_safe_samples(self):
        first = self.bank()
        second = self.post("bank", self.bank_body(OTHER_PROFILE, "产品实习生；负责用户访谈与需求分析")).json()["bank"]
        self.assertEqual(len(first["questions"]), 12)
        self.assertEqual({q["category"] for q in first["questions"]}, set(engine.CATEGORIES))
        self.assertNotEqual(first["questions"][0]["question"], second["questions"][0]["question"])
        self.assertIn("校园预约系统", first["questions"][0]["sample_answer"])
        self.assertIn("社区活动调研", second["questions"][0]["sample_answer"])
        self.assertNotIn("社区活动调研", first["questions"][0]["sample_answer"])
        self.assertIn("【待补充", first["questions"][0]["sample_answer"])

    def test_bank_retry_is_idempotent_and_rejects_changed_materials(self):
        req = self.bank_body()
        first = self.post("bank", req).json()
        self.assertEqual(first, self.post("bank", req).json())
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(self.post("bank", dict(req, jd_text="另一个岗位")).status_code, 409)

    def test_richer_materials_are_available_and_mock_covers_distinct_experiences(self):
        req = self.bank_body(RICH_PROFILE, "产品实习生；用户访谈；原型设计；协作沟通")
        response = self.post("bank", req)
        self.assertEqual(response.status_code, 200, response.text)
        bank = response.json()["bank"]
        self.assertEqual(len(bank["questions"]), 16)
        payload = json.loads(self.model.call_args.args[1])
        self.assertEqual(payload["resume_markdown"], req["resume_markdown"])
        self.assertTrue(all(exp["name"] in json.dumps(payload, ensure_ascii=False) for exp in RICH_PROFILE["experiences"]))
        samples = " ".join(q["sample_answer"] for q in bank["questions"])
        self.assertTrue(all(exp["name"] in samples for exp in RICH_PROFILE["experiences"]))
        self.assertNotIn("校园预约系统", samples)

    def test_unconfirmed_empty_jd_and_oversized_inputs_do_not_call_model(self):
        for change in ({"resume_profile": dict(PROFILE, user_confirmed=False)}, {"jd_text": " "}, {"resume_markdown": " "}, {"jd_text": "字" * 20001}):
            self.assertEqual(self.post("bank", dict(self.bank_body(), **change)).status_code, 422)
        self.assertEqual(self.model.call_count, 0)

    def test_malformed_model_and_foreign_sample_sources_rejected(self):
        original = model_reply
        def bad(system, user, **kwargs):
            data = original(system, user, **kwargs)
            data["questions"][0]["sample_source_ids"] = ["s999"]
            return data
        self.model.side_effect = bad
        self.assertEqual(self.post("bank", self.bank_body()).status_code, 502)
        self.model.return_value = {}; self.model.side_effect = None
        self.assertEqual(self.post("bank", self.bank_body()).status_code, 502)

    def test_dynamic_followup_uses_transcript_and_hides_sample_and_scores(self):
        session = self.start()
        req = self.answer_body(session)
        value = self.post("turn", req).json()["session"]
        self.assertIn(req["answer"][:20], value["turns"][-1]["question"]["text"])
        payload = self.model.call_args.args[1]
        self.assertIn("预约冲突检查", payload)
        self.assertNotIn("sample_answer", payload)
        self.assertNotIn("sample_answer", str(value))
        self.assertNotIn("score", str(value))
        self.assertEqual(value["version"], 2)
        self.assertEqual(value["elapsed_seconds"], 70)
        bank, _ = store.load(session["bank_id"], self.uid, "bank")
        self.assertEqual(bank["snapshot"]["resume_profile"], {**PROFILE, "raw_text": ""})

    def test_timeout_then_retry_preserves_answer_without_duplication(self):
        session = self.start(); req = self.answer_body(session)
        self.model.side_effect = LLMError("timeout", status_code=504)
        self.assertEqual(self.post("turn", req).status_code, 504)
        state, _ = store.load(session["id"], self.uid, "session")
        self.assertIsNone(state["turns"][0]["answer"])
        self.model.side_effect = model_reply
        success = self.post("turn", req).json()
        calls = self.model.call_count
        self.assertEqual(success, self.post("turn", req).json())
        self.assertEqual(calls, self.model.call_count)
        self.assertEqual(len(success["session"]["turns"]), 2)
        self.assertEqual(self.post("turn", dict(req, answer="changed")).status_code, 409)

    def test_duplicate_concurrent_submission_and_stale_version(self):
        session = self.start(); req = self.answer_body(session)
        with ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(lambda _: self.post("turn", req), range(2)))
        self.assertEqual([r.status_code for r in replies], [200, 200])
        self.assertEqual(replies[0].json(), replies[1].json())
        self.assertEqual(self.post("turn", self.answer_body(session)).status_code, 409)

    def test_blank_oversized_and_skip(self):
        session = self.start()
        for answer in (" ", "字" * 12001):
            self.assertEqual(self.post("turn", self.answer_body(session, answer)).status_code, 422)
        value = self.post("turn", self.answer_body(session, "", skip=True)).json()["session"]
        self.assertTrue(value["turns"][0]["skipped"])
        self.assertFalse(value["turns"][-1]["question"]["is_follow_up"])

    def test_fifteen_minutes_does_not_end_and_early_end_has_partial_feedback(self):
        session = self.start()
        req = dict(self.answer_body(session), elapsed_seconds=930)
        session = self.post("turn", req).json()["session"]
        self.assertEqual(session["status"], "active")
        value = self.post("report", self.end_body(session, "我会如实说明目前的能力差距。")).json()
        self.assertTrue(value["saved"])
        self.assertEqual(value["report"]["kind"], "partial")
        self.assertIsNone(value["report"]["overall_score"])
        self.assertEqual(value["report"]["answered_count"], 2)
        self.assertEqual(value["session"]["turns"][-1]["answer"], "我会如实说明目前的能力差距。")

    def test_full_report_is_equal_weight_and_cites_actual_answers_and_history(self):
        session = self.start()
        for _ in range(2):
            session = self.post("turn", self.answer_body(session)).json()["session"]
        req = self.end_body(session, "我会使用接口测试确认预约冲突处理的边界。")
        value = self.post("report", req).json()
        self.assertEqual(value["report"]["overall_score"], 75)
        self.assertEqual(len(value["report"]["dimensions"]), 5)
        self.assertIn(value["report"]["dimensions"][0]["evidence"][0]["quote"], session["turns"][0]["answer"])
        calls = self.model.call_count
        self.assertEqual(value, self.post("report", req).json())
        self.assertEqual(calls, self.model.call_count)
        records = self.a.get("/api/interview-records").json()["records"]
        self.assertEqual(len(records), 1)
        record = self.a.get("/api/interview-records/" + value["record_id"]).json()["record"]
        self.assertEqual(record["overall_feedback"]["schema_version"], 3)
        self.assertEqual(record["question_scores"], [])
        self.assertEqual(record["overall_feedback"]["snapshot"]["jd_text"], self.bank_body()["jd_text"])

    def test_missing_dimension_evidence_never_produces_complete_total(self):
        session = self.start()
        for _ in range(3):
            session = self.post("turn", self.answer_body(session)).json()["session"]
        def partial(system, user, **kwargs):
            value = model_reply(system, user, **kwargs)
            value["dimensions"][-1].update(score=None, evidence=[])
            return value
        self.model.side_effect = partial
        report = self.post("report", self.end_body(session)).json()["report"]
        self.assertIsNone(report["overall_score"])
        self.assertEqual(report["dimensions"][-1]["status"], "insufficient")

    def test_report_failure_retries_and_no_more_answers_after_end(self):
        session = self.start(); req = self.end_body(session, "我负责预约冲突检查。")
        self.model.side_effect = LLMError("invalid", status_code=502)
        self.assertEqual(self.post("report", req).status_code, 502)
        self.assertEqual(self.post("turn", self.answer_body(session)).status_code, 409)
        self.model.side_effect = model_reply
        self.assertEqual(self.post("report", req).json()["report"]["answered_count"], 1)

    def test_fabricated_quote_rejected_and_retry_without_reappending_final(self):
        session = self.start(); req = self.end_body(session, "只回答已确认的事实。")
        def bad(system, user, **kwargs):
            data = model_reply(system, user, **kwargs)
            data["dimensions"][0]["evidence"] = [{"turn_id": "turn-1", "quote": "伪造收入增长100倍"}]
            return data
        self.model.side_effect = bad
        self.assertEqual(self.post("report", req).status_code, 502)
        self.model.side_effect = model_reply
        value = self.post("report", req).json()
        self.assertEqual(len(value["session"]["turns"]), 1)
        self.assertEqual(value["report"]["answered_count"], 1)

    def test_save_failure_retains_report_retry_does_not_call_model(self):
        session = self.start(); req = self.end_body(session)
        with patch.object(store, "persist_completed", side_effect=sqlite3.OperationalError("disk unavailable")):
            first = self.post("report", req).json()
        self.assertFalse(first["saved"])
        self.assertIsNone(first["report"]["overall_score"])
        calls = self.model.call_count
        self.assertTrue(self.post("report", req).json()["saved"])
        self.assertEqual(calls, self.model.call_count)
        self.assertEqual(len(self.a.get("/api/interview-records").json()["records"]), 1)

    def test_deleted_history_cannot_be_recreated_by_a_delayed_report_retry(self):
        session = self.start(); req = self.end_body(session)
        result = self.post("report", req).json()
        calls = self.model.call_count
        self.assertEqual(self.a.delete("/api/interview-records/" + result["record_id"]).status_code, 200)
        self.assertEqual(self.post("report", req).status_code, 410)
        self.assertEqual(self.model.call_count, calls)
        self.assertEqual(self.a.get("/api/interview-records").json()["records"], [])

    def test_account_isolation_auth_csrf_and_stale_account(self):
        session = self.start()
        self.assertEqual(TestClient(app).post("/api/interview/bank", json=self.bank_body()).status_code, 401)
        self.assertEqual(self.a.post("/api/interview/turn", json=self.answer_body(session), headers={"X-Requested-With": ""}).status_code, 403)
        self.assertEqual(self.b.post("/api/interview/turn", json=self.answer_body(session)).status_code, 409)
        foreign = self.body(expected_user_id=self.other_uid, session_id=session["id"], version=1, answer="跨账户")
        self.assertEqual(self.b.post("/api/interview/turn", json=foreign).status_code, 404)
        foreign_bank = self.body(expected_user_id=self.other_uid, bank_id=session["bank_id"])
        self.assertEqual(self.b.post("/api/interview/turn", json=foreign_bank).status_code, 404)
        completed = self.post("report", self.end_body(session)).json()
        self.assertEqual(self.b.get("/api/interview-records/" + completed["record_id"]).status_code, 404)
        self.assertEqual(self.b.delete("/api/interview-records/" + completed["record_id"]).status_code, 404)
        self.assertEqual(self.b.get("/api/interview-records").json()["records"], [])

    def test_bank_accepts_dynamic_count_and_rejects_out_of_bounds_and_duplicates(self):
        def sized(count, duplicate=False):
            def reply(system, user, **kwargs):
                value = model_reply(system, user, **kwargs)
                originals = value["questions"]
                value["questions"] = [dict(copy.deepcopy(originals[i % len(originals)]),
                    question=f"请解释独立考察角度{i + 1}的实际选择依据？") for i in range(count)]
                if duplicate:
                    value["questions"][-1]["question"] = " 请解释独立考察角度1的实际选择依据! "
                return value
            return reply
        for count in (10, 18, 30):
            with self.subTest(count=count):
                self.model.side_effect = sized(count)
                response = self.post("bank", self.bank_body())
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(len(response.json()["bank"]["questions"]), count)
        for count, duplicate in ((9, False), (31, False), (10, True)):
            with self.subTest(count=count, duplicate=duplicate):
                self.model.side_effect = sized(count, duplicate)
                req = self.bank_body()
                self.assertEqual(self.post("bank", req).status_code, 502)
                self.assertIsNone(store.find("bank-" + req["request_id"], self.uid, "bank"))

    def test_direct_start_is_one_call_without_bank_and_freezes_latest_materials(self):
        req = dict(self.bank_body(), resume_markdown="# 最新生成稿\n校园预约系统：重点解释并发验证")
        with patch.object(engine, "generate_bank", side_effect=AssertionError("不应生成题库")):
            response = self.post("start", req)
        self.assertEqual(response.status_code, 200, response.text)
        session = response.json()["session"]
        self.assertEqual(self.model.call_count, 1)
        self.assertEqual(session["mode"], "direct")
        self.assertIsNone(session["bank_id"])
        self.assertEqual(session["snapshot"]["resume_markdown"], req["resume_markdown"])
        state, _ = store.load(session["id"], self.uid, "session")
        self.assertIsNone(state["bank"])
        self.assertEqual({t["category"] for t in state["context"]["topics"]}, set(engine.CATEGORIES))
        self.assertNotIn("sample_answer", json.dumps(state["context"]))
        self.assertNotIn("questions", state["context"])
        self.assertIn("最新生成稿", self.model.call_args.args[1])
        value = self.post("turn", self.answer_body(session)).json()["session"]
        self.assertEqual(value["snapshot"], session["snapshot"])
        self.assertIn("最新生成稿", self.model.call_args.args[1])
        self.assertNotIn("score", str(value["turns"]))
        self.assertNotIn("answer_structure", self.model.call_args.args[1])

    def test_direct_starts_differ_by_confirmed_resume_and_jd(self):
        first = self.post("start", self.bank_body()).json()["session"]
        second = self.post("start", self.bank_body(OTHER_PROFILE, "产品实习生；用户访谈")).json()["session"]
        self.assertNotEqual(first["turns"][0]["question"]["text"], second["turns"][0]["question"]["text"])
        self.assertIn("社区活动调研", second["turns"][0]["question"]["text"])
        self.assertNotIn("校园预约系统", second["turns"][0]["question"]["text"])

    def test_start_input_exclusivity_and_auth(self):
        for req in (self.body(), self.body(bank_id="bank-missing", resume_markdown="稿"),
                    self.body(resume_profile=PROFILE, jd_text="岗位"),
                    dict(self.bank_body(), resume_profile=dict(PROFILE, user_confirmed=False)),
                    dict(self.bank_body(), resume_markdown=" ")):
            self.assertEqual(self.post("start", req).status_code, 422)
        self.assertEqual(self.model.call_count, 0)
        self.assertEqual(TestClient(app).post("/api/interview/start", json=self.bank_body()).status_code, 401)
        self.assertEqual(self.a.post("/api/interview/start", json=self.bank_body(), headers={"X-Requested-With": ""}).status_code, 403)
        self.assertEqual(self.b.post("/api/interview/start", json=self.bank_body()).status_code, 409)
        bank = self.bank()
        self.assertEqual(self.b.post("/api/interview/start", json=self.body(expected_user_id=self.other_uid, bank_id=bank["id"])).status_code, 404)

    def test_direct_invalid_or_timeout_start_retries_without_partial_state_and_double_call(self):
        req = self.bank_body()
        def invalid(system, user, **kwargs):
            data = model_reply(system, user, **kwargs)
            data["first_question"]["topic_id"] = "unknown"
            return data
        for failure in (invalid, LLMError("timeout", status_code=504)):
            self.model.side_effect = failure
            self.assertIn(self.post("start", req).status_code, (502, 504))
            self.assertIsNone(store.find("session-" + req["request_id"], self.uid, "session"))
        self.model.side_effect = model_reply
        calls = self.model.call_count
        with ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(lambda _: self.post("start", req), range(2)))
        self.assertEqual([r.status_code for r in replies], [200, 200])
        self.assertEqual(replies[0].json(), replies[1].json())
        self.assertEqual(self.model.call_count, calls + 1)
        self.assertEqual(self.post("start", dict(req, jd_text="改了岗位")).status_code, 409)

    def test_direct_report_schema3_save_recovery_and_deleted_record_never_returns(self):
        session = self.post("start", self.bank_body()).json()["session"]
        for _ in range(2):
            session = self.post("turn", self.answer_body(session)).json()["session"]
        req = self.end_body(session, "我负责接口边界验证，会如实补充还未覆盖的测试。")
        with patch.object(store, "persist_completed", side_effect=sqlite3.OperationalError("disk unavailable")):
            failed = self.post("report", req).json()
        self.assertFalse(failed["saved"])
        calls = self.model.call_count
        result = self.post("report", req).json()
        self.assertEqual(self.model.call_count, calls)
        self.assertEqual(result["report"]["overall_score"], 75)
        record = self.a.get("/api/interview-records/" + session["id"]).json()["record"]
        feedback = record["overall_feedback"]
        self.assertEqual(feedback["schema_version"], 3)
        self.assertEqual(feedback["mode"], "direct")
        self.assertIsNone(feedback["bank"])
        self.assertEqual(feedback["snapshot"], session["snapshot"])
        self.assertEqual(len(feedback["context"]["topics"]), 4)
        self.assertEqual(len(result["report"]["coverage"]), 4)
        quote = result["report"]["dimensions"][0]["evidence"][0]["quote"]
        self.assertIn(quote, session["turns"][0]["answer"])
        self.assertEqual(self.b.get("/api/interview-records/" + session["id"]).status_code, 404)
        self.assertEqual(self.a.delete("/api/interview-records/" + session["id"]).status_code, 200)
        self.assertEqual(self.post("report", req).status_code, 410)

    def test_legacy_turn_start_and_in_progress_v2_context_remain_compatible(self):
        bank = self.bank()
        session = self.post("turn", self.body(bank_id=bank["id"])).json()["session"]
        state, revision = store.load(session["id"], self.uid, "session")
        del state["context"]; del state["mode"]
        store.write(session["id"], self.uid, "session", state, revision)
        response = self.post("turn", self.answer_body(session))
        self.assertEqual(response.status_code, 200, response.text)
        result = self.post("report", self.end_body(response.json()["session"])).json()
        self.assertTrue(result["saved"])


if __name__ == "__main__":
    unittest.main()
