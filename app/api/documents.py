"""F组 文书接口（F6 四产出物生成 + F7 签发）。对齐《受理Agent接口文档》F 组，页面④。

红线："系统只起草、不拍板"——文书未签发不生效；签发不可逆并全程留审计。
生成/签发的业务规则在 app/services/document_service.py。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.deps import get_current_user
from app.services import audit_service, document_service
from app.services.document_service import DocumentError

router = APIRouter(prefix="/cases", tags=["F-文书"])


# ---------- 表结构（幂等创建） ----------
# document：一案每类一份（uk_case_type），重生成=覆盖 draft、doc_id 保持不变
# document_annotation：溯源锚点（层①要素↔原文 / 法条 / 类案 / 规则依据）
# 刻意不加外键：重生成按 doc_id 先删后插注解，级联外键会误删（与 assist_adoption 同一约定）
DDL = """
CREATE TABLE IF NOT EXISTS document (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  doc_id VARCHAR(20) NOT NULL COMMENT '文书ID，如 doc_9f3a01b2（重生成时保持不变）',
  case_id VARCHAR(24) NOT NULL COMMENT '所属案件 case_info.case_id',
  type ENUM('case_profile','verify_report','intake_form','similar_cases','reject_notice',
            'agreement','termination') NOT NULL
      COMMENT '文书类型（agreement/termination 属调解结果模块，本期只建枚举）',
  title VARCHAR(128) NOT NULL COMMENT '文书标题（列表/导出文件名用）',
  content_md MEDIUMTEXT COMMENT '正文 Markdown（字符偏移 = 注解锚定的基准）',
  status ENUM('draft','issued') NOT NULL DEFAULT 'draft'
      COMMENT 'draft=草案（可重生成覆盖）/ issued=已签发（不可变）',
  issued_by VARCHAR(16) DEFAULT NULL COMMENT '签发人 user_id（人工介入③）',
  issued_at DATETIME(3) DEFAULT NULL,
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_doc (doc_id),
  UNIQUE KEY uk_case_type (case_id, type),
  KEY idx_status (status, updated_at)
) COMMENT='文书（一案每类一份；重生成=覆盖 draft）';

CREATE TABLE IF NOT EXISTS document_annotation (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  doc_id VARCHAR(20) NOT NULL COMMENT '所属文书 document.doc_id',
  annotation_type ENUM('element_source','law','similar_case','rule') NOT NULL
      COMMENT '溯源类型：要素原文/法条/类案/核验规则依据（rule 为本项目扩展值）',
  anchor_start INT NOT NULL COMMENT '锚点在 content_md 中的起始字符偏移（含）',
  anchor_end INT NOT NULL COMMENT '结束偏移（不含）；锚点不跨行，前端据此注入高亮 span',
  ref_type VARCHAR(16) NOT NULL COMMENT '引用对象类型：element/law/case/rule',
  ref_id VARCHAR(24) NOT NULL COMMENT '引用对象ID：el_xxx / law_{id} / case_{id} / R1',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_doc (doc_id, anchor_start)
) COMMENT='文书溯源锚点（点正文→回要素/法条/类案/规则）';
"""


def init_tables():
    import pymysql
    from app.core.config import config
    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor() as cur:
            for stmt in DDL.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _raise(e: DocumentError):
    raise HTTPException(e.http_status, {"code": e.code, "message": e.message})


class GenerateReq(BaseModel):
    types: Optional[list[str]] = None   # 缺省=按案件状态推导（auto_passed/documents_ready→四产出物；reject_suggested→通知书）


@router.get("/{case_id}/documents")
def list_documents(case_id: str, user=Depends(get_current_user)):
    """F1 文书列表（三角色可看）：doc 元信息 + 案件状态 + 是否可生成。"""
    try:
        return document_service.list_documents(case_id)
    except DocumentError as e:
        _raise(e)


@router.get("/{case_id}/documents/{doc_id}")
def get_document(case_id: str, doc_id: str, user=Depends(get_current_user)):
    """F2 文书详情：正文 + 溯源注解（前端据此实现"点引用→侧栏展开原文"）。"""
    try:
        return document_service.get_document(case_id, doc_id)
    except DocumentError as e:
        _raise(e)


@router.post("/{case_id}/documents/generate")
def generate_documents(case_id: str, body: GenerateReq, request: Request,
                       user=Depends(get_current_user)):
    """F6 生成/重生成文书。draft 覆盖、issued 跳过；单类失败不整单失败。"""
    try:
        result = document_service.generate(case_id, body.types, user["user_id"])
    except DocumentError as e:
        _raise(e)
    audit_service.record(
        user, "doc_generate", target=case_id,
        detail={"types": [g["type"] for g in result["generated"]],
                "warnings": result["warnings"], "skipped": result["skipped"]},
        ip=_ip(request))
    return result


@router.post("/{case_id}/documents/{doc_id}/issue")
def issue_document(case_id: str, doc_id: str, request: Request,
                   user=Depends(get_current_user)):
    """F7 签发（人工介入③，不可逆）。登记表单独签发或四类全签 → 案件 issued；
    通知书签发 → rejected 终态。已签发重复调用返回 409 DOC_004。"""
    try:
        result = document_service.issue(case_id, doc_id, user["user_id"])
    except DocumentError as e:
        _raise(e)
    audit_service.record(
        user, "doc_issue", target=doc_id,
        detail={"case_id": case_id, "type": result["type"],
                "case_status": result["case_status"], "also_issued": result["also_issued"]},
        ip=_ip(request))
    return result
