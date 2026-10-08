"""复核工作台服务（E 组 · 页面③ · 人工介入点②）。

入队：核验分流后由 intake_service.run_verification 调用 enqueue（延迟 import 防循环）；
      pending_review → normal；reject_suggested → high（对齐讲义 priority 设计）。
裁决状态去向：pass → auto_passed（受理员随后生成文书）；supplement → awaiting_confirmation
（追问清单随裁决留档）；reject → reject_suggested（受理员随后生成并签发通知书）。
"""
import json
import logging

import pymysql

from app.core.config import config
from app.services import intake_service, retrieval_service

logger = logging.getLogger(__name__)

_LEVEL_REASON_MAX = 200
_DECISION_STATUS = {"pass": "auto_passed", "supplement": "awaiting_confirmation",
                    "reject": "reject_suggested"}


def _conn():
    return pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)


# ---------- 入队（幂等） ----------

def enqueue(case_id: str, case_status: str, reason: str | None = None) -> None:
    """分流入队：pending_review→normal；reject_suggested→high。

    同案已有 pending 任务 → 更新摘要/优先级（重核验场景）；否则新建。
    """
    priority = "high" if case_status == "reject_suggested" else "normal"
    level_reason = (reason or "").strip()[:_LEVEL_REASON_MAX] or None
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM review_task WHERE case_id=%s AND status='pending'"
                " ORDER BY id DESC LIMIT 1", (case_id,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE review_task SET priority=%s, level_reason=%s WHERE id=%s",
                            (priority, level_reason, row["id"]))
            else:
                cur.execute(
                    "INSERT INTO review_task (case_id, priority, level_reason) VALUES (%s,%s,%s)",
                    (case_id, priority, level_reason))
        conn.commit()
    finally:
        conn.close()


# ---------- 队列与详情 ----------

def pending_count() -> int:
    """待裁决任务数（侧边栏徽章口径：与复核工作台队列条数一致）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM review_task WHERE status='pending'")
            return cur.fetchone()["n"]
    finally:
        conn.close()


def queue(status: str = "pending", page: int = 1, page_size: int = 20) -> dict:
    """复核队列（按优先级 high 在前、等待时间升序）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            where = "WHERE t.status=%s" if status else ""
            args = (status,) if status else ()
            cur.execute(f"SELECT COUNT(*) AS n FROM review_task t {where}", args)
            total = cur.fetchone()["n"]
            cur.execute(
                f"SELECT t.id, t.case_id, t.priority, t.level_reason, t.status,"
                f" t.created_at, t.decided_at, c.dispute_type, c.applicant_name, c.status AS case_status"
                f" FROM review_task t JOIN case_info c ON c.case_id = t.case_id"
                f" {where} ORDER BY (t.priority='high') DESC, t.created_at ASC LIMIT %s OFFSET %s",
                args + (page_size, (page - 1) * page_size))
            rows = cur.fetchall()
    finally:
        conn.close()
    return {
        "items": [{
            "task_id": r["id"], "case_id": r["case_id"], "dispute_type": r["dispute_type"],
            "applicant_name": r["applicant_name"], "level_reason": r["level_reason"],
            "priority": r["priority"], "waiting_since": str(r["created_at"]),
            "case_status": r["case_status"],
        } for r in rows],
        "page": page, "page_size": page_size, "total": total,
    }


def detail(case_id: str) -> dict:
    """复核详情：底情（陈述+要素）+ 核验报告 + 类案参考 top3 + 历史裁决 + 当前待办任务。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id, dispute_type, applicant_name, narrative, status,"
                " assignee_user_id, created_at FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            if not case:
                raise LookupError("案件不存在")
            cur.execute(
                "SELECT element_id, name, value, confidence, confidence_level, is_core,"
                " confirmed, needs_clarify, quote FROM element"
                " WHERE case_id=%s AND is_current=1 ORDER BY id", (case_id,))
            elements = cur.fetchall()
            cur.execute(
                "SELECT level, conclusion, hard_findings, soft_findings, verified_at"
                " FROM verification_report WHERE case_id=%s ORDER BY id DESC LIMIT 1", (case_id,))
            report = cur.fetchone()
            if report:
                for k in ("hard_findings", "soft_findings"):
                    v = report[k]
                    if isinstance(v, str):
                        v = json.loads(v) if v else []
                    report[k] = v or []
            cur.execute(
                "SELECT id, status, priority, level_reason, created_at FROM review_task"
                " WHERE case_id=%s AND status='pending' ORDER BY id DESC LIMIT 1", (case_id,))
            task = cur.fetchone()
            cur.execute(
                "SELECT decision, reason, questions, decided_by, created_at FROM review_decision"
                " WHERE case_id=%s ORDER BY id DESC LIMIT 5", (case_id,))
            decisions = []
            for r in cur.fetchall():
                qs = r["questions"]
                if isinstance(qs, str):
                    qs = json.loads(qs) if qs else []
                decisions.append({"decision": r["decision"], "reason": r["reason"],
                                  "questions": qs or [], "decided_by": r["decided_by"],
                                  "created_at": str(r["created_at"])})
    finally:
        conn.close()

    # 类案参考 top3（检索驱动；异常降级为空——复核对照不因检索故障中断）
    try:
        query = case["dispute_type"] + " " + " ".join(
            f"{e['name']}{e['value']}" for e in elements if (e["value"] or "").strip())
        similar = retrieval_service.retrieve(query, top_laws=0, top_cases=3)["cases"]
    except Exception as e:
        logger.warning("复核详情类案检索失败 case_id=%s: %s", case_id, e)
        similar = []

    case["created_at"] = str(case["created_at"]) if case["created_at"] else ""
    if task:
        task["created_at"] = str(task["created_at"])
    if report:
        report["verified_at"] = str(report["verified_at"]) if report.get("verified_at") else None
    return {"case": case, "elements": elements, "verification": report,
            "similar_cases": similar, "task": task, "previous_decisions": decisions}


# ---------- 裁决 ----------

def decide(case_id: str, decision: str, reason: str, questions: list | None,
           by_user_id: str) -> dict:
    """裁决（resume 人工介入②）：落 review_decision + task 关闭 + 案件状态流转。"""
    if decision not in _DECISION_STATUS:
        raise ValueError(f"未知裁决：{decision}")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ValueError("裁决理由必填（不少于 10 字）")

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM review_task WHERE case_id=%s AND status='pending'"
                " ORDER BY id DESC LIMIT 1", (case_id,))
            task = cur.fetchone()
            if not task:
                raise PermissionError("该案件不在待复核状态")
            cur.execute(
                "INSERT INTO review_decision (review_task_id, case_id, decision, reason,"
                " questions, decided_by) VALUES (%s,%s,%s,%s,%s,%s)",
                (task["id"], case_id, decision, reason,
                 json.dumps(questions or [], ensure_ascii=False) if decision == "supplement" else None,
                 by_user_id))
            cur.execute("UPDATE review_task SET status='decided', decided_at=NOW(3) WHERE id=%s",
                        (task["id"],))
        conn.commit()
    finally:
        conn.close()

    note = {"pass": f"复核通过：{reason[:60]}",
            "supplement": f"复核退回补充：{reason[:60]}",
            "reject": f"复核不予受理：{reason[:60]}"}[decision]
    intake_service.set_status(case_id, _DECISION_STATUS[decision], by_user_id, note)
    return {"case_id": case_id, "decision": decision,
            "new_status": _DECISION_STATUS[decision], "questions": questions or []}
