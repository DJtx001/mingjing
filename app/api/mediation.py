"""G组 调解结果与协议书接口（讲义 G 组 · 页面⑤ · F10 结案收尾）。

流程：issued（受理文书已签发）→ PUT 录入结果（即时校验 + 落快照 + 纯模板生成
《调解协议书》/《调解终结书》草案）→ POST agreement/issue 签发结案 → closed。
协议书生成为纯模板渲染（ADR-4），零 LLM；基础要素继承自录入时刻的快照。
"""
import json
from datetime import date, datetime, timedelta
from typing import Any, Optional

import pymysql
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.cases import _STATUS_LABEL
from app.core.config import config
from app.core.deps import get_current_user
from app.services import audit_service, document_service
from app.services.document_service import DocumentError, TYPE_LABEL

router = APIRouter(tags=["G-调解结果"])

DDL = """
CREATE TABLE IF NOT EXISTS mediation_result (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  case_id VARCHAR(24) NOT NULL COMMENT '所属案件',
  reached TINYINT(1) NOT NULL COMMENT '是否达成调解（0 走《调解终结书》模板）',
  settlement JSON DEFAULT NULL COMMENT '达成：principal_agreed/interest_waived/installments[{seq,due_date,amount}]/pay_method；未达成：termination_reason',
  judicial_confirmation TINYINT(1) DEFAULT 0 COMMENT '是否申请司法确认',
  inherited_snapshot JSON DEFAULT NULL COMMENT '★ 录入时刻的继承要素快照（底情变了协议书不变）',
  recorded_by VARCHAR(16) NOT NULL,
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_case (case_id)
) COMMENT='调解结果（一案一条，PUT 覆盖；快照保证协议书稳定）';
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


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _raise(e: DocumentError):
    raise HTTPException(e.http_status, {"code": e.code, "message": e.message})


def _inherited_elements(cur, case_id: str) -> list[dict]:
    """继承要素快照：当前（is_current=1）有值的要素；confirmed 供前端"未确认"警示。"""
    cur.execute(
        "SELECT element_id, name, value, confirmed FROM element"
        " WHERE case_id=%s AND is_current=1 AND value IS NOT NULL AND value<>''"
        " ORDER BY is_core DESC, id", (case_id,))
    return [{"field": r["name"], "from_element": r["element_id"], "value": r["value"],
             "origin": "inherited", "confirmed": bool(r["confirmed"])}
            for r in cur.fetchall()]


def _doc_summary(cur, case_id: str) -> dict | None:
    cur.execute(
        "SELECT doc_id, type, title, status, issued_at FROM document"
        " WHERE case_id=%s AND type IN ('agreement','termination')"
        " ORDER BY id DESC LIMIT 1", (case_id,))
    d = cur.fetchone()
    if not d:
        return None
    return {"doc_id": d["doc_id"], "type": d["type"],
            "type_label": TYPE_LABEL.get(d["type"], d["type"]), "title": d["title"],
            "status": d["status"], "status_label": "已签发" if d["status"] == "issued" else "草案",
            "issued_at": str(d["issued_at"]) if d["issued_at"] else None}


class MediationSave(BaseModel):
    reached: bool
    settlement: dict[str, Any] = {}
    judicial_confirmation: bool = False


def _validate(body: MediationSave) -> list[str]:
    """即时校验（确定性规则，非 LLM）：MED_001 分期合计=本金 / MED_002 期限不早于签署日 / MED_003 金额非负。"""
    errors: list[str] = []
    s = body.settlement or {}

    def _amt(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if body.reached:
        principal = _amt(s.get("principal_agreed"))
        if principal is None or principal <= 0:
            errors.append("MED_003 协议本金必须为大于 0 的数字")
        installments = s.get("installments") or []
        total, today = 0.0, date.today()
        for i, it in enumerate(installments, 1):
            amt = _amt(it.get("amount"))
            if amt is None or amt < 0:
                errors.append(f"MED_003 第 {i} 期金额必须为非负数字")
            else:
                total += amt
            due = str(it.get("due_date") or "").strip()
            if due:
                try:
                    if date.fromisoformat(due) < today:
                        errors.append(f"MED_002 第 {i} 期期限（{due}）早于签署日")
                except ValueError:
                    errors.append(f"MED_002 第 {i} 期期限格式应为 YYYY-MM-DD")
            if not due:
                errors.append(f"MED_002 第 {i} 期缺少履行期限")
        if principal is not None and principal > 0 and installments and abs(total - principal) > 1e-6:
            errors.append(f"MED_001 分期合计（{total:g}）与协议本金（{principal:g}）不一致")
    else:
        if not str(s.get("termination_reason") or "").strip():
            errors.append("未达成调解时必须填写终结原因")
    return errors


@router.get("/cases/{case_id}/mediation-result")
def get_mediation_result(case_id: str, user=Depends(get_current_user)):
    """G1 读取（继承要素 + 已录结果 + 协议书文书摘要）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT case_id, status FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            if not case:
                raise HTTPException(404, "案件不存在")
            inherited = _inherited_elements(cur, case_id)
            cur.execute(
                "SELECT reached, settlement, judicial_confirmation, recorded_by, updated_at"
                " FROM mediation_result WHERE case_id=%s", (case_id,))
            row = cur.fetchone()
            if row:
                if isinstance(row["settlement"], str):
                    row["settlement"] = json.loads(row["settlement"]) if row["settlement"] else {}
                row["reached"] = bool(row["reached"])
                row["judicial_confirmation"] = bool(row["judicial_confirmation"])
                row["updated_at"] = str(row["updated_at"]) if row["updated_at"] else ""
            doc = _doc_summary(cur, case_id)
    finally:
        conn.close()
    return {"case_id": case_id, "case_status": case["status"],
            "case_status_label": _STATUS_LABEL.get(case["status"], case["status"]),
            "inherited": inherited, "result": row, "doc": doc}


@router.put("/cases/{case_id}/mediation-result")
def save_mediation_result(case_id: str, body: MediationSave, request: Request,
                          user=Depends(get_current_user)):
    """G2 录入结果（即时校验 + 落快照 + 生成协议书/终结书草案）。仅「已签发」案件可录。"""
    errors = _validate(body)
    if errors:
        raise HTTPException(422, {"code": "MED_001", "message": "；".join(errors)})

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT case_id, status FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            if not case:
                raise HTTPException(404, "案件不存在")
            if case["status"] != "issued":
                raise HTTPException(409, {"code": "MED_005",
                    "message": f"当前状态（{_STATUS_LABEL.get(case['status'], case['status'])}）不能录入调解结果——"
                               f"须先签发受理文书（已结案案件不可重录）"})
            snapshot = _inherited_elements(cur, case_id)
            cur.execute(
                "INSERT INTO mediation_result (case_id, reached, settlement,"
                " judicial_confirmation, inherited_snapshot, recorded_by)"
                " VALUES (%s,%s,%s,%s,%s,%s)"
                " ON DUPLICATE KEY UPDATE reached=VALUES(reached), settlement=VALUES(settlement),"
                " judicial_confirmation=VALUES(judicial_confirmation),"
                " inherited_snapshot=VALUES(inherited_snapshot), recorded_by=VALUES(recorded_by)",
                (case_id, 1 if body.reached else 0,
                 json.dumps(body.settlement or {}, ensure_ascii=False),
                 1 if body.judicial_confirmation else 0,
                 json.dumps(snapshot, ensure_ascii=False), user["user_id"]))
            # 重录/换类型：清掉旧的结案文书草案（issued 的不可删——但签发即 closed 不会走到这）
            cur.execute("SELECT doc_id FROM document WHERE case_id=%s"
                        " AND type IN ('agreement','termination') AND status='draft'", (case_id,))
            old_ids = [r["doc_id"] for r in cur.fetchall()]
            if old_ids:
                fmt = ",".join(["%s"] * len(old_ids))
                cur.execute(f"DELETE FROM document_annotation WHERE doc_id IN ({fmt})", old_ids)
                cur.execute(f"DELETE FROM document WHERE doc_id IN ({fmt})", old_ids)
        conn.commit()
    finally:
        conn.close()

    # 纯模板生成协议书/终结书草案（零 LLM；单类失败即整体失败——结案文书必须有）
    doc_type = "agreement" if body.reached else "termination"
    try:
        result = document_service.generate(case_id, [doc_type], user["user_id"])
    except DocumentError as e:
        _raise(e)
    if not result["generated"]:
        raise HTTPException(500, {"code": "MED_006",
            "message": "结案文书生成失败：" + ("；".join(result["warnings"]) or "未知原因")})
    doc = result["generated"][0]

    audit_service.record(user, "mediation_record", target=case_id,
                         detail={"reached": body.reached, "doc_type": doc_type,
                                 "doc_id": doc["doc_id"]},
                         ip=_ip(request))
    return {"valid": True,
            "agreement_doc": {"doc_id": doc["doc_id"], "type": doc_type,
                              "title": doc["title"], "status": "draft"}}


@router.post("/cases/{case_id}/agreement/issue")
def issue_agreement(case_id: str, request: Request, user=Depends(get_current_user)):
    """G3 签发结案（不可逆）：协议书/终结书签发 → closed；返回司法确认 30 日期限。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            doc = _doc_summary(cur, case_id)
    finally:
        conn.close()
    if not doc:
        raise HTTPException(409, {"code": "MED_004",
                                  "message": "尚未生成结案文书——请先录入调解结果"})

    try:
        result = document_service.issue(case_id, doc["doc_id"], user["user_id"])
    except DocumentError as e:
        _raise(e)

    deadline = None
    try:
        dt = datetime.fromisoformat(result["issued_at"])
        deadline = (dt + timedelta(days=30)).date().isoformat()
    except (ValueError, TypeError):
        pass
    audit_service.record(user, "doc_issue", target=doc["doc_id"],
                         detail={"case_id": case_id, "type": doc["type"],
                                 "case_status": result["case_status"], "via": "agreement/issue"},
                         ip=_ip(request))
    return {"case_id": case_id, "status": result["case_status"],
            "agreement_doc_id": doc["doc_id"],
            "judicial_confirmation_deadline": deadline}
