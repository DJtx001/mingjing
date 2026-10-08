"""B组 案件接口（严格对齐《受理Agent接口文档》V1.1 B组）
列表字段：case_id/dispute_type/applicant_name/current_step/status/status_label/assignee
"""
import json
import random

import pymysql
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.config import config
from app.core.deps import get_current_user
from app.services import intake_service

router = APIRouter(prefix="/cases", tags=["B-案件"])

# ---------- 表结构（幂等创建：最小案件域） ----------
# 受理流程（要素/核验/文书）未开工，只建"案件主体 + 案件备注"两张表。
# 设计文档中 case_info 的 narrative/current_step/phone_enc/checkpoint_version/
# schema_version/closed_at 等列，到对应模块开工时再加（避免超前字段）。
DDL = """
CREATE TABLE IF NOT EXISTS case_info (
  case_id VARCHAR(24) PRIMARY KEY COMMENT '案件ID，如 AJ2026-10086',
  dispute_type VARCHAR(16) NOT NULL COMMENT '纠纷类型：民间借贷/物业服务/侵权赔偿…',
  applicant_name VARCHAR(64) NOT NULL COMMENT '当事人展示名，如 王某 vs 张某',
  narrative MEDIUMTEXT COMMENT '当事人原始陈述（要素抽取的原文依据）',
  status VARCHAR(24) NOT NULL DEFAULT 'draft' COMMENT '状态值（沿用设计状态机命名；中文 label 由接口层映射）',
  assignee_user_id VARCHAR(16) DEFAULT NULL COMMENT '承办/受理员 user_id',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY idx_status (status, updated_at),
  KEY idx_assignee (assignee_user_id, status)
) COMMENT='案件主表（最小版：文书模块开工时按设计文档扩展列）';

CREATE TABLE IF NOT EXISTS case_note (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(24) NOT NULL COMMENT '所属案件 case_info.case_id',
  content TEXT NOT NULL COMMENT '备注正文（采纳时为引用内容的快照）',
  tag ENUM('law','similar_case','reasoning') NOT NULL COMMENT '来源类型：法条/类案/释法说理',
  source VARCHAR(128) DEFAULT NULL COMMENT '来源标题（法条名 / 案例名），列表展示用',
  from_adoption_id BIGINT UNSIGNED DEFAULT NULL COMMENT '来自哪条采纳记录（assist_adoption.id）',
  operator_id VARCHAR(16) NOT NULL COMMENT '操作人 user_id',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_case (case_id, created_at),
  KEY idx_adoption (from_adoption_id)
) COMMENT='案件备注（采纳回流的落点；类案参考的文书形态待文书模块开工）';
"""


def init_tables():
    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor() as cur:
            for stmt in DDL.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
            # 升级老库：case_info 补 narrative 列（新库由 CREATE 带全）
            cur.execute("SHOW COLUMNS FROM case_info LIKE 'narrative'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE case_info ADD COLUMN narrative MEDIUMTEXT "
                            "COMMENT '当事人原始陈述（要素抽取的原文依据）' AFTER applicant_name")
        conn.commit()
    finally:
        conn.close()


# ---------- 状态语义（沿用设计文档状态机命名；中文 label 与分流徽章由接口层映射） ----------
_STATUS_LABEL = {
    "draft": "草稿",
    "extracting": "要素抽取中",
    "awaiting_confirmation": "要素确认中",
    "verifying": "核验中",
    "auto_passed": "核验通过 · 待生成文书",
    "pending_review": "人工复核",
    "reject_suggested": "不予受理意见（草案）",
    "rejected": "不予受理（已签发）",
    "documents_ready": "待签发",
    "issued": "已签发",
    "closed": "已结案",
}
# 核验分流徽章由 status 派生（核验模块未开工，不做独立字段）
_TRIAGE = {
    "auto_passed": "pass",
    "pending_review": "review",
    "reject_suggested": "reject",
    "rejected": "reject",
    "documents_ready": "pass",
    "issued": "pass",
    "closed": "pass",
}

# 演示种子案件（首次访问自动播种，对齐设计原型页⑦；受理流程开工后由真实流程产生）
_SEED_CASES = [
    ("AJ2026-10086", "民间借贷", "王某 vs 张某", "documents_ready", "u_002"),
    ("AJ2026-10083", "民间借贷", "李某 vs 周某", "pending_review", "u_002"),
    ("AJ2026-10081", "物业服务", "某小区业主委会", "pending_review", "u_002"),
    ("AJ2026-10078", "民间借贷", "赵某 vs 钱某", "reject_suggested", "u_003"),
    ("AJ2026-10075", "侵权赔偿", "孙某 vs 吴某", "pending_review", "u_003"),
    ("AJ2026-10070", "民间借贷", "郑某 vs 王某", "closed", "u_006"),
    ("AJ2026-10062", "物业服务", "某物业公司 vs 张先生", "draft", "u_003"),
    ("AJ2026-10055", "婚姻家庭", "陈某 vs 刘某", "awaiting_confirmation", "u_002"),
]


def _conn():
    return pymysql.connect(**config.MYSQL)


def _seed_if_empty():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM case_info")
            if cur.fetchone()[0] > 0:
                return
            cur.executemany(
                "INSERT INTO case_info (case_id, dispute_type, applicant_name, status, assignee_user_id)"
                " VALUES (%s,%s,%s,%s,%s)", _SEED_CASES)
        conn.commit()
    finally:
        conn.close()


def _case_item(r: dict) -> dict:
    """行 → 列表项（对齐前端字段：status_label 中文、triage 分流徽章、ISO 时间）。

    review_pending：该案是否有待裁决的复核任务——前端据此区分"去复核/等待确认/生成通知书"。
    """
    return {
        "case_id": r["case_id"],
        "dispute_type": r["dispute_type"],
        "applicant_name": r["applicant_name"],
        "status": r["status"],
        "status_label": _STATUS_LABEL.get(r["status"], r["status"]),
        "triage": _TRIAGE.get(r["status"]),
        "assignee_user_id": r["assignee_user_id"],
        "review_pending": bool(r.get("review_pending")),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


# ---------- 接口 ----------
class NewCase(BaseModel):
    narrative: str                     # 当事人陈述（必填）
    dispute_type: str = "民间借贷"     # 可空：设计支持类型识别；演示给默认值
    applicant: Optional[dict] = None   # {name, phone?, role_in_dispute?}


@router.post("", status_code=201)
def create_case(body: NewCase, user=Depends(get_current_user)):
    """B1 新建受理（页面①提交）：建案 → 同步 LLM 抽取要素 → 待确认。

    设计为异步（SSE 推进度）；本实现同步完成（几秒，前端 loading 即可），
    语义一致：返回时案件已进入 awaiting_confirmation 且要素已入库。
    """
    narrative = (body.narrative or "").strip()
    if len(narrative) < 20:
        raise HTTPException(422, "陈述过短：请录入不少于 20 字的当事人陈述")

    applicant = body.applicant or {}
    applicant_name = applicant.get("name") or "待补充"

    conn = _conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 生成不冲突的案件编号：AJ{年份}-{5位随机}
            for _ in range(20):
                case_id = f"AJ2026-{random.randint(10000, 99999)}"
                cur.execute("SELECT 1 FROM case_info WHERE case_id=%s", (case_id,))
                if not cur.fetchone():
                    break
            else:
                raise HTTPException(500, "案件编号生成失败，请重试")
            cur.execute(
                "INSERT INTO case_info (case_id, dispute_type, applicant_name, narrative, status,"
                " assignee_user_id) VALUES (%s,%s,%s,%s,'draft',%s)",
                (case_id, body.dispute_type, applicant_name, narrative, user["user_id"]))
        conn.commit()
    finally:
        conn.close()

    # 状态流转：draft → extracting →（抽取完成）awaiting_confirmation（历史时间线真实可溯）
    intake_service.set_status(case_id, "extracting", user["user_id"], "建案，进入要素抽取")
    try:
        elements = intake_service.extract_elements(case_id, by_user_id=user["user_id"])
    except Exception as e:
        # 抽取失败：案件已建（可稍后重试），把错误信息带回前端
        intake_service.set_status(case_id, "draft", user["user_id"], f"抽取失败：{str(e)[:80]}")
        raise HTTPException(502, f"要素抽取失败（案件已创建，可稍后重试）：{e}")

    return {"case_id": case_id, "status": "awaiting_confirmation",
            "dispute_type": body.dispute_type, "elements_count": len(elements)}


@router.get("")
async def list_cases(status: str = "", dispute_type: str = "", keyword: str = "",
                     assignee_user_id: str = "", page: int = 1, page_size: int = 20,
                     user=Depends(get_current_user)):
    """B2 案件列表（页⑦）。status 支持逗号分隔多值"""
    _seed_if_empty()
    where, args = [], []
    if status:
        vals = [s.strip() for s in status.split(",") if s.strip()]
        if vals:
            where.append(f"status IN ({','.join(['%s'] * len(vals))})")
            args += vals
    if dispute_type:
        where.append("dispute_type=%s")
        args.append(dispute_type)
    if keyword:
        where.append("(applicant_name LIKE %s OR case_id LIKE %s)")
        args += [f"%{keyword}%"] * 2
    if assignee_user_id:
        where.append("assignee_user_id=%s")
        args.append(assignee_user_id)
    cond = ("WHERE " + " AND ".join(where)) if where else ""

    conn = _conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM case_info {cond}", args)
            total = cur.fetchone()["n"]
            cur.execute(
                f"SELECT *, EXISTS(SELECT 1 FROM review_task rt WHERE rt.case_id = case_info.case_id"
                f" AND rt.status = 'pending') AS review_pending"
                f" FROM case_info {cond} ORDER BY updated_at DESC, case_id DESC LIMIT %s OFFSET %s",
                args + [page_size, (page - 1) * page_size])
            rows = cur.fetchall()
        return {"items": [_case_item(r) for r in rows],
                "page": page, "page_size": page_size, "total": total}
    finally:
        conn.close()


@router.get("/{case_id}")
async def get_case(case_id: str, user=Depends(get_current_user)):
    """B3 案件详情：案件信息 + 陈述原文 + 流转时间线 + 要素/核验摘要 + 备注"""
    _seed_if_empty()
    conn = _conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT *, EXISTS(SELECT 1 FROM review_task rt WHERE rt.case_id = case_info.case_id"
                " AND rt.status = 'pending') AS review_pending"
                " FROM case_info WHERE case_id=%s", (case_id,))
            row = cur.fetchone()
            if not row:
                return {"error": {"code": "CASE_004", "message": "案件不存在"}}
            cur.execute(
                "SELECT id, content, tag, source, operator_id, created_at"
                " FROM case_note WHERE case_id=%s ORDER BY id DESC", (case_id,))
            notes = cur.fetchall()
            # 流转时间线（步骤条 tooltip / 过程回溯）
            cur.execute(
                "SELECT from_status, to_status, by_user_id, note, created_at"
                " FROM case_status_history WHERE case_id=%s ORDER BY id", (case_id,))
            history = cur.fetchall()
            cur.execute("SELECT COUNT(*) AS n FROM element WHERE case_id=%s AND is_current=1", (case_id,))
            elements_count = cur.fetchone()["n"]
            cur.execute("SELECT level FROM verification_report WHERE case_id=%s ORDER BY id DESC LIMIT 1",
                        (case_id,))
            vrow = cur.fetchone()
            # 复核退回补充（最近一条 supplement 裁决）：受理员在要素确认页据此补询
            cur.execute("SELECT reason, questions, created_at FROM review_decision"
                        " WHERE case_id=%s AND decision='supplement' ORDER BY id DESC LIMIT 1",
                        (case_id,))
            rq = cur.fetchone()
            if rq:
                qs = rq["questions"]
                if isinstance(qs, str):
                    qs = json.loads(qs) if qs else []
                review_followup = {"reason": rq["reason"], "questions": qs or [],
                                   "at": str(rq["created_at"])}
            else:
                review_followup = None
        case_item = _case_item(row)
        case_item["narrative"] = row.get("narrative") or ""
        return {"case": case_item, "notes": notes, "history": history,
                "elements_count": elements_count,
                "verification_level": vrow["level"] if vrow else None,
                "review_followup": review_followup}
    finally:
        conn.close()
