"""手动验收：默认 Mock；--live 调用已有模型配置，仅发送本文件引用的虚构材料。"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from core import accounts
from core.config import settings
from core.llm import is_configured
from engine import interview_v2 as engine
from main import app
from tests.interview_v2_fixtures import PROFILE, RICH_PROFILE, model_reply


def exercise():
    with TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"}) as client:
        user = client.post("/api/auth/register", json={"username": "synthetic_qa", "password": uuid4().hex}).json()["user"]
        def post(route, **kwargs):
            response = client.post("/api/interview/" + route, json={"expected_user_id": user["id"], "request_id": str(uuid4()), **kwargs})
            if response.status_code != 200:
                raise RuntimeError(f"{route}: HTTP {response.status_code} {response.json().get('detail', '')}")
            return response.json()
        banks = []
        for profile, jd in ((PROFILE, "Python 后端工程师；负责并发接口、自动化测试与协作"),
                            (RICH_PROFILE, "产品实习生；负责用户访谈、需求分析和活动报名体验优化")):
            bank = post("bank", resume_profile=profile, resume_markdown="# " + profile["name"], jd_text=jd)["bank"]
            banks.append(bank)
            print(json.dumps({"step": "bank", "role": bank["job_title"], "questions": len(bank["questions"]),
                              "categories": sorted({q["category"] for q in bank["questions"]})}, ensure_ascii=False), flush=True)
        assert banks[0]["questions"][0]["question"] != banks[1]["questions"][0]["question"]
        for index, (bank, profile) in enumerate(zip(banks, (PROFILE, RICH_PROFILE))):
            session = (post("start", bank_id=bank["id"]) if index == 0 else
                       post("start", resume_profile=profile, resume_markdown="# " + profile["name"],
                            jd_text=bank["snapshot"]["jd_text"]))["session"]
            print(json.dumps({"step": "start", "case": index + 1, "mode": session["mode"],
                              "bank_id": session["bank_id"]}, ensure_ascii=False), flush=True)
            answers = (["我在校园预约系统负责使用 Python 编写预约冲突检查，并通过测试用例验证并发预约。",
                        "我个人完成冲突检查接口。验证时使用并发预约测试用例，现有结果是交付预约原型，尚无真实用户指标。",
                        "对于生产环境的高并发我还缺少实践。我会先确认业务冲突规则，补充边界用例，并请有经验的同事评审。"] if index == 0 else
                       ["我参与社区活动调研，负责整理用户访谈笔记，并归纳活动报名的障碍。成果是提交报名流程建议。",
                        "我个人整理访谈材料，把重复出现的报名障碍归类。没有上线效果数字，当前仅能说明已提交的流程建议。",
                        "对于意见冲突我会先核对原始访谈记录，再澄清用户场景，说明建议的依据和还需要验证的假设。"])
            for answer in answers[:2]:
                session = post("turn", session_id=session["id"], version=session["version"], answer=answer, elapsed_seconds=400)["session"]
                print(json.dumps({"step": "turn", "case": index + 1, "stage": session["turns"][-1]["question"]["stage"],
                                  "follow_up": session["turns"][-1]["question"]["is_follow_up"]}, ensure_ascii=False), flush=True)
            result = post("report", session_id=session["id"], version=session["version"], elapsed_seconds=920, final_answer=answers[-1])
            assert result["saved"]
            report = result["report"]
            record = client.get("/api/interview-records/" + result["record_id"]).json()["record"]
            assert record["overall_feedback"]["schema_version"] == 3
            assert record["overall_feedback"]["mode"] == ("bank" if index == 0 else "direct")
            if index == 1:
                assert record["overall_feedback"]["bank"] is None
            transcript = {t["id"]: t["answer"] or "" for t in result["session"]["turns"]}
            assert all(c["quote"] in transcript[c["turn_id"]] for d in report["dimensions"] for c in d["evidence"])
            print(json.dumps({"step": "report", "case": index + 1, "kind": report["kind"], "overall_score": report["overall_score"],
                              "dimensions": len(report["dimensions"]), "saved": result["saved"], "citations": sum(len(d["evidence"]) for d in report["dimensions"])}, ensure_ascii=False), flush=True)
        assert len(client.get("/api/interview-records").json()["records"]) == 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--serve", action="store_true", help="隔离的浏览器 Mock 验收服务；不连接真实账户数据")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    settings()  # 与服务启动一致，先加载本地配置；不输出密钥。
    if args.live and not is_configured():
        raise SystemExit("模型未配置，未运行真实联调")
    with tempfile.TemporaryDirectory(prefix="zhide-interview-manual-") as folder:
        accounts.DATABASE_PATH = Path(folder) / "accounts.sqlite3"
        if args.serve:
            if args.live:
                raise SystemExit("浏览器验收服务仅允许 Mock；真实联调请单独使用 --live")
            import uvicorn
            # 仅本机、仅虚构验收。工作台解析仍按原实现；从预存工作台进入面试。
            with patch.object(engine, "chat_json", side_effect=model_reply):
                with TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"}) as seed:
                    seed_user = seed.post("/api/auth/register", json={"username": "interview_demo", "password": "synthetic-demo-123"}).json()["user"]
                    seed.post("/api/workspace", json={"expected_user_id": seed_user["id"], "revision": 0, "state": {
                        "source_text": "虚构验收资料", "source_name": "虚构材料", "jd_text": "Python 后端工程师；负责并发接口与测试",
                        "profile": PROFILE, "jd_keywords": [], "markdown": "# 虚构林同学\n后端开发：校园预约系统", "page": "interview"}})
                print("Mock demo: interview_demo / synthetic-demo-123", flush=True)
                uvicorn.run(app, host="127.0.0.1", port=args.port)
        elif args.live:
            exercise()
        else:
            with patch.object(engine, "chat_json", side_effect=model_reply):
                exercise()
