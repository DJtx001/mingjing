import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

# 支持两种启动方式：python -m app.main（推荐）/ python app/main.py
# 直接运行脚本时 sys.path[0] 是 app/ 目录，手动把项目根加回来才能 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import logging

from app.api import cases, assist, auth, kb, logs

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
        llm = provider._init_cloud()

        # 关键：_init_cloud 只创建对象，不建立 TCP 连接。
        # 必须真正发一次请求，httpx 连接池才会建好 DNS+TCP+TLS，
        # 这样用户的第一次对话才能复用连接，省去 ~500ms 握手开销。
        # 用 daemon 线程后台预热：不阻塞启动（网络再慢也是秒起）；
        # daemon 线程不阻止进程退出（reload 时不会被挂起的 HTTP 请求拖住）。
        def _warmup_call():
            try:
                llm.invoke([{"role": "user", "content": "hi"}])
                logger.info("warmup: LLM 连接已建立（httpx 连接池就绪）")
            except Exception as e:
                logger.warning("warmup: LLM 预热失败（不影响使用，首次对话时再建连）: %s", e)

        threading.Thread(target=_warmup_call, daemon=True).start()
    except Exception as e:
        logger.warning("warmup: LLM 预热初始化失败: %s", e)

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
app.include_router(kb.router)
app.include_router(logs.router)

# 知识库配置表幂等建表（kb_rule/kb_schema/kb_prompt；法条/案例走 OSS+Chroma，不建表）
try:
    kb.init_tables()
except Exception as _e:
    logger.warning("kb 建表失败（不影响启动，接口调用时会报数据库错误）: %s", _e)

# 操作日志表幂等建表（audit_log）
try:
    logs.init_tables()
except Exception as _e:
    logger.warning("logs 建表失败（不影响启动，接口调用时会报数据库错误）: %s", _e)

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
    # timeout_graceful_shutdown=3：重启/重载时最多等 3 秒优雅关闭，
    # 防止旧 worker 因挂起的长连接一直不退出、热重载换不上新代码
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True,
                timeout_graceful_shutdown=3)
