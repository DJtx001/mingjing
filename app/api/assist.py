"""H组 AI 助手接口（严格对齐《受理Agent接口文档》V1.1 H组，页⑥全局组件）
红线：知识库无命中时必须输出"知识库暂无依据"，禁止编造（页⑥）
"""
import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.llm.provider import provider
from app.services import session_service

router = APIRouter(prefix="/assist", tags=["H-AI助手"])

SYSTEM_PROMPT = (
    "你是「明镜」受理工位 AI 助手，服务对象是人民调解受理员，不是当事人。"
    "回答基于当前案件要素与知识库检索，所有引用必须可溯源；"
    "知识库无命中时必须明确输出『知识库暂无依据』，禁止编造；"
    "拒绝过多的闲聊"
)


class ChatRequest(BaseModel):
    session_id: Optional[str] = None   # 可空：新会话；携带则续上下文
    case_id: Optional[str] = None      # 可空：携带则注入本案要素上下文
    message: str


class AdoptRequest(BaseModel):
    case_id: str
    from_reply_id: str
    citation_type: str                 # law 法条 / similar_case 类案 / reasoning 释法说理话术
    ref_id: Optional[str] = None       # citation_type=reasoning 时为空
    content: str
    target: str                        # similar_case_doc 类案参考 / case_note 案件备注


def _sse_stream(session_id: str, body: ChatRequest):
    """SSE 流生成器（同步）。

    用同步生成器 + StreamingResponse，FastAPI/uvicorn 会自动把它放进线程池迭代，
    不阻塞事件循环。每个 LLM token 到达就立刻 yield 一个 delta 事件，前端实时渲染。
    """
    # 从 Redis 取近 10 轮消息（旧→新顺序），拼进 prompt
    history = session_service.get_messages(session_id)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": body.message})

    # 用户消息写入 Redis（追加到会话）
    session_service.append_message(session_id, "user", body.message)

    yield f"event:start\ndata: {json.dumps({'session_id': session_id}, ensure_ascii=False)}\n\n"

    t0 = time.time()
    full_text = []
    try:
        # 真流式：provider.stream 逐 token yield，收到一个就推一个 delta
        for chunk in provider.stream(messages):
            full_text.append(chunk)
            yield f"event:delta\ndata: {json.dumps({'delta': chunk}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"event:error\ndata: {json.dumps({'error': {'code': 'LLM_001', 'message': str(e)}}, ensure_ascii=False)}\n\n"
        return
    latency_ms = int((time.time() - t0) * 1000)
    text = "".join(full_text)

    # TODO(数据收集完成后)：检索命中时推送 citations 事件（法条/类案引用卡片）
    citations: list = []
    yield "event:citations\ndata: " + json.dumps({"citations": citations}, ensure_ascii=False) + "\n\n"

    # assistant 消息写入 Redis（带 reply_id 和 citations，供采纳回流定位）
    reply_id = "rep_" + uuid.uuid4().hex[:4]
    session_service.append_message(
        session_id, "assistant", text,
        reply_id=reply_id, citations=citations,
    )
    yield f"event:done\ndata: {json.dumps({'reply_id': reply_id}, ensure_ascii=False)}\n\n"


def provider_model() -> str:
    from app.core.config import config
    return config.CLOUD_MODEL if provider._cloud_available() else config.OLLAMA_MODEL


@router.post("/chat")
async def chat(body: ChatRequest, user: dict = Depends(get_current_user)):
    """H1 对话问答（SSE 流式）。需要登录。"""
    user_id = user["user_id"]
    if body.session_id:
        # 续聊：校验会话归属，防止越权访问别人的会话
        if not session_service.check_owner(body.session_id, user_id):
            raise HTTPException(status_code=403,
                                detail={"code": "AUTHZ_001", "message": "无权访问该会话"})
        session_id = body.session_id
    else:
        # 新会话：用 session_service 创建（写用户索引 + 会话元数据）
        session_id = session_service.create_session(user_id, body.case_id)

    return StreamingResponse(
        _sse_stream(session_id, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/adopt")
async def adopt(body: AdoptRequest, user: dict = Depends(get_current_user)):
    """H2 采纳回流：引用卡片一键写入案件（类案参考草案 / 案件备注）"""
    # TODO(建库后)：落 assist_adoption 表 + 写入目标文档
    return {"target": body.target, "doc_id": "doc_" + uuid.uuid4().hex[:4],
            "appended": True, "by": user["user_id"]}


@router.get("/sessions")
async def list_sessions(case_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    """H3 会话列表（恢复抽屉用）。只返回当前用户的会话。"""
    sessions = session_service.list_user_sessions(user["user_id"])
    if case_id:
        sessions = [s for s in sessions if s.get("case_id") == case_id]
    items = []
    for s in sessions:
        # 取最后一条消息做摘要
        msgs = session_service.get_messages(s["session_id"])
        last = msgs[-1]["content"][:30] if msgs else ""
        items.append({
            "session_id": s["session_id"],
            "case_id": s.get("case_id"),
            "last_message": last,
            "updated_at": s.get("updated_at"),
        })
    return {"items": items}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user: dict = Depends(get_current_user)):
    """H4 清空会话（已采纳内容不受影响）。校验归属后删除。"""
    if not session_service.check_owner(session_id, user["user_id"]):
        raise HTTPException(status_code=403,
                            detail={"code": "AUTHZ_001", "message": "无权操作该会话"})
    session_service.delete_session(session_id)
    return {"deleted": True}


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, user: dict = Depends(get_current_user)):
    """H5 会话历史消息。校验归属后返回。"""
    if not session_service.check_owner(session_id, user["user_id"]):
        raise HTTPException(status_code=403,
                            detail={"code": "AUTHZ_001", "message": "无权访问该会话"})
    return {"messages": session_service.get_messages(session_id)}
