"""受理流程服务：要素抽取（LLM）+ 核验分流（规则引擎）+ 状态流转。

流程：narrative →[LLM 抽取]→ element（带原文引句 offset，三层溯源层①）
     →[人工确认/修正]→ run_verification（R1~R7 规则匹配）
     → 三级分流（auto_pass / pending_review / reject_suggestion）→ case_status_history。
抽取提示词与要素 Schema 优先读知识库配置（kb_prompt.extract / kb_schema），未配置用内置默认
（"改配置不发版"设计）。
"""
import json
import re
import uuid

import pymysql

from app.core.config import config
from app.llm.provider import provider

# ---------- 内置默认配置（知识库未配置时的兜底） ----------

DEFAULT_SCHEMAS = {
    "民间借贷": [
        {"name": "出借人", "core": True, "hint": "出借资金一方的姓名"},
        {"name": "借款人", "core": True, "hint": "借款一方的姓名"},
        {"name": "借款金额", "core": True, "hint": "借款本金数额，如 3万元"},
        {"name": "借款日期", "core": True, "hint": "款项交付/借条签订的时间"},
        {"name": "约定利息", "core": False, "hint": "是否约定利息及利率"},
        {"name": "还款期限", "core": False, "hint": "约定的还款时间或期限"},
        {"name": "担保情况", "core": False, "hint": "有无担保人、抵押或保证"},
        {"name": "催讨情况", "core": False, "hint": "是否催讨过、最近一次催讨时间"},
    ],
    "物业服务": [
        {"name": "业主", "core": True, "hint": "业主姓名或房号"},
        {"name": "物业公司", "core": True, "hint": "物业服务企业名称"},
        {"name": "争议金额", "core": True, "hint": "欠付物业费金额"},
        {"name": "欠费期间", "core": True, "hint": "欠费起止时间"},
        {"name": "争议事由", "core": False, "hint": "拒交/欠交原因，如服务质量问题"},
    ],
    "婚姻家庭": [
        {"name": "结婚时间", "core": False, "hint": "登记结婚或共同生活起始时间"},
        {"name": "离婚方式", "core": True, "hint": "协议离婚 / 判决离婚 / 调解离婚"},
        {"name": "争议财产", "core": True, "hint": "房产/存款/车辆等财产及归属主张"},
        {"name": "子女情况", "core": False, "hint": "子女数量、年龄与抚养安排"},
        {"name": "争议焦点", "core": True, "hint": "双方分歧的核心点"},
    ],
    "侵权赔偿": [
        {"name": "侵权行为", "core": True, "hint": "侵害行为及其发生经过"},
        {"name": "损害后果", "core": True, "hint": "人身/财产损失情况与金额"},
        {"name": "发生时间地点", "core": False, "hint": "事故或侵害发生的时间、地点"},
        {"name": "责任主张", "core": True, "hint": "要求对方承担的赔偿范围"},
        {"name": "证据情况", "core": False, "hint": "照片、票据、证人等证据"},
    ],
}

DEFAULT_EXTRACT_PROMPT = """你是人民调解受理系统的要素抽取助手。请从当事人陈述中抽取以下要素：

{schema_desc}

要求：
1. 只输出一个 JSON 数组，不要输出任何其他文字或代码块标记
2. 每个要素的格式：{{"name": "要素名", "value": "抽取到的值", "quote": "陈述中对应的原句片段", "confidence": 0.95}}
3. quote 必须是陈述原文中的连续片段（逐字摘录，用于原文定位）；陈述中找不到依据的要素，value 和 quote 都填空字符串
4. confidence 是你对抽取准确性的把握（0~1 之间的小数）

当事人陈述：
{narrative}"""


def _conn():
    return pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)


# ---------- 配置读取（知识库优先，内置兜底） ----------

def load_schema(dispute_type: str) -> tuple[list[dict], str]:
    """要素 Schema：kb_schema 配置优先，未配置用内置默认。返回 (要素数组, 版本标签)。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content, schema_version FROM kb_schema WHERE dispute_type=%s",
                        (dispute_type,))
            row = cur.fetchone()
        if row and row["content"]:
            content = json.loads(row["content"]) if isinstance(row["content"], str) else row["content"]
            return content, f"v{row['schema_version']}"
    finally:
        conn.close()
    return DEFAULT_SCHEMAS.get(dispute_type, DEFAULT_SCHEMAS["民间借贷"]), "内置默认"


def _load_prompt() -> str:
    """抽取提示词：kb_prompt.extract 配置优先，未配置用内置默认。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM kb_prompt WHERE prompt_key='extract'")
            row = cur.fetchone()
        if row and row["content"]:
            return row["content"]
    finally:
        conn.close()
    return DEFAULT_EXTRACT_PROMPT


# ---------- 状态流转 ----------

def set_status(case_id: str, to_status: str, by_user_id: str | None = None, note: str = "") -> None:
    """更新案件状态并写流转时间线（append-only）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM case_info WHERE case_id=%s", (case_id,))
            row = cur.fetchone()
            if not row:
                return
            from_status = row["status"]
            if from_status == to_status:
                return
            cur.execute("UPDATE case_info SET status=%s WHERE case_id=%s", (to_status, case_id))
            cur.execute(
                "INSERT INTO case_status_history (case_id, from_status, to_status, by_user_id, note)"
                " VALUES (%s,%s,%s,%s,%s)",
                (case_id, from_status, to_status, by_user_id, note or None))
        conn.commit()
    finally:
        conn.close()


# ---------- 要素抽取（LLM，提示词驱动） ----------

def _align_offset(narrative: str, quote: str) -> tuple[int | None, int | None]:
    """引句 → 原文 offset（三层溯源层①的定位基础）。找不到返回 (None, None)。"""
    q = (quote or "").strip()
    if not q:
        return None, None
    idx = narrative.find(q)
    if idx < 0:
        # 引句可能跨自然段，去掉省略号/换行再试一次
        probe = re.split(r"[…\.]{2,}|\n", q)[0].strip()
        if len(probe) >= 6:
            idx = narrative.find(probe)
        if idx < 0:
            return None, None
    return idx, idx + len(q)


def _parse_elements_json(raw: str) -> list[dict]:
    """解析 LLM 输出（容错：剥代码块、截 []、修中文引号/尾逗号等常见漂移）。"""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M).strip()
    lo, hi = text.find("["), text.rfind("]")
    if lo < 0 or hi <= lo:
        return []
    body = text[lo:hi + 1]
    for candidate in (body, _repair_json(body)):
        try:
            data = json.loads(candidate)
            return [d for d in data if isinstance(d, dict) and d.get("name")]
        except json.JSONDecodeError:
            continue
    return []


def _repair_json(text: str) -> str:
    """修 LLM 常见 JSON 漂移：中文引号 / 尾逗号。"""
    fixed = (text.replace("“", '"').replace("”", '"')
                 .replace("‘", "'").replace("’", "'"))
    fixed = re.sub(r",\s*([\]}])", r"\1", fixed)   # 去尾逗号
    return fixed


def extract_elements(case_id: str, by_user_id: str | None = None) -> list[dict]:
    """LLM 抽取要素并入库（覆盖式：旧要素 is_current 置 0）。状态 → awaiting_confirmation。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT narrative, dispute_type FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
        if not case or not case["narrative"]:
            raise ValueError("案件不存在或陈述为空")
    finally:
        conn.close()

    schema, _ver = load_schema(case["dispute_type"])
    schema_desc = "\n".join(
        f"- {e['name']}（{'核心' if e.get('core') else '一般'}）：{e.get('hint', '')}"
        for e in schema)
    prompt = _load_prompt().replace("{schema_desc}", schema_desc).replace("{narrative}", case["narrative"])

    raw = provider.chat([{"role": "user", "content": prompt}], temperature=0.1)
    extracted = _parse_elements_json(raw)
    if not extracted:
        # 一次重试：LLM 输出格式偶发漂移，重试通常即恢复（仍失败则按"全部未抽取"落库）
        raw = provider.chat([{"role": "user", "content": prompt}], temperature=0.1)
        extracted = _parse_elements_json(raw)
    by_name = {e["name"]: e for e in extracted}

    conn = _conn()
    try:
        with conn.cursor() as cur:
            # 覆盖式重抽取：旧要素保留审计（is_current=0）
            cur.execute("UPDATE element SET is_current=0 WHERE case_id=%s AND is_current=1", (case_id,))
            for item in schema:
                got = by_name.get(item["name"], {})
                value = (got.get("value") or "").strip()
                quote = (got.get("quote") or "").strip()
                conf = got.get("confidence")
                conf = float(conf) if isinstance(conf, (int, float)) else (0.9 if value else 0.0)
                s, e = _align_offset(case["narrative"], quote)
                level = "high" if conf >= 0.8 else ("medium" if conf >= 0.5 else "low")
                cur.execute(
                    "INSERT INTO element (element_id, case_id, name, value, confidence,"
                    " confidence_level, quote, start_offset, end_offset, is_core)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (f"el_{uuid.uuid4().hex[:6]}", case_id, item["name"], value, conf, level,
                     quote or None, s, e, 1 if item.get("core") else 0))
        conn.commit()
    finally:
        conn.close()

    set_status(case_id, "awaiting_confirmation", by_user_id, "要素抽取完成")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM element WHERE case_id=%s AND is_current=1 ORDER BY id", (case_id,))
            return cur.fetchall()
    finally:
        conn.close()


# ---------- 核验分流（规则引擎） ----------

def run_verification(case_id: str, by_user_id: str | None = None) -> dict:
    """R1~R7 规则匹配 + 核心要素缺失检查 → 三级分流 → 写核验报告 + 状态流转。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT narrative FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            if not case:
                raise ValueError("案件不存在")
            cur.execute("SELECT * FROM element WHERE case_id=%s AND is_current=1", (case_id,))
            elements = cur.fetchall()
            # condition 是 MySQL 保留字，必须加反引号
            cur.execute("SELECT rule_id, name, description, severity, `condition`"
                        " FROM kb_rule WHERE enabled=1")
            rules = cur.fetchall()

        # 规则匹配范围：陈述原文 + 全部要素值
        text = (case["narrative"] or "") + "\n" + " ".join(e["value"] or "" for e in elements)
        findings, blocks, warns = [], False, False
        for r in rules:
            cond = r["condition"]
            if isinstance(cond, str):
                cond = json.loads(cond) if cond else {}
            kws = (cond or {}).get("keywords", [])
            matched = [k for k in kws if k and k in text]
            if not matched:
                continue
            findings.append({"rule_id": r["rule_id"], "name": r["name"],
                             "severity": r["severity"], "basis": r["description"],
                             "matched": matched})
            if r["severity"] == "block":
                blocks = True
            else:
                warns = True

        # 核心要素缺失/待补 → 不自动通过
        missing_core = [e["name"] for e in elements
                        if e["is_core"] and (e["needs_clarify"] or not (e["value"] or "").strip())]

        if blocks:
            level = "reject_suggestion"
        elif warns or missing_core:
            level = "pending_review"
        else:
            level = "auto_pass"

        # 结论面向受理员展示，不暴露规则内部编号（R1~R7 仅在知识库规则管理页出现）
        conclusion = {
            "auto_pass": "规则核验通过，无硬性风险项，可自动进入下一节点。",
            "pending_review": "存在需要人工复核的项：" +
                ("；".join(f["name"] for f in findings if f["severity"] == "warn")
                 or "（无额外规则命中）") +
                (f"；核心要素待补：{'、'.join(missing_core)}" if missing_core else ""),
            "reject_suggestion": "命中硬性规则：" +
                "；".join(f"{f['name']}（依据：{f['basis']}）"
                         for f in findings if f["severity"] == "block"),
        }[level]

        conn2 = _conn()
        try:
            with conn2.cursor() as cur:
                cur.execute(
                    "INSERT INTO verification_report (case_id, level, conclusion,"
                    " hard_findings, soft_findings, model, provider)"
                    " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (case_id, level, conclusion,
                     json.dumps([f for f in findings if f["severity"] == "block"], ensure_ascii=False),
                     json.dumps([f for f in findings if f["severity"] == "warn"]
                                + ([{"name": "核心要素待补", "items": missing_core}] if missing_core else []),
                                ensure_ascii=False),
                     config.CLOUD_MODEL, "cloud"))
            conn2.commit()
        finally:
            conn2.close()

        status_map = {"auto_pass": "auto_passed", "pending_review": "pending_review",
                      "reject_suggestion": "reject_suggested"}
        set_status(case_id, status_map[level], by_user_id, f"核验完成：{level}")
        return {"level": level, "conclusion": conclusion,
                "findings": findings, "missing_core": missing_core}
    finally:
        conn.close()


# ---------- 补充询问话术（LLM） ----------

def clarify_question(case_id: str, element_id: str) -> dict:
    """为某个待补要素生成补充询问话术（给受理员使用，不直接触达当事人）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT dispute_type, narrative FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            cur.execute("SELECT name, value, is_core FROM element WHERE element_id=%s AND case_id=%s",
                        (element_id, case_id))
            el = cur.fetchone()
        if not case or not el:
            raise ValueError("案件或要素不存在")
    finally:
        conn.close()

    prompt = (f"你是人民调解受理员的话术助手。受理的是一起{case['dispute_type']}纠纷，"
              f"当事人的陈述是：{case['narrative'][:300]}\n\n"
              f"当前需要向当事人补充核实「{el['name']}」这个要素"
              f"（目前值为：{el['value'] or '缺失'}）。\n\n"
              f"请生成一句自然、口语化的补充询问话术（面向调解员照着问，不超过 80 字），"
              f"只输出话术本身，不要其他文字。")
    question = provider.chat([{"role": "user", "content": prompt}], temperature=0.5).strip()
    return {"question": question, "purpose": f"补充「{el['name']}」要素"}
