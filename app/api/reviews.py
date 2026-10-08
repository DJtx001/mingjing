"""E组 复核工作台接口（讲义 E 组 · 页面③ · 人工介入点②）。

队列来源：核验分流 pending_review(normal) / reject_suggested(high) 自动入队；
裁决去向：pass→auto_passed（受理员生成文书）/ supplement→awaiting_confirmation（带追问清单）
/ reject→reject_suggested（受理员生成并签发通知书）。权限：复核员 / 管理员。
"""
import json
from typing import Optional

import pymysql
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.cases import _STATUS_LABEL, _TRIAGE
from app.core.config import config
from app.core.deps import get_current_user, require_reviewer
from app.services import audit_service, review_service

router = APIRouter(prefix="/reviews", tags=["E-复核"])


# ---------- 表结构（幂等创建） ----------
DDL = """
CREATE TABLE IF NOT EXISTS review_task (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(24) NOT NULL COMMENT '所属案件 case_info.case_id',
  status ENUM('pending','decided') NOT NULL DEFAULT 'pending' COMMENT '队列状态',
  priority ENUM('high','normal') NOT NULL DEFAULT 'normal' COMMENT '硬规则命中=high（队列默认高亮）',
  level_reason VARCHAR(200) DEFAULT NULL COMMENT '队列卡片摘要（核验结论截断，不暴露规则编号）',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  decided_at DATETIME(3) DEFAULT NULL,
  KEY idx_queue (status, priority, created_at),
  KEY idx_case (case_id, created_at)
) COMMENT='复核队列（pending=待裁决；decided 保留历史，可多次挂起）';

CREATE TABLE IF NOT EXISTS review_decision (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  review_task_id BIGINT UNSIGNED NOT NULL,
  case_id VARCHAR(24) NOT NULL,
  decision ENUM('pass','supplement','reject') NOT NULL,
  reason VARCHAR(1000) NOT NULL COMMENT '★ 必填≥10字（数据飞轮：裁决回流）',
  questions JSON DEFAULT NULL COMMENT 'supplement 时的追问清单（回要素确认页）',
  decided_by VARCHAR(16) NOT NULL,
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_case (case_id, created_at),
  KEY idx_decider (decided_by, created_at)
) COMMENT='复核裁决留档（数据飞轮核心表）';
"""


def init_tables():
    conn = pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            for stmt in DDL.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
    finally:
        conn.close()
    # 存量兜底：已分流但从未入队的案件补入队（幂等：同案有 pending 则只更新摘要）
    conn = pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.case_id, c.status,"
                " (SELECT conclusion FROM verification_report v"
                "  WHERE v.case_id = c.case_id ORDER BY v.id DESC LIMIT 1) AS conclusion"
                " FROM case_info c WHERE c.status IN ('pending_review','reject_suggested')")
            rows = cur.fetchall()
    finally:
        conn.close()
    for r in rows:
        try:
            review_service.enqueue(r["case_id"], r["status"], r["conclusion"])
        except Exception:
            pass   # 兜底失败不阻塞启动（与 init_tables 的全局降级哲学一致）


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


class DecisionReq(BaseModel):
    decision: str                        # pass / supplement / reject
    reason: str                          # 必填 ≥10 字（数据飞轮）
    questions: Optional[list[str]] = None  # decision=supplement 时的追问清单


@router.get("")
def list_reviews(status: str = "pending", page: int = 1, page_size: int = 20,
                 user=Depends(require_reviewer)):
    """E1 复核队列（按优先级 high 在前、等待时间升序）。"""
    d = review_service.queue(status, page, page_size)
    for it in d["items"]:
        it["case_status_label"] = _STATUS_LABEL.get(it["case_status"], it["case_status"])
    return d


@router.get("/count")
def review_count(user=Depends(get_current_user)):
    """待裁决任务数（任意登录用户可见——侧边栏徽章用，无敏感信息）。

    注意：必须定义在 /{case_id} 之前，否则会被路径参数捕获。
    """
    return {"pending": review_service.pending_count()}


@router.get("/{case_id}")
def review_detail(case_id: str, user=Depends(require_reviewer)):
    """E2 复核详情：底情 + 核验结论 + 类案参考（辅助裁决）+ 历史裁决。"""
    try:
        d = review_service.detail(case_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    d["case"]["status_label"] = _STATUS_LABEL.get(d["case"]["status"], d["case"]["status"])
    d["case"]["triage"] = _TRIAGE.get(d["case"]["status"])
    return d


@router.post("/{case_id}/decision")
def decide(case_id: str, body: DecisionReq, request: Request,
           user=Depends(require_reviewer)):
    """E3 裁决（人工介入②）：理由必填≥10字；不在待复核状态 → 409 REV_001。"""
    try:
        result = review_service.decide(case_id, body.decision, body.reason,
                                       body.questions, user["user_id"])
    except PermissionError as e:
        raise HTTPException(409, {"code": "REV_001", "message": str(e)})
    except ValueError as e:
        raise HTTPException(422, {"code": "REV_002", "message": str(e)})
    audit_service.record(user, "review_decision", target=case_id,
                         detail={"decision": body.decision, "new_status": result["new_status"],
                                 "questions": body.questions or []},
                         ip=_ip(request))
    return result
