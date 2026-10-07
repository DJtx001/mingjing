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
from app.services import audit_service, reindex_service

router = APIRouter(prefix="/admin", tags=["J-知识库"])


def _ip(request: Request) -> str:
    """取请求来源 IP，用于审计日志。"""
    return request.client.host if request.client else ""


def _conn():
    """每次请求新建连接，用完即关，避免长连接被 MySQL wait_timeout 掐断"""
    import pymysql
    return pymysql.connect(**config.MYSQL)


# ---------- 表结构（幂等创建：规则/Schema/提示词配置表 + 知识库结构化表） ----------
# 法条/案例解析后的结构化数据存 MySQL（真相源，Chroma 可由此重建）；原始文件存 OSS
DDL = """
CREATE TABLE IF NOT EXISTS kb_rule (
  rule_id VARCHAR(16) PRIMARY KEY,
  name VARCHAR(64) NOT NULL,
  description TEXT,
  rule_type ENUM('keyword','regex') NOT NULL DEFAULT 'keyword' COMMENT '规则实现类型（element_logic 待二期）',
  `condition` JSON DEFAULT NULL COMMENT '匹配条件，如 {"keywords":["赌博","报案"]}',
  severity ENUM('block','warn') NOT NULL DEFAULT 'warn' COMMENT 'block→不予受理建议 / warn→人工复核',
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

CREATE TABLE IF NOT EXISTS law (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  source VARCHAR(128) NOT NULL COMMENT '法名，取 md 一级标题，如 中华人民共和国民法典',
  chapter VARCHAR(255) DEFAULT NULL COMMENT '编/章路径，如 合同编·第十二章 借款合同',
  article VARCHAR(64) DEFAULT NULL COMMENT '条号，如 第四百六十三条（条号精确匹配键；无条号文本为 NULL）',
  text MEDIUMTEXT NOT NULL COMMENT '条文全文（部分"修改N件司法解释的决定"整文件超 64KB，故用 MEDIUMTEXT）',
  category VARCHAR(64) DEFAULT NULL COMMENT '法律部门，取上传相对路径首段，如 行政法规',
  effective_date DATE DEFAULT NULL COMMENT '施行日期，取文件头时间行',
  vector_synced TINYINT(1) DEFAULT 0 COMMENT '0=待灌向量库（reindex 扫描条件）',
  file_key VARCHAR(255) DEFAULT NULL COMMENT 'OSS 原文 key，回溯用',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_source_article (source, article),
  KEY idx_category (category),
  KEY idx_synced (vector_synced)
) COMMENT='法条库（子块=单条条文，编/章信息随行携带）';

CREATE TABLE IF NOT EXISTS case_ref (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(255) NOT NULL COMMENT '案例标题，取 md 一级标题',
  source VARCHAR(64) DEFAULT NULL COMMENT '分类，取上传相对路径首段，如 劳动人事',
  fact TEXT COMMENT '基本案情',
  process TEXT COMMENT '诉讼请求/处理过程',
  result TEXT COMMENT '裁判/调解结果',
  comment TEXT COMMENT '案例分析',
  vector_synced TINYINT(1) DEFAULT 0 COMMENT '0=待灌向量库（reindex 扫描条件）',
  file_key VARCHAR(255) DEFAULT NULL COMMENT 'OSS 原文 key，回溯用',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_title (title),
  KEY idx_synced (vector_synced)
) COMMENT='类案库（父块=摘要，子块=四段各一块）';
"""


def init_tables():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            for stmt in DDL.strip().split(";"):
                if stmt.strip():
                    cur.execute(stmt)
            # 升级老库：kb_rule 补规则引擎新列（新库由 CREATE 带全）
            for col, ddl in (
                ("rule_type", "ADD COLUMN rule_type ENUM('keyword','regex') NOT NULL DEFAULT 'keyword'"),
                ("condition", "ADD COLUMN `condition` JSON DEFAULT NULL COMMENT '匹配条件'"),
                ("severity", "ADD COLUMN severity ENUM('block','warn') NOT NULL DEFAULT 'warn'"),
            ):
                cur.execute("SHOW COLUMNS FROM kb_rule LIKE %s", (col,))
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE kb_rule {ddl}")
            # 为存量 R1~R7 回填匹配条件（只填从未配置过的，用户改过的保留）
            cur.executemany(
                "UPDATE kb_rule SET `condition`=%s, severity=%s, rule_type=%s"
                " WHERE rule_id=%s AND `condition` IS NULL",
                [(json.dumps(cond, ensure_ascii=False), sev, rtype, rid)
                 for rid, _name, _desc, rtype, cond, sev in DEFAULT_RULES])
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


# ---------- 规则（含规则引擎的匹配条件：rule_type / condition / severity） ----------
# severity: block→核验建议不予受理；warn→转人工复核
DEFAULT_RULES = [
    ("R1", "涉嫌刑事犯罪", "案件涉嫌刑事犯罪的，不予受理，告知向公安机关报案",
     "keyword", {"keywords": ["刑事", "犯罪", "报案", "诈骗", "赌博", "故意伤害", "非法拘禁", "盗窃"]}, "block"),
    ("R2", "虚假调解嫌疑", "双方无实质争议、疑似借调解确权逃债的，不予受理",
     "keyword", {"keywords": ["没有争议", "无争议", "虚假", "串通", "逃债", "规避", "转移财产"]}, "block"),
    ("R3", "管辖不符", "不属于本调解组织管辖范围的，不予受理并指引正确渠道",
     "keyword", {"keywords": ["不属于本辖区", "外地", "其他省市", "已在仲裁委"]}, "block"),
    ("R4", "已判决或已受理", "同一纠纷已由法院判决或其他机构受理的，不再受理",
     "keyword", {"keywords": ["已判决", "已经判决", "判决书", "法院判", "已起诉", "已经起诉",
                              "已向法院", "已受理", "仲裁裁决"]}, "block"),
    ("R5", "分歧过大无调解基础", "双方分歧过大、无调解意愿的，终止调解",
     "keyword", {"keywords": ["不同意调解", "拒绝调解", "分歧过大", "无法沟通", "谈不拢"]}, "warn"),
    ("R6", "当事人身份无法核实", "当事人身份或代理权限无法核实的，中止受理",
     "keyword", {"keywords": ["身份不明", "无法核实", "没有身份证", "冒用", "冒名"]}, "warn"),
    ("R7", "超过时效且对方抗辩", "超过诉讼时效且对方明确提出抗辩的，不予受理",
     "keyword", {"keywords": ["超过诉讼时效", "诉讼时效已过", "时效抗辩", "超过时效"]}, "block"),
]


@router.get("/rules")
def list_rules(user=Depends(get_current_user)):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT rule_id, name, description, rule_type, `condition`, severity, enabled"
                        " FROM kb_rule ORDER BY rule_id")
            rows = cur.fetchall()
            if not rows:
                # 首次访问自动播种 R1~R7（含规则引擎匹配条件）
                for rid, name, desc, rtype, cond, sev in DEFAULT_RULES:
                    cur.execute(
                        "INSERT IGNORE INTO kb_rule (rule_id, name, description, rule_type,"
                        " `condition`, severity) VALUES (%s,%s,%s,%s,%s,%s)",
                        (rid, name, desc, rtype, json.dumps(cond, ensure_ascii=False), sev),
                    )
                conn.commit()
                cur.execute("SELECT rule_id, name, description, rule_type, `condition`, severity, enabled"
                            " FROM kb_rule ORDER BY rule_id")
                rows = cur.fetchall()
        return {"items": [
            {"rule_id": r[0], "name": r[1], "description": r[2],
             "rule_type": r[3],
             "keywords": (json.loads(r[4]).get("keywords", []) if r[4] else []),
             "severity": r[5], "enabled": bool(r[6])}
            for r in rows]}
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
            # 未配置过：返回内置默认作为可编辑模板（抽取引擎同样使用它），保存即生成 v1
            from app.services.intake_service import DEFAULT_SCHEMAS
            return {"dispute_type": dispute_type,
                    "content": DEFAULT_SCHEMAS.get(dispute_type, []), "schema_version": 0}
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


# ---------- OSS 文件管理（法条/案例原始文件上传 + 解析入库） ----------
def _normalize_rel(rel_path: str, category: str) -> str:
    """归一化相对路径：去掉与 category 同名的开头段。

    用户选任意层级文件夹都能正确处理：选 laws/ 得到 "行政法规/x.md"，
    选上级目录可能得到 "laws/行政法规/x.md"，去掉开头重复的 laws 后两者等价。
    """
    parts = rel_path.replace("\\", "/").split("/")
    while len(parts) > 1 and parts[0] == category:
        parts.pop(0)
    return "/".join(p for p in parts if p)


def _meta_category(key: str) -> str | None:
    """从 OSS key 提取分类元数据：laws/行政法规/xxx.md → 行政法规；单文件上传无目录段 → NULL"""
    parts = key.split("/")
    return parts[1] if len(parts) >= 3 else None


def _import_law(text: str, file_key: str) -> int:
    """法条 md 解析入库，返回入库条数。同(source,article)覆盖更新并重置待灌标记。"""
    from app.services.kb_parser import parse_law_md
    r = parse_law_md(text)
    if not r["source"] or not r["items"]:
        return 0
    category = _meta_category(file_key)
    conn = _conn()
    try:
        with conn.cursor() as cur:
            # UNIQUE 不约束 NULL：无条号块按 file_key 先删后插，避免重导翻倍
            cur.execute("DELETE FROM law WHERE file_key=%s AND article IS NULL", (file_key,))
            cur.executemany(
                "INSERT INTO law (source, chapter, article, text, category, effective_date, file_key)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s)"
                " ON DUPLICATE KEY UPDATE text=VALUES(text), chapter=VALUES(chapter),"
                " category=VALUES(category), effective_date=VALUES(effective_date),"
                " file_key=VALUES(file_key), vector_synced=0",
                [(r["source"], it["chapter"], it["article"], it["text"], category,
                  r["effective_date"], file_key) for it in r["items"]],
            )
        conn.commit()
        return len(r["items"])
    finally:
        conn.close()


def _insert_case(r: dict, file_key: str) -> int:
    """解析结果入库（md / pdf 共用）。uk_title 全局唯一，重名覆盖更新。"""
    if not r["title"]:
        return 0
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO case_ref (title, source, fact, process, result, comment, file_key)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s)"
                " ON DUPLICATE KEY UPDATE source=VALUES(source), fact=VALUES(fact),"
                " process=VALUES(process), result=VALUES(result), comment=VALUES(comment),"
                " file_key=VALUES(file_key), vector_synced=0",
                (r["title"], _meta_category(file_key),
                 r["fact"], r["process"], r["result"], r["comment"], file_key),
            )
        conn.commit()
        return 1
    finally:
        conn.close()


def _import_case(text: str, file_key: str) -> int:
    """案例 md 解析入库。"""
    from app.services.kb_parser import parse_case_md
    return _insert_case(parse_case_md(text), file_key)


def _import_case_pdf(data: bytes, file_key: str) -> int:
    """案例 PDF（人民法院案例库格式）解析入库。"""
    from app.services.kb_parser import parse_case_pdf
    r = parse_case_pdf(data)
    if not r["title"]:   # 标题抽取失败时退回文件名（去掉 .pdf）
        r["title"] = file_key.rsplit("/", 1)[-1].removesuffix(".pdf")
    return _insert_case(r, file_key)


@router.post("/kb/upload", status_code=201)
async def upload_kb_file(
    request: Request,
    file: UploadFile = File(...),
    category: str = "laws",   # laws=法条，cases=案例
    rel_path: str = "",       # 批量导入时的相对路径（含文件名），目录段作为分类元数据
    user=Depends(get_current_user),
):
    """上传法条/案例文件：.md 存 OSS 并解析入库；其他格式（如 PDF）暂只存 OSS 不解析。"""
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    key = f"{category}/{_normalize_rel(rel_path, category)}" if rel_path else f"{category}/{file.filename}"
    url = oss_upload(key, data)
    audit_service.record(user, "kb_upload", target=key, ip=_ip(request))

    result = {"key": key, "url": url, "size": len(data), "filename": file.filename, "parsed": 0}
    lower = key.lower()
    try:
        if lower.endswith(".md"):
            text = data.decode("utf-8")
            result["parsed"] = _import_law(text, key) if category == "laws" else _import_case(text, key)
        elif lower.endswith(".pdf") and category == "cases":
            # 案例 PDF（人民法院案例库格式）：解析四段入库
            result["parsed"] = _import_case_pdf(data, key)
        else:
            result["note"] = "该格式暂不入库（仅存 OSS）"
    except Exception as e:   # 解析失败不炸上传：文件已在 OSS，修复后重传即可
        result["note"] = f"解析入库失败：{e}"
    return result


@router.get("/kb/files")
def list_kb_files(category: str = "", user=Depends(get_current_user)):
    """列出 OSS 上的知识库文件。category=laws/cases，不传则列出全部"""
    prefix = f"{category}/" if category else ""
    return {"items": oss_list(prefix)}


def _purge_structured(file_key: str) -> dict:
    """级联清理某文件的派生数据：MySQL 结构化行 + Chroma 向量块。

    不清理会留下"删了文件但还能检索到"的幽灵数据。
    """
    from app.services import vector_service
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM law WHERE file_key=%s", (file_key,))
            law_ids = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT id FROM case_ref WHERE file_key=%s", (file_key,))
            case_ids = [r[0] for r in cur.fetchall()]
            if law_ids:
                cur.execute("DELETE FROM law WHERE file_key=%s", (file_key,))
            if case_ids:
                cur.execute("DELETE FROM case_ref WHERE file_key=%s", (file_key,))
        conn.commit()
    finally:
        conn.close()
    # Chroma 块 ID 由 MySQL 主键推导，与 reindex_service 保持一致
    if law_ids:
        vector_service.get_collection(vector_service.LAWS_COLLECTION).delete(
            ids=[f"law_{i}" for i in law_ids])
    if case_ids:
        ids = []
        for i in case_ids:
            ids += [f"case_{i}_p"] + [f"case_{i}_{s}" for s in ("fact", "process", "result", "comment")]
        vector_service.get_collection(vector_service.CASES_COLLECTION).delete(ids=ids)
    return {"laws": len(law_ids), "cases": len(case_ids)}


@router.delete("/kb/files")
def delete_kb_file(key: str, request: Request, user=Depends(require_admin)):
    """删除 OSS 文件 + 级联清理 MySQL 结构化数据与 Chroma 向量"""
    oss_delete(key)
    purged = _purge_structured(key)
    audit_service.record(user, "kb_delete", target=key, detail=purged, ip=_ip(request))
    return {"deleted": key, "purged": purged}


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


# ---------- 索引重建（后台线程：vector_synced=0 → embedding → Chroma） ----------
@router.post("/kb/reindex", status_code=202)
def reindex(request: Request, user=Depends(require_admin)):
    if reindex_service.state["status"] == "running":
        # 幂等：进行中重复调用返回同一 task_id
        return {"task_id": reindex_service.state["task_id"], "status": "running"}
    task_id = f"reidx_{uuid.uuid4().hex[:8]}"
    audit_service.record(user, "kb_reindex", target=task_id, ip=_ip(request))
    reindex_service.start(task_id)
    return {"task_id": task_id, "status": "accepted"}


@router.get("/kb/reindex/status")
def reindex_status(user=Depends(get_current_user)):
    return reindex_service.state
