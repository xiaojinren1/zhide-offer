"""省份信源模板：选一个省，启用它的招聘公告源。

模板放在 `backend/data/jobs/province_sources.json`，`verified` 字段记录实测结论：
true 表示能直连且首页含招聘/公告链接；false 表示当前抓不到（WAF、前端渲染或
域名不可达），需要在界面里手工换栏目页地址。**不臆造地址**——没验证的就标出来。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from engine.sources import base as sources_base

TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "data" / "jobs" / "province_sources.json"


@lru_cache(maxsize=1)
def _template() -> dict[str, Any]:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def default_config() -> dict[str, Any]:
    return dict(_template()["default_config"])


def list_provinces() -> list[dict[str, Any]]:
    """省份列表；返回副本，调用方随便改。"""
    return [dict(item) for item in _template()["provinces"]]


def find(code: str) -> dict[str, Any] | None:
    for item in _template()["provinces"]:
        if item["code"] == code:
            return dict(item)
    return None


def source_id(code: str) -> str:
    return f"prov-{code}"


def build_spec(code: str, *, url: str | None = None) -> sources_base.SourceSpec:
    """由一个省生成信源配置；url 可以覆盖模板地址（用户填了栏目页时）。"""
    province = find(code)
    if province is None:
        raise ValueError(f"未知省份代码：{code}")
    target = (url or province.get("url") or "").strip()
    if not target:
        raise ValueError(f"{province['name']} 还没有可用地址，请先填写招聘公告列表页")

    config = default_config()
    config["province"] = province["name"]
    config["province_code"] = province["code"]
    return sources_base.SourceSpec(
        id=source_id(code),
        name=f"{province['name']}人社厅招聘公告",
        kind="html_list",
        url=target,
        tier=1,
        license_note="政府公开信息",
        config=config,
    )


def enable(db: Any, code: str, *, url: str | None = None) -> sources_base.SourceSpec:
    """启用一个省：写入 feed_sources（重复启用只更新配置，不重复建源）。"""
    spec = build_spec(code, url=url)
    sources_base.upsert_spec(db, spec)
    db.execute("UPDATE feed_sources SET enabled = 1 WHERE id = ?", (spec.id,))
    return spec


def disable(db: Any, code: str) -> bool:
    cursor = db.execute(
        "UPDATE feed_sources SET enabled = 0 WHERE id = ? AND enabled = 1",
        (source_id(code),),
    )
    return cursor.rowcount > 0
