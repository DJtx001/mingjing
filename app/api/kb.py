"""J组 知识库与规则管理接口（对齐《受理Agent接口文档》V1.1 J组，页面⑨）"""
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from typing import Any, Optional

from app.core.config import config
from app.core.deps import get_current_user, require_admin
from app.services.oss_service import (
    upload_file as oss_upload,
    list_files as oss_list,
    delete_file as oss_delete,
    download_file as oss_download,
)
from app.services import audit_service

router = APIRouter(prefix="/admin", tags=["J-知识库"])


def _ip(request: Request) -> str:
    """取请求来源 IP，用于审计日志。"""
    return request.client.host if request.client else ""


def _conn():
    """每次请求新建连接，用完即关，避免长连接被 MySQL wait_timeout 掐断"""
    import pymysql
    return pymysql.connect(**config.MYSQL)


# ---------- 表结构（幂等创建，仅保留规则/Schema/提示词配置表） ----------
# 法条/案例原文存 OSS，向量存 Chroma，不再落 MySQL
DDL = """
CREATE TABLE IF NOT EXISTS kb_rule (
  rule_id VARCHAR(16) PRIMARY KEY,
  name VARCHAR(64) NOT NULL,
  description TEXT,
  enabled TINYINT(1) DEFAULT 1,
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) COMMENT='核验规则 R1~R7';

CREATE TABLE IF NOT EXISTS kb_schema (
  dispute_type VARCHAR(32) PRIMARY KEY,
  content JSON NOT NULL COMMENT '要素数组 [{name,core,type,hint}]',
  schema_version INT DEFAULT 1,
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) COMMENT='要素 Schema（每类纠纷一套）';

CREATE TABLE IF NOT EXISTS kb_prompt (
  prompt_key VARCHAR(32) PRIMARY KEY COMMENT 'extract/verify/retrieve/assist',
  content TEXT NOT NULL,
  version INT DEFAULT 1,
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) COMMENT='提示词模板';
"""


def init_tables():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            for stmt in DDL.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
        conn.commit()
    finally:
        conn.close()


# ---------- Pydantic 入参（仅规则/Schema/提示词） ----------
class RuleUpdate(BaseModel):
    rule_id: str
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


class SchemaSave(BaseModel):
    content: list[dict[str, Any]]


class PromptSave(BaseModel):
    prompt_key: str
    content: str


# ---------- 规则 ----------
DEFAULT_RULES = [
    ("R1", "涉嫌刑事犯罪", "案件涉嫌刑事犯罪的，不予受理，告知向公安机关报案"),
    ("R2", "虚假调解嫌疑", "双方无实质争议、疑似借调解确权逃债的，不予受理"),
    ("R3", "管辖不符", "不属于本调解组织管辖范围的，不予受理并指引正确渠道"),
    ("R4", "已判决或已受理", "同一纠纷已由法院判决或其他机构受理的，不再受理"),
    ("R5", "分歧过大无调解基础", "双方分歧过大、无调解意愿的，终止调解"),
    ("R6", "当事人身份无法核实", "当事人身份或代理权限无法核实的，中止受理"),
    ("R7", "超过时效且对方抗辩", "超过诉讼时效且对方明确提出抗辩的，不予受理"),
]


@router.get("/rules")
def list_rules(user=Depends(get_current_user)):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT rule_id, name, description, enabled FROM kb_rule ORDER BY rule_id")
            rows = cur.fetchall()
            if not rows:
                # 首次访问自动播种 R1~R7
                for rid, name, desc in DEFAULT_RULES:
                    cur.execute(
                        "INSERT IGNORE INTO kb_rule (rule_id, name, description) VALUES (%s,%s,%s)",
                        (rid, name, desc),
                    )
                conn.commit()
                cur.execute("SELECT rule_id, name, description, enabled FROM kb_rule ORDER BY rule_id")
                rows = cur.fetchall()
        return {"items": [{"rule_id": r[0], "name": r[1], "description": r[2], "enabled": bool(r[3])} for r in rows]}
    finally:
        conn.close()


@router.put("/rules")
def update_rule(body: RuleUpdate, request: Request, user=Depends(get_current_user)):
    """规则启停/修改：对所有登录用户开放（区别于删除/保存类操作的 require_admin）。

    操作人仍会记入审计日志（audit_log.rule_update）。
    """
    sets, args = [], []
    if body.name is not None:
        sets.append("name=%s"); args.append(body.name)
    if body.description is not None:
        sets.append("description=%s"); args.append(body.description)
    if body.enabled is not None:
        sets.append("enabled=%s"); args.append(int(body.enabled))
    if not sets:
        raise HTTPException(400, "没有需要更新的字段")
    args.append(body.rule_id)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE kb_rule SET {','.join(sets)} WHERE rule_id=%s", args)
            if cur.rowcount == 0:
                raise HTTPException(404, "规则不存在")
        conn.commit()
        audit_service.record(user, "rule_update", target=body.rule_id,
                             detail={"enabled": body.enabled} if body.enabled is not None else None,
                             ip=_ip(request))
        return {"rule_id": body.rule_id, "updated": True}
    finally:
        conn.close()


# ---------- Schema ----------
@router.get("/schemas/{dispute_type}")
def get_schema(dispute_type: str, user=Depends(get_current_user)):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content, schema_version FROM kb_schema WHERE dispute_type=%s", (dispute_type,))
            row = cur.fetchone()
        if not row:
            # 未配置过：返回空数组 v0，由管理员首次保存生成 v1
            return {"dispute_type": dispute_type, "content": [], "schema_version": 0}
        return {"dispute_type": dispute_type, "content": json.loads(row[0]), "schema_version": row[1]}
    finally:
        conn.close()


@router.put("/schemas/{dispute_type}")
def save_schema(dispute_type: str, body: SchemaSave, request: Request, user=Depends(require_admin)):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            # 已存在则版本 +1（快照原则：旧案件不受影响）；不存在则 v1
            cur.execute(
                "INSERT INTO kb_schema (dispute_type, content, schema_version) VALUES (%s,%s,1) "
                "ON DUPLICATE KEY UPDATE content=VALUES(content), schema_version=schema_version+1",
                (dispute_type, json.dumps(body.content, ensure_ascii=False)),
            )
            cur.execute("SELECT schema_version FROM kb_schema WHERE dispute_type=%s", (dispute_type,))
            ver = cur.fetchone()[0]
        conn.commit()
        audit_service.record(user, "schema_save", target=dispute_type,
                             detail={"schema_version": ver}, ip=_ip(request))
        return {"dispute_type": dispute_type, "schema_version": ver}
    finally:
        conn.close()


# ---------- 提示词 ----------
@router.get("/prompts")
def list_prompts(user=Depends(get_current_user)):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT prompt_key, content FROM kb_prompt")
            rows = cur.fetchall()
        return {"items": {r[0]: r[1] for r in rows}}
    finally:
        conn.close()


@router.put("/prompts")
def save_prompt(body: PromptSave, request: Request, user=Depends(require_admin)):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO kb_prompt (prompt_key, content) VALUES (%s,%s) "
                "ON DUPLICATE KEY UPDATE content=VALUES(content), version=version+1",
                (body.prompt_key, body.content),
            )
        conn.commit()
        audit_service.record(user, "prompt_save", target=body.prompt_key, ip=_ip(request))
        return {"prompt_key": body.prompt_key, "saved": True}
    finally:
        conn.close()


# ---------- OSS 文件管理（法条/案例原始文件上传） ----------
@router.post("/kb/upload", status_code=201)
async def upload_kb_file(
    request: Request,
    file: UploadFile = File(...),
    category: str = "laws",   # laws=法条，cases=案例
    user=Depends(get_current_user),
):
    """上传法条/案例 .md 文件到 OSS。后续「入向量库」时从 OSS 读取解析。"""
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    key = f"{category}/{file.filename}"
    url = oss_upload(key, data)
    audit_service.record(user, "kb_upload", target=key, ip=_ip(request))
    return {"key": key, "url": url, "size": len(data), "filename": file.filename}


@router.get("/kb/files")
def list_kb_files(category: str = "", user=Depends(get_current_user)):
    """列出 OSS 上的知识库文件。category=laws/cases，不传则列出全部"""
    prefix = f"{category}/" if category else ""
    return {"items": oss_list(prefix)}


@router.delete("/kb/files")
def delete_kb_file(key: str, request: Request, user=Depends(require_admin)):
    """删除 OSS 上的知识库文件"""
    oss_delete(key)
    audit_service.record(user, "kb_delete", target=key, ip=_ip(request))
    return {"deleted": key}


@router.get("/kb/files/content")
def get_kb_file_content(key: str, user=Depends(get_current_user)):
    """在线查看文本文件内容：从 OSS 下载并按 UTF-8 返回"""
    data = oss_download(key)
    if data[:4] == b'%PDF':
        raise HTTPException(400, "PDF 文件请使用预览模式查看")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "该文件不支持在线预览（二进制文件），请下载后查看")
    return {"key": key, "content": text, "size": len(data)}


# 文件扩展名 → Content-Type（用于浏览器内嵌预览，如 PDF）
_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


@router.get("/kb/files/raw")
def get_kb_file_raw(key: str, user=Depends(get_current_user)):
    """以原始字节流返回文件：PDF 走浏览器内置阅读器，文本可直接显示"""
    from fastapi import Response
    import os
    from urllib.parse import quote
    data = oss_download(key)
    ext = os.path.splitext(key)[1].lower()
    media_type = _CONTENT_TYPES.get(ext, "application/octet-stream")
    # inline：浏览器尝试内嵌展示而非直接下载；中文文件名走 RFC 5987 编码
    filename = quote(os.path.basename(key))
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
    )


# ---------- 索引重建（异步任务，幂等） ----------
_reindex_task: Optional[str] = None


@router.post("/kb/reindex", status_code=202)
def reindex(request: Request, user=Depends(require_admin)):
    global _reindex_task
    if _reindex_task:
        # 幂等：进行中重复调用返回同一 task_id
        return {"task_id": _reindex_task, "status": "running"}
    _reindex_task = f"reidx_{uuid.uuid4().hex[:8]}"
    audit_service.record(user, "kb_reindex", target=_reindex_task, ip=_ip(request))
    # TODO(二期)：真实异步任务 → BGE-M3 全量向量化 → 写入 Chroma
    # MVP 先返回 task_id，前端展示即可
    return {"task_id": _reindex_task, "status": "accepted"}


@router.get("/kb/reindex/status")
def reindex_status(user=Depends(get_current_user)):
    global _reindex_task
    if not _reindex_task:
        return {"status": "idle"}
    return {"task_id": _reindex_task, "status": "running"}
