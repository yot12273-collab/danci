# -*- coding: utf-8 -*-
"""FastAPI 应用入口：装配路由、静态资源、全局异常处理与启动初始化。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routers import history, import_docx, quiz, recite, tags, words
from .schemas.common import AppError, ERR_INTERNAL, ERR_VALIDATION


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时建表（幂等），退出时无需特殊清理。"""
    init_db()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
)

# 静态资源（前端页面），挂载到 /static
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")


# ---------- 全局异常处理（统一响应信封） ----------
@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, _exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"code": ERR_VALIDATION, "message": "参数校验失败", "data": None},
    )


@app.exception_handler(Exception)
async def generic_error_handler(_request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": ERR_INTERNAL, "message": f"服务器内部错误：{exc}", "data": None},
    )


# ---------- 业务路由 ----------
app.include_router(words.router)
app.include_router(tags.router)
app.include_router(history.router)
app.include_router(import_docx.router)
app.include_router(quiz.router)
app.include_router(recite.router)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(settings.static_dir / "index.html"))


@app.get("/api/health", include_in_schema=False)
def health():
    return {"code": 0, "message": "ok", "data": {"status": "ok"}}


if __name__ == "__main__":
    import uvicorn

    # 绑定 0.0.0.0，便于局域网内 iPhone 访问
    uvicorn.run(app, host="0.0.0.0", port=8000)
