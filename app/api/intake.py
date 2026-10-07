"""C/D 组 受理流程接口：要素表（页面②）+ 核验报告。

流程：GET elements（读，含原文对齐）→ PUT elements（人工确认①，自动触发核验）
→ GET verification（核验报告）。抽取在 POST /cases 建案时自动执行。
"""
import json

import pymysql
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.config import config
from app.core.deps import get_current_user
from app.services import intake_service

router = APIRouter(tags=["C/D-受理流程"])

# ---------- 表结构（幂等创建 + 老库升级） ----------
DDL = """
CREATE TABLE IF NOT EXISTS element (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  element_id VARCHAR(20) NOT NULL COMMENT '要素ID，如 el_9f3a01',
  case_id VARCHAR(24) NOT NULL,
  name VARCHAR(64) NOT NULL COMMENT '要素名（来自 Schema）',
  value VARCHAR(500) DEFAULT NULL COMMENT '抽取值',
  confidence DECIMAL(4,3) DEFAULT 0 COMMENT '置信度 0~1',
  confidence_level ENUM('high','medium','low') DEFAULT 'low',
  quote VARCHAR(500) DEFAULT NULL COMMENT '★ 原文出处引句（三层溯源·层①）',
  start_offset INT DEFAULT NULL COMMENT '引句在陈述中的起始位置',
  end_offset INT DEFAULT NULL,
  is_core TINYINT(1) DEFAULT 0 COMMENT '是否核心要素（缺失将不自动通过）',
  confirmed TINYINT(1) DEFAULT 0 COMMENT '人工是否已确认',
  needs_clarify TINYINT(1) DEFAULT 0 COMMENT '标记待补',
  is_current TINYINT(1) DEFAULT 1 COMMENT '重抽取时旧记录置0保留（审计）',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_element (element_id),
  KEY idx_case_current (case_id, is_current)
) COMMENT='案件要素表';

CREATE TABLE IF NOT EXISTS element_confirm_log (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(24) NOT NULL,
  element_id VARCHAR(20) NOT NULL,
  action ENUM('confirm','modify','mark_missing') NOT NULL,
  old_value VARCHAR(500) DEFAULT NULL,
  new_value VARCHAR(500) DEFAULT NULL,
  reason VARCHAR(500) DEFAULT NULL COMMENT '修正理由（回流数据）',
  operator_id VARCHAR(16) NOT NULL,
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_case (case_id, created_at),
  KEY idx_element (element_id)
) COMMENT='要素确认/修正流水（数据飞轮回流）';

CREATE TABLE IF NOT EXISTS verification_report (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(24) NOT NULL,
  level ENUM('auto_pass','pending_review','reject_suggestion') NOT NULL,
  conclusion TEXT,
  hard_findings JSON COMMENT '硬规则命中（block）',
  soft_findings JSON COMMENT '需复核项（warn + 核心要素缺失）',
  model VARCHAR(32), provider VARCHAR(16),
  verified_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_case_latest (case_id, verified_at)
) COMMENT='核验报告（每次运行留档，最新为准）';

CREATE TABLE IF NOT EXISTS case_status_history (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(24) NOT NULL,
  from_status VARCHAR(24) DEFAULT NULL COMMENT 'NULL=建案',
  to_status VARCHAR(24) NOT NULL,
  by_user_id VARCHAR(16) DEFAULT NULL COMMENT 'NULL=系统',
  note VARCHAR(255) DEFAULT NULL,
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_case (case_id, created_at)
) COMMENT='状态流转时间线（append-only）';
"""


def init_tables():
    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor() as cur:
            for stmt in DDL.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def _conn():
    return pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)


# ---------- 请求模型 ----------
class ElementAction(BaseModel):
    element_id: str
    action: str                        # confirm / modify / mark_missing
    value: Optional[str] = None        # action=modify 时的新值
    reason: Optional[str] = None       # action=modify 必填（回流数据）


class ElementsConfirm(BaseModel):
    elements: list[ElementAction]


# ---------- C1 读取要素表（含原文对齐） ----------
@router.get("/cases/{case_id}/elements")
def get_elements(case_id: str, user=Depends(get_current_user)):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT dispute_type, narrative FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            if not case:
                raise HTTPException(404, "案件不存在")
            cur.execute(
                "SELECT element_id, name, value, confidence, confidence_level, quote,"
                " start_offset, end_offset, is_core, confirmed, needs_clarify"
                " FROM element WHERE case_id=%s AND is_current=1 ORDER BY id", (case_id,))
            elements = cur.fetchall()
        _, schema_ver = intake_service.load_schema(case["dispute_type"])
        return {"dispute_type": case["dispute_type"], "schema_version": schema_ver,
                "narrative": case["narrative"] or "", "elements": elements}
    finally:
        conn.close()


# ---------- C2 确认/修正（人工介入① → 自动触发核验） ----------
@router.put("/cases/{case_id}/elements")
def confirm_elements(case_id: str, body: ElementsConfirm, user=Depends(get_current_user)):
    conn = _conn()
    try:
        stats = {"confirmed_count": 0, "modified_count": 0, "missing_count": 0}
        with conn.cursor() as cur:
            for act in body.elements:
                cur.execute("SELECT * FROM element WHERE element_id=%s AND case_id=%s", (act.element_id, case_id))
                el = cur.fetchone()
                if not el:
                    raise HTTPException(404, f"要素不存在：{act.element_id}")
                old_value = el["value"]
                if act.action == "confirm":
                    cur.execute("UPDATE element SET confirmed=1 WHERE element_id=%s", (act.element_id,))
                    stats["confirmed_count"] += 1
                elif act.action == "modify":
                    if not act.reason or len(act.reason.strip()) < 4:
                        raise HTTPException(400, "修正要素必须填写理由（≥4字）")
                    cur.execute("UPDATE element SET value=%s, confirmed=1, needs_clarify=0 WHERE element_id=%s",
                                (act.value, act.element_id))
                    stats["modified_count"] += 1
                elif act.action == "mark_missing":
                    cur.execute("UPDATE element SET needs_clarify=1 WHERE element_id=%s", (act.element_id,))
                    stats["missing_count"] += 1
                else:
                    raise HTTPException(400, f"未知操作：{act.action}")
                cur.execute(
                    "INSERT INTO element_confirm_log (case_id, element_id, action, old_value, new_value,"
                    " reason, operator_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (case_id, act.element_id, act.action, old_value, act.value,
                     act.reason, user["user_id"]))
        conn.commit()
    finally:
        conn.close()

    # 确认完成 → 自动核验（设计：interrupt① resume 后进入 verify 节点）
    result = intake_service.run_verification(case_id, by_user_id=user["user_id"])
    return {**stats, "verification": result}


# ---------- 单要素补充询问话术（页面②按钮，LLM 生成给受理员） ----------
@router.post("/cases/{case_id}/elements/{element_id}/clarify")
def clarify(case_id: str, element_id: str, user=Depends(get_current_user)):
    try:
        return intake_service.clarify_question(case_id, element_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------- D1 核验报告（最新一份） ----------
@router.get("/cases/{case_id}/verification")
def get_verification(case_id: str, user=Depends(get_current_user)):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT level, conclusion, hard_findings, soft_findings, model, provider, verified_at"
                " FROM verification_report WHERE case_id=%s ORDER BY id DESC LIMIT 1", (case_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(404, "该案件尚未核验")
        for k in ("hard_findings", "soft_findings"):
            if isinstance(row[k], str):
                row[k] = json.loads(row[k]) if row[k] else []
            row[k] = row[k] or []
        return row
    finally:
        conn.close()
