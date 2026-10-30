"""服务冒烟测试：起 FastAPI → 打 /api/health → 打一个不存在的路由验证 404 不崩 → 退出。"""
import sys
import threading
import time
import urllib.request
import json

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import uvicorn  # noqa: E402
from main import app  # noqa: E402

results = []


def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8123, log_level="warning")


t = threading.Thread(target=run_server, daemon=True)
t.start()
time.sleep(3)


def get(path):
    """返回 (status, body)。非 2xx 也返回真实状态码（不抛）。"""
    import urllib.error
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:8123{path}", timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return None, str(e)


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    results.append(cond)


st, body = get("/api/health")
check("服务可起 + /api/health 200", st == 200, f"status={st} body={str(body)[:200]}")
check("health 含 model/llm_configured/token_usage",
      isinstance(body, dict) and "model" in body and "llm_configured" in body and "token_usage" in body,
      str(body)[:200])

st2, body2 = get("/api/no-such-route")
check("未知 /api 路由返回 JSON 404（不回 HTML）",
      st2 == 404 and isinstance(body2, dict) and body2.get("ok") is False,
      f"status={st2} body={str(body2)[:120]}")

st3, body3 = get("/")
# / 返回的是 HTML，get() 的 JSON 解析必然失败——单独用原始请求验证
root_ok = False
root_detail = ""
try:
    import urllib.request as _u
    with _u.urlopen("http://127.0.0.1:8123/", timeout=10) as r:
        raw = r.read(400).decode(errors="replace")
        root_ok = r.status == 200 and ('<div id="root">' in raw or "<html" in raw)
        root_detail = f"status={r.status} html={'<html' in raw}"
except Exception as e:
    root_detail = str(e)
check("dist 存在时 / 返回 index.html（SPA 托管生效）", root_ok, root_detail)

st4, body4 = get("/api/quality")
check("未知 /api/quality 也回 JSON 404（不回 HTML）",
      st4 == 404 and isinstance(body4, dict) and body4.get("ok") is False,
      f"status={st4} body={str(body4)[:120]}")

print()
print("RESULT: ALL PASS" if all(results) else f"RESULT: {results.count(False)} FAILURE(S)")
sys.exit(0 if all(results) else 1)
