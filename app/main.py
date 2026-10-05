from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import logging

from app.api import cases, assist, auth

logger = logging.getLogger("warmup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动预热：把首次请求的初始化开销提前到启动阶段。

    预热内容：
    - Redis 连接池建第一条连接
    - LLM 客户端（ChatOpenAI + httpx 连接池）初始化
    这样用户的第一次对话请求就不会因为冷启动而变慢。
    """
    try:
        from app.core.redis import get_redis
        get_redis().ping()
        logger.info("warmup: Redis 连接已建立")
    except Exception as e:
        logger.warning("warmup: Redis 预热失败（不影响启动）: %s", e)

    try:
        from app.llm.provider import provider
        provider._init_cloud()
        logger.info("warmup: LLM 客户端已初始化")
    except Exception as e:
        logger.warning("warmup: LLM 客户端预热失败（不影响启动）: %s", e)

    yield


app = FastAPI(title="明镜·要素式智能受理系统", version="0.1.0", lifespan=lifespan)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """把 401/403 的 detail 统一包成 {error: {code, message}} 结构。"""
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "ERR", "message": str(exc.detail)}},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(assist.router)

# 前端为 Vite 工程（frontend/）：生产产物在 frontend/dist，由后端同源托管
# 必须放在所有 API 路由注册之后；dist 不存在时（未执行 npm run build）给出提示
DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return {"message": "前端未构建：开发期请访问 http://localhost:5173 ，或在 frontend/ 执行 npm run build"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
