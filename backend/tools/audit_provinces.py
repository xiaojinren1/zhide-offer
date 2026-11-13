"""省份信源巡检：逐个实测，如实标注 verified，不臆造可用性。

用法（在仓库根目录）：

    .venv/bin/python backend/tools/audit_provinces.py            # 只检查，不改文件
    .venv/bin/python backend/tools/audit_provinces.py --write    # 把结果写回模板

判定口径：
- `verified = true` 只代表"当前出口网络下，该地址能抓到至少 1 条像样的岗位公告"；
- 403 / 412 / 证书错误 / 连接失败一律标 false，并在 `note` 写清原因；
- 抓到了但内容太短（导航页、报名入口）也算 false，并提示换栏目页。

为什么不做成定时任务：无人值守的批量抓取会带来封 IP 与脏数据无人纠正的问题（见 AGENTS.md）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import accounts  # noqa: E402
from engine.sources import base as sources_base, provinces  # noqa: E402


def _reason(result: dict) -> str:
    error = str(result.get("error") or "").strip()
    if error:
        low = error.lower()
        if "403" in low:
            return "站点返回 403，可能拦截了服务器出口 IP；需要换栏目页或代理"
        if "412" in low:
            return "站点返回 412（反爬校验），需人工确认可用地址"
        if "404" in low:
            return "地址返回 404，官网已改版，需要重新确认栏目页"
        if "certificate" in low or "ssl" in low:
            return "证书校验失败，需人工确认站点证书"
        return f"抓取失败：{error[:80]}"
    if not result.get("ok"):
        return "抓取未成功，原因未知，需人工复测"
    if int(result.get("skipped") or 0) > 0 and int(result.get("created") or 0) + int(result.get("updated") or 0) == 0:
        return "页面能打开但没有抓到足够长的正文，可能存的是导航页，需要换栏目页地址"
    return ""


def _verdict(result: dict) -> str:
    """三态判断：可用 / 不可用 / 判不出来。

    "能连上但这轮没有新公告"属于第三种：不能因为今天没更新就把可用源标成不可用，
    也不能凭连接成功就认定长期可用。写回时保留原状态，只记一条备注。
    """
    if not result.get("ok") or str(result.get("error") or "").strip():
        return "unusable"
    if int(result.get("created") or 0) + int(result.get("updated") or 0) > 0:
        return "usable"
    return "inconclusive"


def audit(*, interval: float = 0.8, limit: int | None = None) -> list[dict]:
    reports: list[dict] = []
    templates = provinces.list_provinces()
    if limit:
        templates = templates[:limit]
    with accounts.connection() as db:
        for index, province in enumerate(templates):
            try:
                spec = provinces.build_spec(province["code"])
            except ValueError as exc:
                # 模板里没填地址的省份（如西藏）直接记为不可用，不让巡检中断
                reports.append({
                    "code": province["code"], "name": province["name"], "url": "",
                    "ok": False, "created": 0, "updated": 0, "skipped": 0, "seconds": 0,
                    "reason": str(exc), "verdict": "unusable",
                })
                print(f"[SKIP] {province['name']:4s} · {exc}")
                continue
            started = time.time()
            result = sources_base.run_source(db, spec)
            reports.append({
                "code": province["code"],
                "name": province["name"],
                "url": spec.url,
                "ok": bool(result.get("ok")),
                "created": int(result.get("created") or 0),
                "updated": int(result.get("updated") or 0),
                "skipped": int(result.get("skipped") or 0),
                "seconds": round(time.time() - started, 1),
                "reason": _reason(result),
                "verdict": _verdict(result),
            })
            print(f"[{'OK  ' if result.get('ok') else 'FAIL'}] {province['name']:4s} "
                  f"{result.get('created', 0)}+{result.get('updated', 0)} "
                  f"{('· ' + reports[-1]['reason']) if reports[-1]['reason'] else ''}")
            if index < len(templates) - 1:
                time.sleep(interval)
    return reports


def default_template_path() -> Path:
    return Path(__file__).resolve().parents[2] / "backend" / "data" / "jobs" / "province_sources.json"


def write_back(reports: list[dict], path: Path | None = None) -> Path:
    """把实测结果写回模板文件：只改 verified 与 note，不动地址。"""
    path = path or default_template_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    key = "provinces" if "provinces" in data else None
    items = data[key] if key else data
    by_code = {item["code"]: item for item in items}
    for report in reports:
        item = by_code.get(report["code"])
        if item is None:
            continue
        verdict = report.get("verdict") or ("usable" if report["ok"] else "unusable")
        if verdict == "usable":
            item["verified"] = True
            item.pop("note", None)
        elif verdict == "unusable":
            item["verified"] = False
            item["note"] = report["reason"] or "本轮抓取失败，需人工复测"
        else:
            # 判不出来：保留原来的 verified，只在还没有备注时补一条说明
            item.setdefault("note", "本轮能连上但没有新公告，建议隔几天再测")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="省份信源地址巡检")
    parser.add_argument("--write", action="store_true", help="把结果写回 province_sources.json")
    parser.add_argument("--limit", type=int, default=None, help="只测前 N 个省，便于快速抽查")
    args = parser.parse_args(argv)

    reports = audit(limit=args.limit)
    usable = [item for item in reports if item.get("verdict") == "usable"]
    unusable = [item for item in reports if item.get("verdict") == "unusable"]
    other = len(reports) - len(usable) - len(unusable)
    print()
    print(f"实测可用 {len(usable)} 个 · 抓不到 {len(unusable)} 个 · 能连上但无新公告 {other} 个（共 {len(reports)} 个省）")
    if args.write:
        path = write_back(reports)
        print(f"已写回 {path}")
    else:
        print("（未写回文件；需要更新模板时加 --write）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
