"""范例检索（脚本式检查）：资料层优先、种子回退、写法三件套不泄露内部字段。

用法：.venv/bin/python tests/run_examples_qa.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

FAILURES: list[str] = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


from core import accounts  # noqa: E402
from engine.knowledge import examples  # noqa: E402

tmp = tempfile.TemporaryDirectory(prefix="qa-examples-")
original_path = accounts.DATABASE_PATH
accounts.DATABASE_PATH = Path(tmp.name) / "examples.sqlite3"
try:
    with accounts.connection() as db:
        seeded = examples.seed(db)
        check("种子导入资料层", seeded >= 25, f"{seeded} 条")
        check("重复导入幂等", examples.seed(db) == 0)
        check("count() 读资料层", examples.count(db) == seeded, str(examples.count(db)))

        hits = examples.retrieve(db, "数据开发工程师，负责数仓建设与指标口径治理", ["数据开发", "数仓"], top_k=3)
        check("能检索到范例", len(hits) > 0, str(len(hits)))
        check("只返回写法三件套", all(set(item) == {"id", "weak", "strong", "technique"} for item in hits),
              str([sorted(item) for item in hits][:2]))
        check("按相关度降序稳定", hits == examples.retrieve(db, "数据开发工程师，负责数仓建设与指标口径治理",
                                                        ["数据开发", "数仓"], top_k=3))

        with db:
            db.execute("UPDATE documents SET visibility = 'private' WHERE kind = 'example'")
        fallback = examples.retrieve(db, "数据开发工程师，负责数仓建设", ["数据开发"], top_k=2)
        check("资料层无可用范例时回退种子", len(fallback) > 0, str(len(fallback)))

    empty = Path(tmp.name) / "empty.sqlite3"
    accounts.DATABASE_PATH = empty
    with accounts.connection() as db:
        db.execute("DELETE FROM documents WHERE kind = 'example'")
        got = examples.retrieve(db, "数据开发", [], top_k=2)
    check("库为空也不抛异常", isinstance(got, list))
finally:
    accounts.DATABASE_PATH = original_path
    tmp.cleanup()

print()
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("RESULT: EXAMPLES ALL CHECKS PASSED")
