"""文书生成与签发服务（F6 四产出物 + F7 签发）。

生成策略（ADR-4 模板为主、LLM 为辅）：仅「案件底情」的无争议事实/争议焦点调 LLM，
失败降级（该段省略并在正文标注）；其余文书零 LLM 纯组装。

溯源锚定（三层溯源的落点，支撑"溯源覆盖率"指标）：
生成器返回单行片段 [{md, refs, sep}]，assemble() 按序拼装并累积字符偏移——
片段带 refs 就必然产出注解，覆盖率由构造保证，不依赖读取期启发式重定位。
不变量：片段 md 单行（不含 \n）——前端对锚点区间注入 <span> 高亮时不会跨 markdown 块。
偏移以 Python 字符下标计（= JS string index；片段只含 BMP 字符，无 emoji 等代理对）。
"""
import json
import re
from datetime import datetime

import pymysql

from app.core.config import config
from app.core.id_gen import gen_doc_id
from app.llm.provider import provider
from app.services import intake_service, retrieval_service

# ---------- 常量 ----------

FOUR = ("intake_form", "verify_report", "similar_cases", "case_profile")

# 可生成文书的案件状态 → 该状态下应生成的文书类型（缺省推导；显式传 types 可覆盖）
TYPES_BY_STATUS = {
    "auto_passed": FOUR,
    "documents_ready": FOUR,          # 重生成（draft 覆盖；issued 的会被跳过）
    "reject_suggested": ("reject_notice",),
}

TYPE_LABEL = {
    "intake_form": "受理登记表",
    "verify_report": "核验报告",
    "similar_cases": "类案参考与法律依据",
    "case_profile": "案件底情（要素式）",
    "reject_notice": "不予受理通知书",
    "agreement": "调解协议书",
    "termination": "调解终结书",
}

# 签发后案件进入 issued 的关键文书：受理登记表单独签发即生效；四类全部签发同样生效
_FINAL_STATUSES = ("issued", "rejected", "closed")

_LEVEL_TEXT = {
    "auto_pass": "分流结果：建议受理——无硬性风险项、核心要素齐备，可进入文书生成与签发。",
    "pending_review": "分流结果：转人工复核——存在需人工核实的项，由复核员裁决后继续。",
    "reject_suggestion": "分流结果：建议不予受理——命中硬性规则，需人工确认签发后生效。",
}


class DocumentError(Exception):
    """文书业务错误：code 供前端识别，http_status 供接口层转换。"""

    def __init__(self, code: str, message: str, http_status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _conn():
    return pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)


def _fmt_d(v) -> str:
    """日期 → YYYY年MM月DD日；datetime/date 均可。"""
    return f"{v:%Y年%m月%d日}" if v else "—"


def _fmt_dt(v) -> str:
    """datetime → YYYY-MM-DD HH:MM。"""
    return f"{v:%Y-%m-%d %H:%M}" if v else "—"


# ---------- 片段与拼装 ----------

def _clean(text) -> str:
    """片段文本清洗：换行压空格、去尖括号（防 XSS）、竖线换全角（保表格结构）。"""
    t = (text or "").replace("\r", " ").replace("\n", " ")
    t = t.replace("<", "").replace(">", "").replace("|", "｜")
    return " ".join(t.split())


def _frag(md: str, refs: list | None = None, sep: str = "\n\n",
          head: int = 0, tail: int = 0) -> dict:
    """构造片段。md 必须单行；sep = 与下一片段的间隔（表格行内用 "\\n"，块间用 "\\n\\n"）。

    head/tail：锚点相对片段首/尾的收缩量。**锚点绝不能包住行首 markdown 语法标记**
    （`|` / `- ` / `###` / `> `）——前端在锚点区间注入 <span> 高亮，若把标记包进去，
    span 会让该行丢失表格/列表/标题语义（渲染结构被破坏）。
    """
    if "\n" in md:
        raise ValueError("片段必须是单行（锚点不跨行的不变量）")
    if head + tail >= len(md):
        raise ValueError("锚点收缩量超过片段长度")
    return {"md": md, "refs": refs or [], "sep": sep, "head": head, "tail": tail}


def _table_row(cells: list[str], refs: list | None = None, sep: str = "\n") -> dict:
    """表格行片段：锚点只覆盖第一个单元格文本（跨单元格的 span 会撕裂表格）。"""
    md = "| " + " | ".join(cells) + " |"
    tail = len(md) - 2 - len(cells[0])   # "| " 之后到第一格结束
    return _frag(md, refs=refs, sep=sep, head=2, tail=tail)


def assemble(frags: list[dict]) -> tuple[str, list[dict]]:
    """片段序列 → (content_md, annotations)。偏移 = 片段起点（含分隔符累积）+ 锚点收缩。"""
    parts, anns, pos = [], [], 0
    for f in frags:
        md = f["md"]
        a = f.get("head", 0)
        b = len(md) - f.get("tail", 0)
        for r in f["refs"]:
            anns.append({"anchor_start": pos + a, "anchor_end": pos + b, **r})
        sep = f.get("sep", "\n\n")
        parts.append(md)
        parts.append(sep)
        pos += len(md) + len(sep)
    return "".join(parts[:-1]), anns          # 裁掉最后一个分隔符


def _elem_ref(element_id: str) -> dict:
    return {"annotation_type": "element_source", "ref_type": "element", "ref_id": element_id}


def _rule_ref(rule_id: str) -> dict:
    return {"annotation_type": "rule", "ref_type": "rule", "ref_id": rule_id or "?"}


# ---------- 上下文与配置 ----------

def _load_context(case_id: str) -> dict:
    """加载生成所需数据：案件 + 当前要素 + 最新核验报告 + 类案采纳记录。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT case_id, dispute_type, applicant_name, narrative, status,"
                " assignee_user_id, created_at FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            if not case:
                raise DocumentError("DOC_001", "案件不存在", 404)
            cur.execute(
                "SELECT element_id, name, value, confidence, is_core, confirmed, needs_clarify, quote"
                " FROM element WHERE case_id=%s AND is_current=1 ORDER BY id", (case_id,))
            elements = cur.fetchall()
            cur.execute(
                "SELECT level, conclusion, hard_findings, soft_findings, verified_at"
                " FROM verification_report WHERE case_id=%s ORDER BY id DESC LIMIT 1", (case_id,))
            report = cur.fetchone()
            if report:
                for k in ("hard_findings", "soft_findings"):
                    v = report[k]
                    if isinstance(v, str):   # pymysql 对 JSON 列返回字符串
                        v = json.loads(v) if v else []
                    report[k] = v or []
            cur.execute(
                "SELECT id, ref_id, content FROM assist_adoption"
                " WHERE case_id=%s AND target='similar_case_doc' ORDER BY id", (case_id,))
            adoptions = cur.fetchall()
            # 调解结果（M3）：协议书/终结书生成的数据源；表未建时视为无（M1 接口不受影响）
            try:
                cur.execute(
                    "SELECT reached, settlement, judicial_confirmation, inherited_snapshot,"
                    " recorded_by FROM mediation_result WHERE case_id=%s", (case_id,))
                mediation = cur.fetchone()
                if mediation:
                    for k in ("settlement", "inherited_snapshot"):
                        v = mediation[k]
                        if isinstance(v, str):
                            mediation[k] = json.loads(v) if v else None
            except Exception:
                mediation = None
    finally:
        conn.close()
    return {"case": case, "elements": elements, "report": report,
            "adoptions": adoptions, "mediation": mediation}


def _build_query(ctx: dict) -> str:
    """检索查询串：案由 + 全部非空要素值（对齐讲义"案由+要素值拼接构造"）。"""
    parts = [ctx["case"]["dispute_type"]]
    parts += [f"{e['name']}{e['value']}" for e in ctx["elements"] if (e["value"] or "").strip()]
    return " ".join(parts)


def _case_titles(ref_ids: list) -> dict:
    """批量反查案例标题：case_{id} → title。查不到的不返回（调用方兜底）。"""
    ids = [r.split("_", 1)[1] for r in ref_ids if r and r.startswith("case_") and r.split("_", 1)[1].isdigit()]
    if not ids:
        return {}
    conn = _conn()
    try:
        with conn.cursor() as cur:
            fmt = ",".join(["%s"] * len(ids))
            cur.execute(f"SELECT id, title FROM case_ref WHERE id IN ({fmt})", ids)
            return {f"case_{r['id']}": r["title"] for r in cur.fetchall()}
    finally:
        conn.close()


# ---------- 五个生成器（纯函数：只读 ctx，返回片段列表） ----------

def gen_intake_form(ctx: dict) -> list[dict]:
    """受理登记表：纯模板渲染，零 LLM。数据 = 要素表（含确认状态与原文引句）。"""
    case, els = ctx["case"], ctx["elements"]
    frags = [_frag("# 人民调解受理登记表")]
    frags.append(_frag(
        f"**受理编号**：{case['case_id']}　**纠纷类型**：{case['dispute_type']}"
        f"　**受理日期**：{_fmt_d(case.get('created_at'))}"))
    frags.append(_frag(
        f"**当事人**：{_clean(case['applicant_name'])}"
        f"　**承办受理员**：{case.get('assignee_user_id') or '—'}"))

    # 未确认/待补要素警示（软提示，不设硬门——"系统只起草、不拍板"，核实权在签发人）
    pending = [e for e in els if (e["value"] or "").strip() and (e["needs_clarify"] or not e["confirmed"])]
    if pending:
        names = "、".join(_clean(e["name"]) for e in pending)
        frags.append(_frag(f"> ⚠ 本表含未确认或待补要素 {len(pending)} 项（{names}），签发前请核实。"))

    if case.get("narrative"):
        frags.append(_frag("## 一、当事人陈述摘要"))
        frags.append(_frag(_clean(case["narrative"][:200]) + "…"))

    frags.append(_frag("## 二、要素确认表"))
    frags.append(_frag("| 要素 | 内容 | 核心 | 确认状态 | 原文依据 |", sep="\n"))
    frags.append(_frag("| --- | --- | --- | --- | --- |", sep="\n"))
    for i, e in enumerate(els):
        val = _clean(e["value"]) if e["value"] else "（未抽取）"
        state = "待补" if e["needs_clarify"] else ("已确认" if e["confirmed"] else "未确认")
        quote = f"“{_clean(e['quote'])[:40]}”" if e.get("quote") else "—"
        refs = [_elem_ref(e["element_id"])] if e["value"] else []
        sep = "\n\n" if i == len(els) - 1 else "\n"
        frags.append(_table_row(
            [_clean(e["name"]), val, "★" if e["is_core"] else "", state, quote],
            refs=refs, sep=sep))

    report = ctx.get("report")
    frags.append(_frag("## 三、核验情况"))
    frags.append(_frag(_clean(report["conclusion"]) if report and report.get("conclusion")
                       else "（尚无核验记录）"))

    frags.append(_frag("## 四、受理意见"))
    frags.append(_frag("经审查，本纠纷属于人民调解受理范围，申请材料齐备，同意受理。"))
    frags.append(_frag("受理员（签字）：______　　日期：______"))
    return frags


def gen_verify_report(ctx: dict) -> list[dict]:
    """核验报告：组装核验数据（零 LLM）+ 法律依据参考节（知识库检索，仅法条）。"""
    case, els = ctx["case"], ctx["elements"]
    report = ctx.get("report")
    frags = [_frag("# 受理核验报告")]
    frags.append(_frag(
        f"**案件**：{case['case_id']}　**纠纷类型**：{case['dispute_type']}"
        f"　**核验时间**：{_fmt_dt(report.get('verified_at')) if report else '—'}"))

    frags.append(_frag("## 一、核验结论"))
    frags.append(_frag(_clean(report["conclusion"]) if report and report.get("conclusion")
                       else "（尚无核验记录）"))

    hard = (report or {}).get("hard_findings") or []
    frags.append(_frag(f"## 二、硬性规则命中（{len(hard)} 项）"))
    if hard:
        for f in hard:
            frags.append(_frag(
                f"- **{_clean(f.get('name'))}**　命中关键词：{_clean('、'.join(f.get('matched') or []))}",
                refs=[_rule_ref(f.get("rule_id"))], sep="\n", head=2))
            frags.append(_frag(f"  依据：{_clean(f.get('basis'))}"))
    else:
        frags.append(_frag("未命中硬性规则。"))

    soft = (report or {}).get("soft_findings") or []
    frags.append(_frag(f"## 三、复核项（{len(soft)} 项）"))
    if soft:
        for f in soft:
            if "items" in f:   # 核心要素待补：回查要素 ID 锚定
                items = f.get("items") or []
                refs = [_elem_ref(e["element_id"]) for nm in items
                        for e in els if e["name"] == nm]
                frags.append(_frag(
                    f"- **{_clean(f.get('name', '待补项'))}**：{'、'.join(_clean(x) for x in items)}",
                    refs=refs, head=2))
            else:
                frags.append(_frag(
                    f"- **{_clean(f.get('name'))}**　命中关键词：{_clean('、'.join(f.get('matched') or []))}",
                    refs=[_rule_ref(f.get("rule_id"))], sep="\n", head=2))
                frags.append(_frag(f"  依据：{_clean(f.get('basis'))}"))
    else:
        frags.append(_frag("未命中软审查项，核心要素齐备。"))

    # 四、法律依据参考：检索只要法条（案例归"类案参考"文书）；异常降级为空，不阻塞报告
    try:
        laws = retrieval_service.retrieve(_build_query(ctx), top_laws=3, top_cases=0)["laws"]
    except Exception:
        laws = []
    frags.append(_frag(f"## 四、法律依据参考（知识库检索命中 {len(laws)} 条）"))
    if laws:
        for l in laws:
            t = _clean(l["text"])   # 灌库时 document 已带"《法名》章 条号："前缀，此处不再包裹
            frags.append(_frag(
                f"{t[:140]}{'…' if len(t) > 140 else ''}",
                refs=[{"annotation_type": "law", "ref_type": "law", "ref_id": l["ref_id"]}]))
    else:
        frags.append(_frag("未检索到与本案直接相关的法条（相似度阈值 0.42，宁缺毋滥）。"))

    frags.append(_frag("## 五、分流结果"))
    frags.append(_frag(_LEVEL_TEXT.get((report or {}).get("level"), "（未核验）")))
    return frags


def gen_similar_cases(ctx: dict) -> list[dict]:
    """类案参考：检索驱动（零 LLM）——知识库检索命中 + 人工采纳清单（去重）。"""
    case = ctx["case"]
    adoptions = ctx.get("adoptions") or []
    adopted_ids = {a["ref_id"] for a in adoptions if a.get("ref_id")}

    frags = [_frag("# 类案参考与法律依据")]
    frags.append(_frag(
        f"**案件**：{case['case_id']}　**纠纷类型**：{case['dispute_type']}"
        f"　**生成时间**：{_fmt_dt(datetime.now())}"))

    try:
        cases, err = retrieval_service.retrieve(_build_query(ctx), top_laws=0, top_cases=5)["cases"], None
    except Exception as e:
        cases, err = [], str(e)[:80]

    frags.append(_frag(f"## 一、知识库检索命中（{len(cases)} 例）"))
    if cases:
        for i, c in enumerate(cases):
            sim = round(1 - c["distance"], 2)   # cosine 距离 → 相似度（阈值 0.42 → ≥0.58 才命中）
            mark = "（已采纳）" if c["ref_id"] in adopted_ids else ""
            frags.append(_frag(f"### {i + 1}. {_clean(c['title'])}{mark}（相似度 {sim:.2f}）",
                               refs=[{"annotation_type": "similar_case", "ref_type": "case",
                                      "ref_id": c["ref_id"]}], sep="\n", head=4))
            # 父块摘要首行是"【案例】标题"（灌库时拼装），标题已在上行展示，去掉避免重复
            summary = c["summary"] or ""
            if summary.startswith("【案例】") and "\n" in summary:
                summary = summary.split("\n", 1)[1]
            frags.append(_frag(_clean(summary)[:200] or "（无摘要）", sep="\n"))
            frags.append(_frag(f"相关段落：{_clean(c['hit_text'])[:200]}"))
    elif err:
        frags.append(_frag(f"> 检索服务暂不可用（{err}），稍后重新生成可恢复。"))
    else:
        frags.append(_frag("> 知识库暂未检索到相关类案（相似度阈值 0.42，宁缺毋滥）。"))

    # 二、人工采纳的类案（已在检索命中里出现的去重，仅标题标"（已采纳）"）
    fresh = [a for a in adoptions if a.get("ref_id") not in {c["ref_id"] for c in cases}]
    frags.append(_frag(f"## 二、人工采纳的类案（{len(fresh)} 例）"))
    if fresh:
        titles = _case_titles([a["ref_id"] for a in fresh])
        for a in fresh:
            title = titles.get(a.get("ref_id")) or "人工采纳的类案"
            refs = [{"annotation_type": "similar_case", "ref_type": "case", "ref_id": a["ref_id"]}] \
                if a.get("ref_id") else []
            frags.append(_frag(f"### {_clean(title)}", refs=refs, sep="\n", head=4))
            frags.append(_frag(_clean(a["content"])[:300]))
    else:
        frags.append(_frag("暂无人工采纳的类案（可在 AI 助手引用卡片中点「采纳到本案」）。"))

    frags.append(_frag("## 三、使用说明"))
    frags.append(_frag("类案仅供调解参考与释法说理，不构成裁判依据；引用案例均来自公开渠道。"))
    return frags


def gen_case_profile(ctx: dict) -> list[dict]:
    """案件底情：数据表组装 + LLM 起草「无争议事实/争议焦点」（失败降级标注）。"""
    case, els = ctx["case"], ctx["elements"]
    frags = [_frag("# 案件底情（要素式）")]

    frags.append(_frag("## 一、基本情况"))
    frags.append(_frag("| 项目 | 内容 |", sep="\n"))
    frags.append(_frag("| --- | --- |", sep="\n"))
    rows = [
        ("案件编号", case["case_id"]),
        ("纠纷类型", case["dispute_type"]),
        ("当事人", _clean(case["applicant_name"])),
        ("承办受理员", case.get("assignee_user_id") or "—"),
        ("受理日期", _fmt_d(case.get("created_at"))),
    ]
    for i, (k, v) in enumerate(rows):
        frags.append(_frag(f"| {k} | {v} |", sep="\n\n" if i == len(rows) - 1 else "\n"))

    sections, err = _draft_profile_sections(ctx)
    core_refs = [_elem_ref(e["element_id"]) for e in els
                 if e["is_core"] and (e["value"] or "").strip()][:8]

    def _llm_frag(key: str) -> dict:
        if sections and sections.get(key):
            return _frag(_clean(sections[key]), refs=core_refs)
        return _frag(f"> （AI 起草不可用{'：' + err if err else ''}，本段未生成；可重新生成或人工补充。）")

    frags.append(_frag("## 二、无争议事实"))
    frags.append(_llm_frag("undisputed"))
    frags.append(_frag("## 三、争议焦点"))
    frags.append(_llm_frag("focus"))

    frags.append(_frag("## 四、要素明细（含原文引句）"))
    if els:
        for e in els:
            val = _clean(e["value"]) if e["value"] else "（未抽取）"
            mark = "（待补）" if e["needs_clarify"] else ("" if e["confirmed"] else "（未确认）")
            conf = f"　置信度 {int(e['confidence'] * 100)}%" if e["value"] else ""
            refs = [_elem_ref(e["element_id"])] if e["value"] else []
            frags.append(_frag(f"- **{_clean(e['name'])}**：{val}{mark}{conf}", refs=refs, sep="\n", head=2))
            if e.get("quote"):
                frags.append(_frag(f"  原文：“{_clean(e['quote'])[:60]}”"))
    else:
        frags.append(_frag("（本案尚无要素记录）"))
    return frags


def gen_reject_notice(ctx: dict) -> list[dict]:
    """不予受理通知书：模板渲染，数据 = 硬规则命中详情（零 LLM）。"""
    case = ctx["case"]
    report = ctx.get("report")
    hard = (report or {}).get("hard_findings") or []

    frags = [_frag("# 不予受理通知书")]
    frags.append(_frag(f"**编号**：{case['case_id']}-BYS　**致**：{_clean(case['applicant_name'])}"))
    frags.append(_frag(f"**纠纷类型**：{case['dispute_type']}　**审查日期**：{_fmt_d(datetime.now())}"))

    frags.append(_frag("## 一、审查情况"))
    frags.append(_frag(_clean(report["conclusion"]) if report and report.get("conclusion")
                       else "（尚无核验记录）"))

    frags.append(_frag(f"## 二、不予受理理由（命中硬性规则 {len(hard)} 条）"))
    if hard:
        for f in hard:
            frags.append(_frag(f"- **{_clean(f.get('name'))}**：{_clean(f.get('basis'))}",
                               refs=[_rule_ref(f.get("rule_id"))], head=2))
    else:
        frags.append(_frag("（无明细）"))

    frags.append(_frag("## 三、告知事项"))
    frags.append(_frag("1. 如对本决定有异议，可向有管辖权的人民法院提起诉讼；"
                       "2. 属于其他机关职责范围的，可向相应机关申请处理；"
                       "3. 补充材料后符合条件的，可重新申请调解。"))
    frags.append(_frag("## 四、落款"))
    frags.append(_frag("受理员（签字）：______　　日期：______"))
    frags.append(_frag("> 本通知书经人工签发后生效。"))
    return frags


# ---------- 调解结案文书（M3：协议书 / 终结书，纯模板渲染零 LLM） ----------

def _fmt_money(v) -> str:
    """金额展示：整数加千分位，异常值原样清洗返回。"""
    try:
        f = float(v)
        return f"{f:,.0f}" if f == int(f) else f"{f:,.2f}"
    except (TypeError, ValueError):
        return _clean(str(v or "")) or "____"


def _split_parties(name: str) -> tuple[str, str]:
    """展示名拆双方：'王某 vs 张某' → ('王某','张某')；拆不出返回 (name, '')。"""
    for sep in (" vs ", " v. ", "诉"):
        if sep in name:
            a, _, b = name.partition(sep)
            return _clean(a), _clean(b)
    return _clean(name), ""


def _facts_desc(ctx: dict) -> tuple[str, list[dict]]:
    """纠纷主要事实段（协议书/终结书共用）：从录入时刻快照拼装 + 全要素溯源引用。"""
    case = ctx["case"]
    snap = (ctx.get("mediation") or {}).get("inherited_snapshot") or []

    def pick(name: str) -> str:
        for it in snap:
            if it.get("field") == name:
                return _clean(it.get("value") or "")
        return ""

    desc = []
    if pick("借款金额"):
        borrower = pick("借款人") or "借款人"
        lender = pick("出借人") or "出借人"
        when = f"于{pick('借款日期')}" if pick("借款日期") else ""
        desc.append(f"{borrower}向{lender}借款{pick('借款金额')}{when}。")
    if pick("约定利息"):
        desc.append(f"利息约定：{pick('约定利息')}。")
    if pick("还款期限"):
        desc.append(f"还款期限：{pick('还款期限')}。")
    if pick("催讨情况"):
        desc.append(f"履行情况：{pick('催讨情况')}。")
    known = {"出借人", "借款人", "借款金额", "借款日期", "还款期限", "约定利息", "担保情况", "催讨情况"}
    others = [it for it in snap if it.get("field") not in known and (it.get("value") or "").strip()]
    if others:
        desc.append("其他查明要素：" + "；".join(
            f"{_clean(it['field'])}：{_clean(it['value'])}" for it in others[:6]) + "。")
    if not desc:
        desc.append(f"本案系{case['dispute_type']}纠纷，双方经调解就争议事项协商一致。")
    refs = [{"annotation_type": "element_source", "ref_type": "element",
             "ref_id": it["from_element"]}
            for it in snap if it.get("from_element") and (it.get("value") or "").strip()]
    return "".join(desc), refs


def gen_agreement(ctx: dict) -> list[dict]:
    """《调解协议书》（G2 录入达成时生成）：纯模板渲染，要素继承自录入时刻快照。"""
    case = ctx["case"]
    med = ctx.get("mediation") or {}
    sett = med.get("settlement") or {}
    installments = sett.get("installments") or []
    amount_raw = sett.get("principal_agreed")
    parties = _split_parties(case.get("applicant_name") or "")
    fact, refs = _facts_desc(ctx)

    frags = [_frag("# 人民调解协议书（要素式）")]
    frags.append(_frag(f"**编号**：{case['case_id']}-XYS"))
    frags.append(_frag(f"**当事人**：{parties[0] or '——'}、{parties[1] or '——'}"))
    frags.append(_frag("## 一、纠纷主要事实与争议事项"))
    frags.append(_frag(fact, refs=refs))
    frags.append(_frag("## 二、达成协议内容"))
    if installments:
        for i, it in enumerate(installments):
            seq = it.get("seq") or (i + 1)
            frags.append(_frag(
                f"- 第{seq}期：于 {_clean(it.get('due_date') or '____')} 前支付 {_fmt_money(it.get('amount'))} 元",
                head=2))
        frags.append(_frag(f"**还款总额**：{_fmt_money(amount_raw)} 元"
                           + ("（双方确认互不主张利息）" if sett.get("interest_waived") else "")))
    else:
        if amount_raw is not None:
            frags.append(_frag(f"- 乙方于 {_clean(sett.get('deadline') or '____')} 前一次性支付 "
                               f"{_fmt_money(amount_raw)} 元", head=2))
        else:
            frags.append(_frag("- 履行方案以双方约定为准", head=2))
    if sett.get("pay_method"):
        frags.append(_frag(f"**履行方式**：{_clean(sett['pay_method'])}"))
    frags.append(_frag("## 三、其他约定"))
    frags.append(_frag(
        "本协议自双方签字（按印）之日起生效。双方可自协议生效之日起三十日内共同向人民法院申请司法确认。"
        if med.get("judicial_confirmation") else
        "本协议自双方签字（按印）之日起生效；是否申请司法确认由双方另行协商。"))
    frags.append(_frag("## 四、落款"))
    frags.append(_frag("甲方（签名）：______　　乙方（签名）：______"))
    frags.append(_frag("调解员：______　　调解组织（盖章）　　日期：____年__月__日"))
    return frags


def gen_termination(ctx: dict) -> list[dict]:
    """《调解终结书》（G2 录入未达成时生成）：纯模板渲染，零 LLM。"""
    case = ctx["case"]
    med = ctx.get("mediation") or {}
    reason = _clean((med.get("settlement") or {}).get("termination_reason") or "")
    parties = _split_parties(case.get("applicant_name") or "")
    fact, refs = _facts_desc(ctx)

    frags = [_frag("# 人民调解终结书")]
    frags.append(_frag(f"**编号**：{case['case_id']}-ZJS"))
    frags.append(_frag(f"**当事人**：{parties[0] or '——'}、{parties[1] or '——'}"))
    frags.append(_frag("## 一、纠纷主要事实"))
    frags.append(_frag(fact, refs=refs))
    frags.append(_frag("## 二、调解情况"))
    frags.append(_frag(f"经调解，因{reason or '双方未能达成一致'}，调解未能达成协议，本次调解终结。"))
    frags.append(_frag("## 三、告知事项"))
    frags.append(_frag("当事人可以依法通过诉讼、仲裁等途径解决争议；"
                       "补充材料或条件成熟后，可就同一纠纷重新申请调解。"))
    frags.append(_frag("## 四、落款"))
    frags.append(_frag("调解员：______　　调解组织（盖章）　　日期：____年__月__日"))
    return frags


GENERATORS = {
    "intake_form": gen_intake_form,
    "verify_report": gen_verify_report,
    "similar_cases": gen_similar_cases,
    "case_profile": gen_case_profile,
    "reject_notice": gen_reject_notice,
    "agreement": gen_agreement,
    "termination": gen_termination,
}


# ---------- LLM 起草（案件底情专用；kb_prompt 配置优先，内置兜底） ----------

DEFAULT_PROFILE_PROMPT = """你是人民调解受理工位的文书助手。请基于以下案件要素，起草「案件底情」中的两段内容。

案件类型：{dispute_type}
案件要素（含原文引句）：
{elements_desc}

要求：
1. 只输出一个 JSON 对象：{{"undisputed": "无争议事实（1~2 句）", "focus": "争议焦点（1~2 句）"}}
2. 只能使用上述要素中出现的事实，禁止编造；要素未覆盖的内容宁缺毋滥（可如实写"借款用途不明"）
3. 只陈述事实与双方分歧，不作法律评价、不给结论
4. 不要输出任何其他文字或代码块标记"""


def _load_prompt() -> str:
    """文书起草提示词：kb_prompt.profile 配置优先，未配置用内置默认（"改配置不发版"）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM kb_prompt WHERE prompt_key='profile'")
            row = cur.fetchone()
        if row and row["content"]:
            return row["content"]
    finally:
        conn.close()
    return DEFAULT_PROFILE_PROMPT


def _parse_profile_json(raw: str) -> dict | None:
    """解析 LLM 输出的 {undisputed, focus}（容错：剥代码块、截 {}、修中文引号/尾逗号）。"""
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.M).strip()
    lo, hi = text.find("{"), text.rfind("}")
    if lo < 0 or hi <= lo:
        return None
    body = text[lo:hi + 1]
    # _repair_json 与要素抽取共用同一套容错（中文引号/尾逗号）
    for candidate in (body, intake_service._repair_json(body)):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None


def _draft_profile_sections(ctx: dict) -> tuple[dict | None, str | None]:
    """LLM 起草两段。成功返回 ({undisputed, focus}, None)，失败 (None, 原因)——不抛异常。"""
    case, els = ctx["case"], ctx["elements"]
    desc = "\n".join(
        f"- {e['name']}：{e['value'] or '（未抽取）'}"
        + (f"（原文引句：{e['quote']}）" if e.get("quote") else "")
        for e in els)
    prompt = (_load_prompt()
              .replace("{dispute_type}", case["dispute_type"])
              .replace("{elements_desc}", desc))
    try:
        raw = provider.chat([{"role": "user", "content": prompt}], temperature=0.1)
    except Exception as e:
        return None, f"模型调用失败（{type(e).__name__}）"
    data = _parse_profile_json(raw)
    if not data:
        return None, "模型输出解析失败"
    return {
        "undisputed": (data.get("undisputed") or "").strip() or None,
        "focus": (data.get("focus") or "").strip() or None,
    }, None


# ---------- 主流程 ----------

def generate(case_id: str, types: list | None, by_user_id: str) -> dict:
    """生成/重生成文书。draft 覆盖（doc_id 不变、注解重写）；issued 跳过。

    单类失败只记 warning 不整单失败；生成成功后 auto_passed → documents_ready。
    """
    ctx = _load_context(case_id)
    status = ctx["case"]["status"]
    targets = list(types) if types else list(TYPES_BY_STATUS.get(status, ()))
    if not targets:
        raise DocumentError("DOC_003", f"当前状态（{status}）不可生成文书")
    unknown = [t for t in targets if t not in GENERATORS]
    if unknown:
        raise DocumentError("DOC_003", f"不支持的文书类型：{'、'.join(unknown)}", 400)

    # 生成在事务外（LLM/检索可能较慢），逐类容错
    generated, skipped, warnings, built = [], [], [], []
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT doc_id, type, status FROM document WHERE case_id=%s", (case_id,))
            existing = {r["type"]: r for r in cur.fetchall()}
    finally:
        conn.close()

    for t in targets:
        row = existing.get(t)
        if row and row["status"] == "issued":
            skipped.append({"type": t, "reason": "已签发"})
            continue
        try:
            frags = GENERATORS[t](ctx)
            content, anns = assemble(frags)
        except Exception as e:   # 单类失败不整单失败（内容异常也不该阻断其余文书）
            warnings.append(f"{TYPE_LABEL[t]}生成失败：{str(e)[:120]}")
            continue
        built.append((t, content, anns, row))

    if not built:
        if skipped:
            raise DocumentError("DOC_002", "所选文书均已签发，不可重新生成")
        raise DocumentError("DOC_003", "文书生成失败，请查看提示后重试")

    conn = _conn()
    try:
        with conn.cursor() as cur:
            for t, content, anns, row in built:
                title = TYPE_LABEL[t]
                if row:   # 已有 draft：覆盖内容，保留 doc_id（注解按 doc_id 关联）
                    doc_id = row["doc_id"]
                    cur.execute("UPDATE document SET title=%s, content_md=%s WHERE doc_id=%s",
                                (title, content, doc_id))
                    cur.execute("DELETE FROM document_annotation WHERE doc_id=%s", (doc_id,))
                else:
                    doc_id = gen_doc_id()
                    cur.execute(
                        "INSERT INTO document (doc_id, case_id, type, title, content_md)"
                        " VALUES (%s,%s,%s,%s,%s)", (doc_id, case_id, t, title, content))
                if anns:
                    cur.executemany(
                        "INSERT INTO document_annotation (doc_id, annotation_type,"
                        " anchor_start, anchor_end, ref_type, ref_id) VALUES (%s,%s,%s,%s,%s,%s)",
                        [(doc_id, a["annotation_type"], a["anchor_start"], a["anchor_end"],
                          a["ref_type"], a["ref_id"]) for a in anns])
                generated.append({"doc_id": doc_id, "type": t, "title": title,
                                  "chars": len(content), "annotations": len(anns)})
        conn.commit()
    finally:
        conn.close()

    # 采纳回流打通：类案参考文书存在时，把采纳记录的目标载体半回写为 doc_id
    sc = next((g for g in generated if g["type"] == "similar_cases"), None)
    if sc:
        _backfill_adoption_target(case_id, sc["doc_id"])

    if ctx["case"]["status"] == "auto_passed":
        intake_service.set_status(case_id, "documents_ready", by_user_id,
                                  f"生成文书 {len(generated)} 份，待签发")

    return {"generated": generated, "skipped": skipped, "warnings": warnings,
            "case_status": _case_status(case_id)}


def _backfill_adoption_target(case_id: str, doc_id: str) -> None:
    """采纳记录 target_doc_id 语义升级：类案参考文书生成后，指向最终载体文档。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE assist_adoption SET target_doc_id=%s"
                " WHERE case_id=%s AND target='similar_case_doc'", (doc_id, case_id))
        conn.commit()
    finally:
        conn.close()


def issue(case_id: str, doc_id: str, by_user_id: str) -> dict:
    """签发（人工介入③，不可逆）：原子 check-and-set 防并发双击。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT doc_id, type, status FROM document WHERE doc_id=%s AND case_id=%s",
                        (doc_id, case_id))
            doc = cur.fetchone()
            if not doc:
                raise DocumentError("DOC_001", "文书不存在", 404)
            if doc["status"] == "issued":   # 已签发优先报 DOC_004（比"状态不允许"更准确）
                raise DocumentError("DOC_004", "该文书已签发（签发不可逆）")
            cur.execute("SELECT status FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            if not case:
                raise DocumentError("DOC_001", "案件不存在", 404)

            # 允许签发的案件状态：通知书 → 不予受理意见（草案）态；结案文书 → 已签发态；
            # 其余（四产出物）→ 待签发态
            if doc["type"] == "reject_notice":
                allowed = {"reject_suggested"}
            elif doc["type"] in ("agreement", "termination"):
                allowed = {"issued"}
            else:
                allowed = {"documents_ready"}
            if case["status"] not in allowed:
                raise DocumentError(
                    "DOC_005",
                    f"案件当前状态不可签发该文书（如要素已重新核验，请重新生成后再签发）")

            cur.execute(
                "UPDATE document SET status='issued', issued_by=%s, issued_at=NOW(3)"
                " WHERE doc_id=%s AND status='draft'", (by_user_id, doc_id))
            if cur.rowcount == 0:   # 已被签发（含并发第二次点击）
                conn.rollback()
                raise DocumentError("DOC_004", "该文书已签发（签发不可逆）")
            cur.execute("SELECT issued_at FROM document WHERE doc_id=%s", (doc_id,))
            issued_at = cur.fetchone()["issued_at"]
        conn.commit()
    finally:
        conn.close()

    final = _finalize(case_id, doc["type"], by_user_id)
    return {"doc_id": doc_id, "type": doc["type"], "status": "issued",
            "issued_by": by_user_id, "issued_at": str(issued_at), **final}


def _finalize(case_id: str, doc_type: str, by_user_id: str) -> dict:
    """签发后终态判定：通知书 → rejected；结案文书 → closed；
    登记表签发或四类全签 → issued（残稿一并归档）。"""
    if doc_type == "reject_notice":
        intake_service.set_status(case_id, "rejected", by_user_id, "不予受理通知书已签发")
        return {"case_status": "rejected", "also_issued": []}

    if doc_type in ("agreement", "termination"):
        intake_service.set_status(case_id, "closed", by_user_id,
                                  f"{TYPE_LABEL[doc_type]}已签发，案件结案")
        return {"case_status": "closed", "also_issued": []}

    conn = _conn()
    try:
        with conn.cursor() as cur:
            fmt = ",".join(["%s"] * len(FOUR))
            cur.execute(f"SELECT doc_id, type, status FROM document"
                        f" WHERE case_id=%s AND type IN ({fmt})", (case_id, *FOUR))
            rows = cur.fetchall()
            issued_types = {r["type"] for r in rows if r["status"] == "issued"}
            if set(FOUR) <= issued_types or "intake_form" in issued_types:
                others = [r["doc_id"] for r in rows if r["status"] == "draft"]
                if others:
                    cur.execute(
                        "UPDATE document SET status='issued', issued_by=%s, issued_at=NOW(3)"
                        " WHERE case_id=%s AND status='draft'", (by_user_id, case_id))
                conn.commit()
                # ponytail: 提交后重读判定，两路并发签不同文书时理论上都判"未集齐"；
                # 单进程演示场景可接受，升级路径 = 同一事务内对 document 行 FOR UPDATE
                done = len(issued_types) + len(others)
                intake_service.set_status(case_id, "issued", by_user_id,
                                          f"文书签发完成（{done}/{len(FOUR)}），案件已受理")
                return {"case_status": "issued", "also_issued": others}
            conn.commit()
    finally:
        conn.close()
    return {"case_status": "documents_ready", "also_issued": []}


def _case_status(case_id: str) -> str:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM case_info WHERE case_id=%s", (case_id,))
            row = cur.fetchone()
            return row["status"] if row else ""
    finally:
        conn.close()


# ---------- 查询 ----------

def list_documents(case_id: str) -> dict:
    """文书列表：doc 元信息 + 案件状态 + 是否可生成（前端按此渲染按钮）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT case_id, status FROM case_info WHERE case_id=%s", (case_id,))
            case = cur.fetchone()
            if not case:
                raise DocumentError("DOC_001", "案件不存在", 404)
            cur.execute(
                "SELECT doc_id, type, title, status, issued_by, issued_at,"
                " CHAR_LENGTH(content_md) AS chars, updated_at"
                " FROM document WHERE case_id=%s ORDER BY FIELD(type,"
                " 'case_profile','verify_report','intake_form','similar_cases',"
                " 'reject_notice','agreement','termination')", (case_id,))
            rows = cur.fetchall()
            ann_counts = {}
            if rows:
                ids = [r["doc_id"] for r in rows]
                fmt = ",".join(["%s"] * len(ids))
                cur.execute(f"SELECT doc_id, COUNT(DISTINCT anchor_start, anchor_end) AS n"
                            f" FROM document_annotation WHERE doc_id IN ({fmt}) GROUP BY doc_id", ids)
                ann_counts = {r["doc_id"]: r["n"] for r in cur.fetchall()}
    finally:
        conn.close()
    return {
        "case_id": case_id,
        "case_status": case["status"],
        "generatable": case["status"] in TYPES_BY_STATUS and not _all_issued(rows),
        "items": [{
            "doc_id": r["doc_id"], "type": r["type"], "title": r["title"],
            "type_label": TYPE_LABEL.get(r["type"], r["type"]),
            "status": r["status"], "status_label": "已签发" if r["status"] == "issued" else "草案",
            "issued_by": r["issued_by"],
            "issued_at": str(r["issued_at"]) if r["issued_at"] else None,
            "annotation_count": ann_counts.get(r["doc_id"], 0),
            "chars": r["chars"], "updated_at": str(r["updated_at"]),
        } for r in rows],
    }


def _all_issued(rows: list) -> bool:
    """请求状态推导出的类型已全部签发 → 不可再生成（存量文书列表判据）。"""
    return bool(rows) and all(r["status"] == "issued" for r in rows)


def get_document(case_id: str, doc_id: str) -> dict:
    """文书详情：正文 + 溯源注解（联表填 label/sub_label）+ 覆盖率统计。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, case_id, type, title, content_md, status,"
                " issued_by, issued_at, updated_at FROM document"
                " WHERE doc_id=%s AND case_id=%s", (doc_id, case_id))
            doc = cur.fetchone()
            if not doc:
                raise DocumentError("DOC_001", "文书不存在", 404)
            # 联表填展示字段（单文书锚点 10~40 行，量级无碍）
            # ponytail: CONCAT 连接条件不走索引；量大时按 ref_type 分三批 IN 查询
            cur.execute(
                "SELECT a.annotation_type, a.anchor_start, a.anchor_end,"
                " a.ref_type, a.ref_id,"
                " COALESCE(e.name, l.source, c.title, a.ref_id) AS label,"
                " COALESCE(e.value, l.article, c.source, '') AS sub_label"
                " FROM document_annotation a"
                " LEFT JOIN element e ON a.ref_type='element' AND e.element_id = a.ref_id"
                " LEFT JOIN law l ON a.ref_type='law' AND CONCAT('law_', l.id) = a.ref_id"
                " LEFT JOIN case_ref c ON a.ref_type='case' AND CONCAT('case_', c.id) = a.ref_id"
                " WHERE a.doc_id=%s ORDER BY a.anchor_start, a.id", (doc_id,))
            anns = cur.fetchall()
    finally:
        conn.close()

    content = doc["content_md"] or ""
    lines = [ln for ln in content.splitlines() if ln.strip()]
    segments = {(a["anchor_start"], a["anchor_end"]) for a in anns}
    return {
        "doc": {
            "doc_id": doc["doc_id"], "case_id": doc["case_id"], "type": doc["type"],
            "title": doc["title"], "type_label": TYPE_LABEL.get(doc["type"], doc["type"]),
            "content_md": content, "status": doc["status"],
            "status_label": "已签发" if doc["status"] == "issued" else "草案",
            "issued_by": doc["issued_by"],
            "issued_at": str(doc["issued_at"]) if doc["issued_at"] else None,
            "updated_at": str(doc["updated_at"]),
        },
        "annotations": anns,
        "stats": {"annotations": len(segments), "lines": len(lines)},
    }
