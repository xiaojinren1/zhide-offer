"""仅虚构资料与 Mock 模型响应，供面试合约及本机验收使用。"""
import copy
import json

PROFILE = {
    "name": "虚构林同学", "skills": ["Python"], "education": ["虚构大学"], "user_confirmed": True,
    "experiences": [{"kind": "project", "name": "校园预约系统", "role": "后端开发", "period": "2025",
                     "actions": ["使用 Python 编写预约冲突检查", "通过测试用例验证并发预约"],
                     "results": ["交付预约原型"], "skills": ["Python", "接口测试"]}],
}
OTHER_PROFILE = copy.deepcopy(PROFILE)
OTHER_PROFILE.update(name="虚构许同学", skills=["用户访谈"])
OTHER_PROFILE["experiences"] = [{"kind": "internship", "name": "社区活动调研", "role": "产品实习生", "period": "2024",
                                 "actions": ["整理用户访谈笔记并归纳报名障碍"], "results": ["提交活动报名流程建议"], "skills": ["用户访谈"]}]
RICH_PROFILE = copy.deepcopy(OTHER_PROFILE)
RICH_PROFILE["experiences"] += [
    {"kind": "project", "name": "校园信息检索原型", "role": "产品设计", "period": "2025",
     "actions": ["梳理搜索任务路径并制作原型", "邀请同学完成可用性走查"], "results": ["整理走查问题清单"], "skills": ["原型设计"]},
    {"kind": "project", "name": "志愿活动复盘", "role": "组织协调", "period": "2025",
     "actions": ["收集参与者反馈并和志愿者讨论分工"], "results": ["形成下一轮活动改进清单"], "skills": ["协作沟通"]},
]


def model_reply(system, user, **_kwargs):
    payload = json.loads(user)
    if '"DirectStartOutput"' in system:
        sources = payload["sources"]
        resume = next(s for s in sources if s["kind"] == "resume")
        jd = next(s for s in sources if s["kind"] == "jd")
        return {"job_title": jd["text"][:60], "topics": [
            {"id": f"topic-{i + 1}", "category": category, "focus": f"{resume['text']}与{jd['text']}的{category}能力",
             "source_ids": [resume["id"], jd["id"]]}
            for i, category in enumerate(("experience", "professional", "behavior", "motivation"))],
            "first_question": {"text": f"针对{jd['text']}，请介绍你在{resume['text']}中的相关经历。",
                               "stage": "introduction", "topic_id": "topic-1", "is_follow_up": False, "suggest_finish": False}}
    if "transcript" not in payload:
        sources = payload["sources"]
        resume = next(s for s in sources if s["kind"] == "resume")
        jd = next(s for s in sources if s["kind"] == "jd")
        projects = [s for s in sources if s["kind"] == "resume" and " · " not in s["label"] and not s["label"].startswith("已确认")]
        count = min(30, 10 + 2 * len(projects))
        return {"job_title": jd["text"][:60], "questions": [
            {"category": ("experience", "professional", "behavior", "motivation")[i % 4],
             "question": f"关于{projects[i % len(projects)]['text']}，针对{jd['text']}，请说明第{i + 1}项决策的个人行动？",
             "focus": f"个人贡献与判断依据{i + 1}", "source_ids": [projects[i % len(projects)]["id"], jd["id"]],
             "follow_ups": ["你个人负责哪一部分？", "如何验证结果？"],
             "answer_structure": ["说明已确认的背景", "说明个人行动与依据"], "sample_source_ids": [projects[i % len(projects)]["id"]],
             "missing": ["请补充实际决策依据和复盘"]} for i in range(count)]}
    turns = payload["transcript"]
    if "JSON Schema:" in system and '"NextQuestion"' in system:
        count = len(turns)
        last = turns[-1] if turns else None
        return {"text": "请介绍你与目标岗位最相关的一段经历。" if not last else
                f"你刚才提到“{(last.get('answer') or '暂时跳过')[:50]}”，请进一步说明第{count}轮的判断依据？",
                "stage": "introduction" if not count else "deep_dive" if count < 4 else "scenario" if count < 7 else "candidate_questions",
                "topic_id": payload["topics"][(count // 2) % len(payload["topics"])]["id"], "is_follow_up": bool(count % 2) and not bool(last and last.get("skipped")),
                "suggest_finish": count >= 7}
    answered = [t for t in turns if t.get("answer") and not t.get("skipped")]
    evidence = [{"turn_id": answered[0]["id"], "quote": answered[0]["answer"][:50]}] if answered else []
    return {
        "summary": "本轮已完成，基于实际回答提供练习反馈。", "hr_feedback": "建议更明确地解释求职动机及协作边界。",
        "interviewer_feedback": "建议解释选择方案的依据与验证过程。",
        "dimensions": [{"key": key, "score": 75 if answered else None, "comment": "已给出部分行动依据。" if answered else "尚未充分考察。",
                        "evidence": evidence} for key in ("evidence", "professional", "job_match", "communication", "reflection")],
        "strengths": [{"title": "能说明个人行动", "advice": "保留这段具体行动，再解释判断依据。", "evidence": evidence}] if answered else [],
        "improvements": [{"title": "补充验证过程", "advice": "在行动之后说明如何检查结果，并指出实际局限。", "evidence": evidence}] if answered else [],
        "optimized_answers": [{"turn_id": answered[0]["id"], "answer_excerpt": answered[0]["answer"][:50],
                               "structure": ["解释背景", "说明行动与验证"], "source_ids": ["s1"], "missing": ["请补充实际验证步骤"]}] if answered else [],
        "recommendations": [{"topic_id": "topic-1", "action": "回到个人贡献主题，补充一次有依据的决策说明。"}],
    }
