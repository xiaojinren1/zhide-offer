"""模型可调用的工具集（Agent 的手脚）。

设计原则（来自 ARC 教训 + Pi 的"给原语"）：
- 工具必须**程序可判**：返回结构化结果，不返回"看起来对"的文字
- 工具描述写清"什么时候该用、输入输出是什么"，否则模型不会调
- 执行器永不抛异常到模型之外——工具失败应以结果形式返回给模型
"""
from __future__ import annotations

from typing import Any, Callable

TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "check_resume_quality",
            "description": (
                "检查你刚写出的定制简历，返回可复核的问题清单（虚构数字、套话、"
                "JD 关键词覆盖率、时间线重叠/空窗、无量化、技能无支撑）。"
                "**每写完一版简历必须调用**，然后按 issues 里的 fix 逐条修订；"
                "修订后再调一次，直到 ok 为 true 或没有 high 级问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "resume_markdown": {
                        "type": "string",
                        "description": "待检查的简历正文（Markdown）",
                    }
                },
                "required": ["resume_markdown"],
            },
        },
    },
]


def build_executor(
    *,
    profile,
    jd_keywords: list[str],
) -> tuple[Callable[[str, dict], dict], list[str]]:
    """构造工具执行器。返回 (executor, 可用工具名列表)。

    executor(name, args) -> dict：工具失败也返回 {"error": ...} 而不抛异常，
    让模型自己决定怎么办（工具失败不该杀死整个生成流程）。
    """
    from engine.quality_check import check_markdown

    calls: list[str] = []

    def _exec(name: str, args: dict) -> dict:
        calls.append(name)
        if name != "check_resume_quality":
            return {"error": f"unknown tool: {name}"}
        md = str((args or {}).get("resume_markdown") or "")
        if not md.strip():
            return {"error": "resume_markdown 不能为空"}
        try:
            return check_markdown(md, profile, jd_keywords)
        except Exception as exc:  # 工具失败不杀死流程
            return {"error": f"quality check failed: {exc}"}

    return _exec, calls
