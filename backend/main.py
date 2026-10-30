"""职得offer 本机开发服务入口，必要路由导入失败时明确终止启动。"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from core import budget, events  # noqa: E402
from core.config import settings  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = settings()
    events.configure(cfg["events_path"])
    events.emit("server_started", model=cfg["model"], port=cfg["port"])
    yield
    events.emit("server_stopped")


app = FastAPI(title="职得offer", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 必要路由直接注册；依赖错误必须阻止启动 ----


for module_path in ("api.diagnose", "api.resume", "api.quality", "api.interview", "api.profiles"):
    module = __import__(module_path, fromlist=["router"])
    app.include_router(module.router)


@app.get("/api/health")
def health():
    cfg = settings()
    from core.llm import is_configured

    return {
        "ok": True,
        "model": cfg["model"],
        "llm_configured": is_configured(),
        "token_usage": budget.get_usage(),
    }


@app.exception_handler(Exception)
async def unhandled(_request, exc: Exception):
    """保命层：未捕获异常也返回 JSON，不让进程崩掉。"""
    events.emit_error("unhandled", exc)
    return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)[:500]})


# ---- 前端静态托管（SPA fallback，逻辑照抄老模板 app.js） ----

DIST = PROJECT_ROOT / "frontend" / "dist"

if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        from fastapi.responses import FileResponse

        # 未知 /api/* 路由必须回 JSON 404：否则前端会把 index.html 当 API 响应，
        # JSON 解析报一个看不懂的错（dist 存在后才会暴露，特此显式处理）。
        if full_path.startswith("api/") or full_path == "api":
            return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown api route: /{full_path}"})
        index = DIST / "index.html"
        if not index.is_file():
            return JSONResponse(
                status_code=503,
                content={"ok": False, "error": "Frontend Build Missing"},
            )
        return FileResponse(str(index))
else:
    @app.get("/")
    def no_dist():
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "Frontend Build Missing",
                "hint": "先在 frontend/ 跑 npm install && npm run build 生成 dist",
            },
        )


def main() -> None:
    try:
        import uvicorn

        cfg = settings()
        uvicorn.run(app, host="127.0.0.1", port=cfg["port"], log_level="info")
    except Exception as exc:
        events.emit_error("server_start", exc)
        print(f"[jobagent] server failed to start: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
