"""读事件流做错误统计：把 `data/events.jsonl` 变成管理员能看的趋势与分类。

三条边界（对应 AGENTS.md 与 MODELS_ERRORS.md）：

- **只读不写**：统计不改事件文件，也不往库里落新表。
- **不泄露内容**：事件里可能带着材料片段、上游响应摘要甚至凭据，所以对外只给
  时间、功能入口、错误分类和一个排查编号；原文一律不出后台。
- **分类按状态码与异常类型判断**，不看上游响应正文——正文是别人给的，不可信。

事件文件的形态是"一行一个 JSON"，历史可能很长，因此读取只从尾部按字节截断，
不会把整个文件读进内存。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 尾部最多读这么多字节：约等于最近若干万条事件，够统计趋势又不吃内存
MAX_TAIL_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 20000

# 错误分类：id -> 展示名 + 说明（说明给管理员看，不含原始错误文本）
CATEGORIES: dict[str, dict[str, str]] = {
    "model_timeout": {"label": "模型超时", "hint": "上游响应慢或流程预算耗尽，可重试或调大 JOBAGENT_FLOW_DEADLINE"},
    "model_rate_limited": {"label": "模型限流", "hint": "上游 429，稍后重试或换供应商"},
    "model_auth": {"label": "模型鉴权失败", "hint": "Key 无效或无权限，检查模型设置"},
    "model_unreachable": {"label": "模型连接失败", "hint": "网络或上游不可达，检查 Base URL 与出网"},
    "model_bad_output": {"label": "模型输出不可用", "hint": "空响应/非 JSON/结构不符，可繁忙时重试"},
    "model_unavailable": {"label": "模型服务异常", "hint": "上游 5xx 或供应商故障"},
    "config_missing": {"label": "配置缺失", "hint": "用户没有启用对应模型，属正常提示，不是故障"},
    "validation": {"label": "输入校验失败", "hint": "用户输入不符合要求，非系统故障"},
    "not_found": {"label": "资源不存在", "hint": "资料/卡片被删或无权访问"},
    "forbidden": {"label": "权限不足", "hint": "非管理员或账号不匹配"},
    "unhandled": {"label": "未捕获异常", "hint": "程序错误，需要看服务端日志定位"},
    "other": {"label": "其他错误", "hint": "未归类的失败"},
}

# 只统计"最终失败"的事件。`llm_provider_failed` 是单次尝试失败，随后可能已成功切换，
# 混进失败数会让管理员以为全线故障——它单独算"重试次数"。
_ERROR_TYPES = {"error", "model_request_failed", "llm_chain_deadline",
                "llm_flow_deadline", "diagnose_model_validation_failed", "unhandled"}
_RETRY_TYPES = {"llm_provider_failed", "llm_tool_round_failed", "llm_flow_degraded"}

# 功能入口：事件里的 stage / type 前缀 → 给管理员看的功能名
_FEATURES: tuple[tuple[str, str], ...] = (
    ("resume_image", "简历图片解析"),
    ("jobs_screenshot", "岗位截图导入"),
    ("jobs_import", "岗位导入"),
    ("resume_parse", "简历解析"),
    ("resume_generate", "简历生成"),
    ("resume_revise", "简历修订"),
    ("diagnose", "岗位诊断"),
    ("quality", "简历质检"),
    ("tailoring", "岗位定制"),
    ("interview", "模拟面试"),
    ("export", "导出"),
    ("model", "模型调用"),
    ("llm", "模型调用"),
    ("server", "服务启动"),
    ("pipeline", "一键链路"),
    ("community", "社群"),
    ("jobs", "岗位收件箱"),
    ("unhandled", "未分类"),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def event_path() -> Path:
    """事件文件位置：与 `core.events.configure()` 一致，默认 data/events.jsonl。"""
    configured = os.environ.get("JOBAGENT_EVENTS_PATH", "").strip()
    if configured:
        return Path(configured)
    from core.config import settings

    try:
        return Path(settings()["events_path"])
    except Exception:  # 配置读取失败时退回默认路径，统计不该因此 500
        return Path("data") / "events.jsonl"


def _read_tail(path: Path) -> list[dict[str, Any]]:
    """从文件尾部按字节截断读取，避免把很大的历史文件整体读入。"""
    if not path.is_file():
        return []
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > MAX_TAIL_BYTES:
                fh.seek(size - MAX_TAIL_BYTES)
                fh.readline()  # 丢掉被截断的半行
            raw = fh.read()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue  # 损坏行直接跳过，不让统计整页报错
        if isinstance(item, dict):
            records.append(item)
    return records[-MAX_RECORDS:]


def _parse_time(value: object) -> datetime | None:
    """事件时间是 UTC 的 `YYYY-mm-dd HH:MM:SS`。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


_PATH_FEATURES: tuple[tuple[str, str], ...] = (
    ("/resume/parse-image", "简历图片解析"),
    ("/resume/template", "简历版式识别"),
    ("/resume/generate", "简历生成"),
    ("/resume/revise", "简历修订"),
    ("/resume/parse", "简历解析"),
    ("/jobs/parse-image", "岗位截图导入"),
    ("/jobs/import", "岗位导入"),
    ("/jobs", "岗位收件箱"),
    ("/diagnose", "岗位诊断"),
    ("/quality", "简历质检"),
    ("/interview", "模拟面试"),
    ("/export", "导出"),
    ("/model-preferences", "模型设置"),
    ("/community", "社群"),
    ("/feedback", "站内反馈"),
)


def feature_from_path(path: object) -> str:
    """按接口路径判断功能入口；路径只用于归类，不进返回体。"""
    value = str(path or "")
    for prefix, label in _PATH_FEATURES:
        if prefix in value:
            return label
    return ""


def feature_of(event: dict[str, Any]) -> str:
    by_path = feature_from_path(event.get("path"))
    if by_path:
        return by_path
    stage = str(event.get("stage") or "").lower()
    etype = str(event.get("type") or "").lower()
    for prefix, label in _FEATURES:
        if stage.startswith(prefix) or etype.startswith(prefix):
            return label
    return "其他"


def classify(event: dict[str, Any]) -> str | None:
    """把一条事件归到错误分类；不是错误事件返回 None。"""
    etype = str(event.get("type") or "")
    if etype not in _ERROR_TYPES and etype != "error":
        return None
    if etype in ("llm_chain_deadline", "llm_flow_deadline"):
        return "model_timeout"
    if etype == "diagnose_model_validation_failed":
        return "model_bad_output"
    stage = str(event.get("stage") or "").lower()
    if etype == "unhandled" or stage == "unhandled":
        return "unhandled"
    status = event.get("status_code")
    try:
        code = int(status) if status is not None else None
    except (TypeError, ValueError):
        code = None
    if code == 428:
        return "config_missing"
    if code == 429:
        return "model_rate_limited"
    if code in (401, 403):
        return "model_auth"
    if code == 404:
        return "not_found"
    if code == 422:
        return "validation"
    if code == 502:
        return "model_bad_output"
    if code == 503:
        return "model_unreachable"
    if code == 504:
        return "model_timeout"
    if code is not None and 500 <= code < 600:
        return "model_unavailable"
    # 没有状态码时按阶段猜：生成/解析类失败更可能是模型不可用
    if any(key in stage for key in ("generate", "parse", "diagnose", "quality", "tailor", "interview")):
        return "model_unavailable"
    return "other"


def trace_id(event: dict[str, Any]) -> str:
    """排查编号：由类型与阶段算出的稳定短码，不含时间与内容，便于对照日志。"""
    seed = f"{event.get('type')}|{event.get('stage')}|{event.get('category', '')}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]


def _bucket(dt: datetime) -> str:
    """按北京时间自然日聚合，与后台其它统计口径一致。"""
    return (dt + timedelta(hours=8)).date().isoformat()


def summarize(path: Path | None = None, *, days: int = 7, sample_limit: int = 20) -> dict[str, Any]:
    """聚合近 N 天（以及最近 24 小时）的错误趋势与分类。"""
    target = path or event_path()
    now = _now()
    start = now - timedelta(days=max(1, min(days, 30)))
    day_start = now - timedelta(hours=24)

    records = _read_tail(target)
    total_events = 0
    retries = {"24h": 0, "window": 0}
    totals = {"24h": 0, "window": 0}
    by_category: dict[str, dict[str, int]] = {"24h": {}, "window": {}}
    by_feature: dict[str, dict[str, int]] = {"24h": {}, "window": {}}
    daily: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    for event in records:
        moment = _parse_time(event.get("timestamp"))
        if moment is None or moment < start:
            continue
        total_events += 1
        if str(event.get("type") or "") in _RETRY_TYPES:
            retries["window"] += 1
            if moment >= day_start:
                retries["24h"] += 1
            continue
        category = classify(event)
        if category is None:
            continue
        feature = feature_of(event)
        in_day = moment >= day_start
        totals["window"] += 1
        by_category["window"][category] = by_category["window"].get(category, 0) + 1
        by_feature["window"][feature] = by_feature["window"].get(feature, 0) + 1
        daily[_bucket(moment)] = daily.get(_bucket(moment), 0) + 1
        if in_day:
            totals["24h"] += 1
            by_category["24h"][category] = by_category["24h"].get(category, 0) + 1
            by_feature["24h"][feature] = by_feature["24h"].get(feature, 0) + 1
        if len(samples) < sample_limit:
            samples.append({
                "time": (moment + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M"),
                "feature": feature,
                "category": category,
                "category_label": CATEGORIES.get(category, CATEGORIES["other"])["label"],
                "trace_id": trace_id(event),
            })

    dates = [(start + timedelta(days=offset)).date().isoformat() for offset in range(days)]
    return {
        "ok": True,
        "window_days": days,
        "events_scanned": total_events,
        "totals": totals,
        "retries": retries,
        "by_category": [
            {"id": key, "label": CATEGORIES.get(key, CATEGORIES["other"])["label"],
             "hint": CATEGORIES.get(key, CATEGORIES["other"])["hint"],
             "last24h": by_category["24h"].get(key, 0),
             "window": by_category["window"].get(key, 0)}
            for key in list(CATEGORIES) if by_category["window"].get(key)
        ],
        "by_feature": [
            {"feature": feature, "last24h": by_feature["24h"].get(feature, 0),
             "window": by_feature["window"][feature]}
            for feature in sorted(by_feature["window"], key=lambda name: -by_feature["window"][name])
        ],
        "daily": [{"date": day, "errors": daily.get(day, 0)} for day in dates],
        "samples": list(reversed(samples)),
    }


def recent_errors(limit: int = 50, path: Path | None = None) -> list[dict[str, Any]]:
    """最近 N 组错误的脱敏视图，供管理员排查。

    同一条 排查编号（同类型+同阶段）会连续刷很多行，所以这里按编号聚合成一组，
    只保留最近一次时间与次数——否则管理员看到的是一屏重复，等于没有信息。
    """
    target = path or event_path()
    records = _read_tail(target)
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for event in reversed(records):
        category = classify(event)
        if category is None:
            continue
        moment = _parse_time(event.get("timestamp"))
        feature = feature_of(event)
        key = (trace_id(event), feature, category)
        if key in groups:
            groups[key]["count"] += 1
            groups[key]["first_time"] = (moment + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if moment else groups[key]["first_time"]
            continue
        if len(groups) >= max(1, min(limit, 200)):
            break
        groups[key] = {
            "time": (moment + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S") if moment else "",
            "first_time": (moment + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M") if moment else "",
            "feature": feature,
            "category": category,
            "category_label": CATEGORIES.get(category, CATEGORIES["other"])["label"],
            "trace_id": key[0],
            "count": 1,
        }
        order.append(key)
    return [groups[key] for key in order]
