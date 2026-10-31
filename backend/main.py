"""职得offer 本机开发服务入口，必要路由导入失败时明确终止启动。"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import Depends, FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.exception_handlers import request_validation_exception_handler  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from core import accounts, budget, events  # noqa: E402
from core.config import settings  # noqa: E402
from core.llm import LLMError  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = settings()
    events.configure(cfg["events_path"])
    events.emit("server_started", model=cfg["model"], port=cfg["port"])
    yield
    events.emit("server_stopped")


app = FastAPI(title="职得offer", version="0.1.0", lifespan=lifespan)


@app.exception_handler(LLMError)
async def model_error(_request: Request, exc: LLMError):
    messages = {
        429: "模型服务请求过于频繁或额度不足，请稍后重试",
        502: "模型返回的内容为空或格式无效，请重试",
        503: "模型服务暂不可用，请检查模型配置或服务状态后重试",
        504: "模型处理超时，请稍后重试",
    }
    status_code = exc.status_code if exc.status_code in messages else 503
    events.emit("model_request_failed", status_code=status_code)
    return JSONResponse(status_code=status_code, content={"detail": messages[status_code]})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/auth/"):
        # 默认校验响应包含 input，账户入口禁止将提交的密码回显给浏览器。
        return JSONResponse(status_code=422, content={
            "detail": "用户名需为3–32位英文字母、数字或下划线；密码需为8–128个字符",
        })
    return await request_validation_exception_handler(request, exc)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Requested-With"],
)

# ---- 必要路由直接注册；依赖错误必须阻止启动 ----


from api.auth import router as auth_router  # noqa: E402

app.include_router(auth_router)

for module_path in ("api.diagnose", "api.resume", "api.quality", "api.interview", "api.profiles",
                    "api.workspace", "api.interview_records", "api.export"):
    module = __import__(module_path, fromlist=["router"])
    app.include_router(module.router, dependencies=[Depends(accounts.require_user), Depends(accounts.require_csrf)])


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
