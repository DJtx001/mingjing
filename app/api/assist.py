"""H组 AI 助手接口（严格对齐《受理Agent接口文档》V1.1 H组，页⑥全局组件）
红线：知识库无命中时必须输出"知识库暂无依据"，禁止编造（页⑥）
"""
import json
import re
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.api.cases import _STATUS_LABEL as _STATUS_CN   # 状态中文映射（案件全貌卡片用）
from app.llm.provider import provider
from app.services import retrieval_service, session_service

router = APIRouter(prefix="/assist", tags=["H-AI助手"])

# ---------- 表结构（幂等创建） ----------
# assist_session / assist_message 为早期手工建表，此处补录基线 DDL 使新环境可自动建齐
# （CREATE IF NOT EXISTS 对已存在的表无副作用）；assist_adoption 为采纳回流新表。
# 注意：assist_adoption 刻意不加外键——设计红线"删除会话不影响已采纳内容"，
# 加 ON DELETE CASCADE 会误删采纳记录，RESTRICT 又会挡住删会话。
ASSIST_DDL = """
CREATE TABLE IF NOT EXISTS assist_session (
  session_id VARCHAR(20) NOT NULL,
  user_id VARCHAR(16) NOT NULL,
  case_id VARCHAR(24) DEFAULT NULL,
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (session_id),
  KEY idx_user_case (user_id, case_id),
  CONSTRAINT fk_session_user FOREIGN KEY (user_id) REFERENCES user (user_id) ON DELETE RESTRICT
) COMMENT='AI 助手会话';

CREATE TABLE IF NOT EXISTS assist_message (
  id BIGINT NOT NULL AUTO_INCREMENT,
  session_id VARCHAR(20) NOT NULL,
  role ENUM('user','assistant') NOT NULL,
  content TEXT NOT NULL,
  reply_id VARCHAR(20) DEFAULT NULL COMMENT 'assistant 消息的回复ID（采纳回流定位）',
  citations JSON DEFAULT NULL COMMENT '引用卡片快照',
  context JSON DEFAULT NULL COMMENT '运行元数据 {model, provider, latency_ms, no_evidence}',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_session (session_id, created_at),
  CONSTRAINT fk_msg_session FOREIGN KEY (session_id) REFERENCES assist_session (session_id) ON DELETE CASCADE
) COMMENT='AI 助手消息（真相源，Redis 过期后由此回放）';

CREATE TABLE IF NOT EXISTS assist_adoption (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(24) NOT NULL COMMENT '采纳到的案件',
  session_id VARCHAR(20) NOT NULL COMMENT '来源会话',
  from_reply_id VARCHAR(20) NOT NULL COMMENT '来源回复 rep_xxx（assist_message.reply_id）',
  citation_type ENUM('law','similar_case','reasoning') NOT NULL COMMENT '引用类型',
  ref_id VARCHAR(24) DEFAULT NULL COMMENT '引用对象ID（law_{id}/case_{id}；reasoning 为空）',
  content VARCHAR(1000) NOT NULL COMMENT '采纳内容快照（截断存）',
  target ENUM('similar_case_doc','case_note') NOT NULL COMMENT '采纳目标',
  target_doc_id VARCHAR(24) DEFAULT NULL COMMENT '目标载体ID（当前为 case_note.id；文书模块后为 doc_xxx）',
  operator_id VARCHAR(16) NOT NULL COMMENT '操作人 user_id',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_case (case_id, created_at),
  KEY idx_reply (from_reply_id),
  KEY idx_created (created_at)
) COMMENT='采纳回流记录（采纳率统计源；不加外键：删会话不影响已采纳）';
"""


def init_tables():
    import pymysql
    from app.core.config import config
    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor() as cur:
            for stmt in ASSIST_DDL.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()

SYSTEM_PROMPT = (
    "你是「明镜」受理工位 AI 助手，服务对象是人民调解受理员，不是当事人。"
    "下面随问题提供了知识库检索出的参考材料（如另有【本案信息】，请结合案件事实作答），"
    "请直接、简洁地基于材料作答：给出明确结论与依据，末尾用 [编号] 标注所引用的材料；"
    "材料未覆盖的部分不要编造；参考材料与问题无关时直接忽略，不要强行引用；拒绝闲聊。"
)

# 案件事实类短问（"这个案子现在什么情况/当事人是谁"）：有案件上下文时确定性直答案件全貌，
# 不走检索与 LLM——这类问题的检索距离与真法律问题重叠，硬检索只会引入无关材料
_CASE_QUERY = re.compile(
    r"(这个?案子?|本案|该案|案子).{0,12}(什么情况|什么状态|怎么样|什么进度|进展|是谁|叫什么|怎么办)")


def _load_case(case_id: Optional[str]) -> Optional[dict]:
    """案件感知：加载案件全貌（含陈述原文、要素表、核验命中、流转、备注）。"""
    if not case_id:
        return None
    from app.api.cases import _STATUS_LABEL, _TRIAGE
    from app.core.db import MySQLClient
    db = MySQLClient()
    try:
        rows = db.execute(
            "SELECT case_id, dispute_type, applicant_name, status, narrative FROM case_info"
            " WHERE case_id=%s", (case_id,))
        if not rows:
            return None
        c = rows[0]
        c["status_label"] = _STATUS_LABEL.get(c["status"], c["status"])
        c["triage"] = _TRIAGE.get(c["status"])
        # 案件实质内容：要素表（回答"案件要点"的依据）
        c["elements"] = db.execute(
            "SELECT name, value, quote, is_core, needs_clarify FROM element"
            " WHERE case_id=%s AND is_current=1 ORDER BY is_core DESC, id LIMIT 8", (case_id,))
        c["notes"] = db.execute(
            "SELECT tag, source, content FROM case_note WHERE case_id=%s"
            " ORDER BY id DESC LIMIT 5", (case_id,))
        c["history"] = db.execute(
            "SELECT to_status, note, created_at FROM case_status_history WHERE case_id=%s"
            " ORDER BY id DESC LIMIT 6", (case_id,))
        vrows = db.execute(
            "SELECT level, conclusion, hard_findings, soft_findings FROM verification_report"
            " WHERE case_id=%s ORDER BY id DESC LIMIT 1", (case_id,))
        if vrows:
            v = vrows[0]
            for k in ("hard_findings", "soft_findings"):
                if isinstance(v[k], str):
                    v[k] = json.loads(v[k]) if v[k] else []
                v[k] = v[k] or []
            c["verification"] = v
        else:
            c["verification"] = None
        return c
    finally:
        db.close()


_VER_CN = {"auto_pass": "自动通过", "pending_review": "转人工复核", "reject_suggestion": "建议不予受理"}


def _case_full_block(case: dict) -> str:
    """案件全貌卡片（"这个案子什么情况"的确定性回复，不调 LLM）：
    案情要点 + 要素表（含原文引句）+ 核验结论 + 流转记录 + 备注。"""
    lines = [f"【本案信息】{case['case_id']} ｜ {case['dispute_type']} ｜ {case['applicant_name']}",
             f"当前节点：{case['status_label']}"
             + (f" ｜ 核验分流：{case['triage']}" if case.get("triage") else "")]
    if case.get("narrative"):
        lines.append(f"案情要点：{case['narrative'][:120]}…")
    els = case.get("elements") or []
    if els:
        lines.append("本案要素（★核心，⚠待补）：")
        for e in els:
            q = f"（原文：“{e['quote'][:40]}”）" if e.get("quote") else ""
            mark = "⚠待补 " if e.get("needs_clarify") else ""
            star = "★" if e.get("is_core") else ""
            lines.append(f"- {star}{e['name']}：{e['value'] or '未抽取'}{mark}{q}")
    v = case.get("verification")
    if v:
        # conclusion 已含命中明细（规则名+依据），此处不再重复罗列、不暴露规则编号
        lines.append(f"核验结论：{_VER_CN.get(v['level'], v['level'])}——{v.get('conclusion') or ''}")
    hist = case.get("history") or []
    if hist:
        lines.append("流转记录（最近在前）：")
        for h in hist:
            at = str(h["created_at"])[5:16].replace("T", " ")
            lines.append(f"- {at} → {_STATUS_CN.get(h['to_status'], h['to_status'])}"
                         + (f"（{h['note']}）" if h.get("note") else ""))
    notes = case.get("notes") or []
    if notes:
        lines.append(f"案件备注（{len(notes)} 条）：")
        for n in notes:
            # source 来自引用卡片标题，已含书名号，勿再包裹
            src = f"{n['source']} " if n.get("source") else ""
            lines.append(f"- [{_NOTE_TAG_CN.get(n['tag'], n['tag'])}] {src}{(n['content'] or '')[:60]}")
    lines.append("如需法律依据（如利息主张、诉讼时效）可继续提问，我会检索知识库作答。")
    return "\n".join(lines)


_NOTE_TAG_CN = {"law": "法条", "similar_case": "类案", "reasoning": "释法说理"}


def _case_block(case: dict) -> str:
    """案件信息块：有命中时作上下文注入；无命中时作确定性回复（不调 LLM）。"""
    line1 = f"【本案信息】{case['case_id']} ｜ {case['dispute_type']} ｜ {case['applicant_name']}"
    line2 = f"当前节点：{case['status_label']}"
    if case.get("triage"):
        line2 += f" ｜ 核验分流：{case['triage']}"
    lines = [line1, line2]
    notes = case.get("notes") or []
    if notes:
        lines.append(f"案件备注（{len(notes)} 条，最新在前）：")
        for n in notes:
            src = f"{n['source']} " if n.get("source") else ""
            lines.append(f"- [{_NOTE_TAG_CN.get(n['tag'], n['tag'])}] {src}{(n['content'] or '')[:80]}")
    return "\n".join(lines)

# 检索无命中时的固定回复：不调 LLM（杜绝编造与自由发挥），一句话给出可行动指引
NO_HIT_REPLY = ("知识库暂无相关依据。如需我基于法条或类案回答，"
                "请在「知识库」页导入对应法律文件并完成灌库后重新提问。")

# 问"现在几点/今天几号"类短问：后端直接答（LLM 不知道真实时间，这类问题也不该花 token），
# 模式收紧防误伤法律问题（如"上诉时间""诉讼时效时间"不匹配）
_TIME_QUERY = re.compile(r"几点了?|几号了?|几月几号|星期几|周几|是什么时间|什么日期|现在时间|当前时间")


def _fallback_reply(message: str) -> str:
    """无命中兜底：时间类问题直接答，其余固定文案。"""
    if len(message.strip()) <= 25 and _TIME_QUERY.search(message):
        now = datetime.now()
        weekday = "一二三四五六日"[now.weekday()]
        return f"现在是 {now.strftime('%Y年%m月%d日 %H:%M')}（星期{weekday}）。"
    return NO_HIT_REPLY


class ChatRequest(BaseModel):
    session_id: Optional[str] = None   # 可空：新会话；携带则续上下文
    case_id: Optional[str] = None      # 可空：携带则注入本案要素上下文
    message: str


class AdoptRequest(BaseModel):
    case_id: str
    session_id: str                    # 来源会话（采纳记录落库用）
    from_reply_id: str
    citation_type: str                 # law 法条 / similar_case 类案 / reasoning 释法说理话术
    ref_id: Optional[str] = None       # citation_type=reasoning 时为空
    title: Optional[str] = None        # 引用标题（法条名/案例名），存备注来源
    content: str
    target: str                        # similar_case_doc 类案参考 / case_note 案件备注


def _sse_stream(session_id: str, body: ChatRequest):
    """SSE 流生成器（同步）。

    用同步生成器 + StreamingResponse，FastAPI/uvicorn 会自动把它放进线程池迭代，
    不阻塞事件循环。每个 LLM token 到达就立刻 yield 一个 delta 事件，前端实时渲染。
    """
    # 从 Redis 取近 10 轮消息（旧→新顺序），拼进 prompt
    history = session_service.get_messages(session_id)
    # 案件感知：携带 case_id 时把案件信息（含备注）注入上下文，AI 才能"看到"本案
    case = _load_case(body.case_id)
    # 案件事实类短问（"这个案子什么情况"）：不检索、不调 LLM，直接回答案件全貌
    case_query = bool(case and _CASE_QUERY.search(body.message))
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if case:
        messages.append({"role": "system", "content": _case_block(case)})
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})

    # RAG：检索知识库（法条+类案），命中则把参考材料绑定在本次提问前
    if case_query:
        context, citations = "", []
    else:
        context, citations = retrieval_service.build_context(retrieval_service.retrieve(body.message))
        if context:
            messages.append({"role": "user", "content": (
                f"{context}\n\n【用户问题】{body.message}\n\n请基于上述参考材料回答，末尾用 [编号] 标注引用。")})
        else:
            messages.append({"role": "user", "content": body.message})

    # 用户消息写入 Redis（追加到会话）
    session_service.append_message(session_id, "user", body.message)

    yield f"event:start\ndata: {json.dumps({'session_id': session_id}, ensure_ascii=False)}\n\n"

    reply_id = "rep_" + uuid.uuid4().hex[:4]
    if case_query:
        # 案件事实类问题：确定性回答案件全貌（含流转记录/核验结论/备注），不调 LLM
        reply = _case_full_block(case)
        session_service.append_message(
            session_id, "assistant", reply, reply_id=reply_id, citations=[],
            context={"no_evidence": 0})
        yield f"event:delta\ndata: {json.dumps({'delta': reply}, ensure_ascii=False)}\n\n"
        yield "event:citations\ndata: " + json.dumps({"citations": []}, ensure_ascii=False) + "\n\n"
        yield f"event:done\ndata: {json.dumps({'reply_id': reply_id}, ensure_ascii=False)}\n\n"
        return
    if not context:
        # 无命中：不调 LLM，确定性兜底（时间类直答；其余固定文案，杜绝编造与说教式发挥）
        reply = _fallback_reply(body.message)
        # 时间兜底算"有回答"，只有"暂无依据"文案计入库缺口指标（先判定再叠加案件卡片）
        is_no_evidence = 1 if reply == NO_HIT_REPLY else 0
        if is_no_evidence and case:
            # 有案件上下文：先给本案卡片（问"这个案子"能答事实），再声明法律依据缺失
            reply = _case_block(case) + "\n\n" + reply
        session_service.append_message(
            session_id, "assistant", reply, reply_id=reply_id, citations=[],
            context={"no_evidence": is_no_evidence})
        yield f"event:delta\ndata: {json.dumps({'delta': reply}, ensure_ascii=False)}\n\n"
        yield "event:citations\ndata: " + json.dumps({"citations": []}, ensure_ascii=False) + "\n\n"
        yield f"event:done\ndata: {json.dumps({'reply_id': reply_id}, ensure_ascii=False)}\n\n"
        return

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

    # 检索命中时推送 citations 事件（法条/类案引用卡片，供采纳回流）
    yield "event:citations\ndata: " + json.dumps({"citations": citations}, ensure_ascii=False) + "\n\n"

    # assistant 消息写入 Redis + MySQL（带 reply_id/citations；context 供统计）
    session_service.append_message(
        session_id, "assistant", text,
        reply_id=reply_id, citations=citations,
        context={"model": provider_model(),
                 "provider": "cloud" if provider._cloud_available() else "local",
                 "latency_ms": latency_ms, "no_evidence": 0},
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
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用代理服务器缓冲（Vite proxy / nginx）
        },
    )


@router.post("/adopt")
async def adopt(body: AdoptRequest, user: dict = Depends(get_current_user)):
    """H2 采纳回流：引用卡片一键落库并写入案件备注。

    闭环：AI 回答 → 采纳 → assist_adoption 记录（统计源） + case_note 备注
    （案件详情可见）。类案参考的文书形态（target=similar_case_doc）待文书模块开工，
    当前两个 target 统一落备注容器，tag 区分来源类型。
    """
    from app.core.db import MySQLClient
    db = MySQLClient()
    try:
        rows = db.execute("SELECT case_id FROM case_info WHERE case_id=%s", (body.case_id,))
        if not rows:
            raise HTTPException(404, "案件不存在")
        cur = db.cursor
        # 1) 案件备注（落点容器；content 存全文）
        cur.execute(
            "INSERT INTO case_note (case_id, content, tag, source, operator_id)"
            " VALUES (%s,%s,%s,%s,%s)",
            (body.case_id, body.content, body.citation_type, body.title, user["user_id"]))
        note_id = cur.lastrowid
        # 2) 采纳记录（统计源；content 快照截断 1000）
        cur.execute(
            "INSERT INTO assist_adoption (case_id, session_id, from_reply_id, citation_type,"
            " ref_id, content, target, target_doc_id, operator_id)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (body.case_id, body.session_id, body.from_reply_id, body.citation_type,
             body.ref_id, body.content[:1000], body.target, str(note_id), user["user_id"]))
        db.commit()
        return {"target": body.target, "doc_id": f"note_{note_id}", "note_id": note_id,
                "appended": True, "by": user["user_id"]}
    finally:
        db.close()


@router.get("/citation")
async def get_citation(ref_id: str, user: dict = Depends(get_current_user)):
    """引用卡片「查看原文」：ref_id=law_{id} / case_{id}，返回完整条文或案例四段。"""
    kind, _, sid = ref_id.partition("_")
    if kind not in ("law", "case") or not sid.isdigit():
        raise HTTPException(400, "无效的引用 ID")
    from app.core.db import MySQLClient
    db = MySQLClient()
    try:
        if kind == "law":
            rows = db.execute("SELECT source, chapter, article, text FROM law WHERE id=%s", (sid,))
            if not rows:
                raise HTTPException(404, "该条文不存在（可能已被删除）")
            r = rows[0]
            return {"type": "law", "title": f"《{r['source']}》 {r['article'] or ''}".strip(),
                    "meta": r["chapter"] or "", "content": r["text"]}
        rows = db.execute(
            "SELECT title, source, fact, process, result, comment FROM case_ref WHERE id=%s", (sid,))
        if not rows:
            raise HTTPException(404, "该案例不存在（可能已被删除）")
        r = rows[0]
        parts = [f"## {name}\n\n{r[key]}" for key, name in
                 (("fact", "基本案情"), ("process", "诉讼请求"), ("result", "裁判结果"), ("comment", "案例分析"))
                 if r[key]]
        return {"type": "case", "title": r["title"], "meta": r["source"] or "",
                "content": "\n\n".join(parts)}
    finally:
        db.close()


@router.get("/sessions")
async def list_sessions(case_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    """H3 会话列表（恢复抽屉用）。只返回当前用户的会话。"""
    sessions = session_service.list_user_sessions(user["user_id"])
    if case_id:
        sessions = [s for s in sessions if s.get("case_id") == case_id]
    items = []
    for s in sessions:
        # 标题取首条用户消息的首行前 30 字（而非最后一条），一眼认得出是哪次对话；
        # 单会话取标题失败（Redis/MySQL 抖动）不拖垮整个列表
        try:
            msgs = session_service.get_messages(s["session_id"])
            first = msgs[0]["content"].strip().splitlines() if msgs else []
            title = first[0][:30] if first else ""
        except Exception:
            title = ""
        items.append({
            "session_id": s["session_id"],
            "case_id": s.get("case_id"),
            "title": title,
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
