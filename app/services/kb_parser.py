"""知识库 md 解析器：法条按「第X条」切条，案例按四段切。

纯函数，无 DB/网络依赖。容错原则：切不出的内容不拒收（法条整文件一条、案例缺段置空）。
"""
import re
from datetime import date

# 中文章节标题（## / ###）
_H2 = re.compile(r"^##\s+(.+)$")
_H3 = re.compile(r"^###\s+(.+)$")
# 中文条号：第四百六十三条 / 第一百二十条之一（修正案新增条文，"之X"并入条号保唯一）
_ARTICLE = re.compile(r"^(第[零一二三四五六七八九十百千两]+条(?:之[零一二三四五六七八九十]+)?)\s*(.*)")
# 施行日期行：2021年1月1日 施行
_EFFECTIVE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s*施行")
_FRONT_MATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)
_INFO_END = "<!-- INFO END -->"


def _parse_meta(head: str) -> tuple[str | None, str | None, date | None]:
    """解析文件头（INFO END 之前）：返回 (source, 编名前缀, 施行日期)。"""
    source = sub = None
    effective = None
    for line in head.splitlines():
        line = line.strip()
        if line.startswith("# ") and source is None:
            source = line[2:].strip()
        elif line.startswith("# ") and source is not None and sub is None:
            sub = line[2:].strip()
        m = _EFFECTIVE.match(line)
        if m:
            effective = date(int(m[1]), int(m[2]), int(m[3]))
    return source, sub, effective


def parse_law_md(text: str) -> dict:
    """法条 md → {source, effective_date, items: [{article, chapter, text}]}。

    章节路径 = 编名前缀 + ##/### 标题累积；正文按条号切分，条内多段合并。
    切不出条号的文件整体存一条（article=None），如鉴定标准类文本。
    """
    text = _FRONT_MATTER.sub("", text)
    if _INFO_END in text:
        head, body = text.split(_INFO_END, 1)
    else:  # 无 INFO END 的文件：第一个空行前视为文件头
        head, _, body = text.partition("\n\n")
    source, sub, effective = _parse_meta(head)

    base = [sub] if sub else []   # 编层（文件副标题）
    h2: list[str] = []            # 当前分编/编
    h3: list[str] = []            # 当前章/节
    items: list[dict] = []
    cur: dict | None = None   # 当前条文 {article, chapter, lines}
    orphan: list[str] = []    # 无条号正文（标题行之外的散段）

    def _chapter() -> str | None:
        return "·".join(base + h2 + h3) or None

    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("###") or line.startswith("##"):
            _flush(cur, orphan, _chapter(), items)   # 章节切换，先落袋
            cur, orphan = None, []
            m = _H3.match(line) if line.startswith("###") else _H2.match(line)
            if line.startswith("###"):
                h3 = [m[1]] if m else []
            else:
                h2, h3 = ([m[1]] if m else []), []
            continue
        m = _ARTICLE.match(line)
        if m:
            _flush(cur, orphan, _chapter(), items)
            cur = {"article": m[1], "chapter": _chapter(), "lines": [m[2]] if m[2] else []}
        elif cur is not None:
            cur["lines"].append(line)
        else:
            orphan.append(line)
    _flush(cur, orphan, _chapter(), items)

    if not items:  # 整文件无条号（标准类文本）：整体一条
        whole = "\n".join(p for p in body.splitlines() if p.strip() and not p.strip().startswith("#"))
        if whole:
            items.append({"article": None, "chapter": "·".join(chapter_parts) or None, "text": whole})
    return {"source": source, "effective_date": effective, "items": items}


def _flush(cur: dict | None, orphan: list[str], chapter: str | None, items: list[dict]) -> None:
    """把上一条条文或无条号散段落袋（章节切换/新条开始时调用）。"""
    if cur is not None:
        items.append({"article": cur["article"], "chapter": cur["chapter"],
                      "text": "\n".join(cur["lines"]).strip()})
    elif orphan:
        items.append({"article": None, "chapter": chapter,
                      "text": "\n".join(orphan).strip()})


# 案例四段：## 标题关键词 → 字段
_CASE_SECTIONS = [
    ("fact", ("基本案情", "案件事实", "案情")),
    ("process", ("诉讼请求", "处理过程", "调解过程", "审查过程")),
    ("result", ("裁判结果", "处理结果", "调解结果", "仲裁结果")),
    ("comment", ("案例分析", "案例评析", "评析", "分析")),
]

# ============ PDF 案例（人民法院案例库"调解案例"格式）============
# 结构：入库编号 / 标题 / ——副标题 / 关键词 / 基本案情 / 处理方式方法 / 处理结果 /
#       解纷依据 / 典型意义（或指导意义）/ 推荐部门…
_PDF_SECTION_MAP = {
    "基本案情": "fact",
    "处理方式方法": "process", "调解过程": "process",
    "处理结果": "result",
    "解纷依据": "comment", "典型意义": "comment",
    "指导意义": "comment", "案例分析": "comment",
}
_PDF_IGNORE_HEADS = ("关键词",)


def parse_case_pdf(data: bytes) -> dict:
    """人民法院案例库调解案例 PDF → {title, fact, process, result, comment}。

    PDF 抽取的换行是按版面的硬换行，需要：①修复被拆开的段标题（"指导"+"意义"）
    ②把段内各行拼回完整段落 ③清理中文间多余空格。
    """
    import io

    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    raw = "\n".join((p.extract_text() or "") for p in reader.pages)
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    heads = set(_PDF_SECTION_MAP) | set(_PDF_IGNORE_HEADS)

    # ① 修复被换行拆开的标题（如 "指导" + "意义"）
    merged = []
    i = 0
    while i < len(lines):
        two = lines[i] + (lines[i + 1] if i + 1 < len(lines) else "")
        if lines[i] not in heads and two in heads:
            merged.append(two)
            i += 2
            continue
        merged.append(lines[i])
        i += 1

    # ② 标题：入库编号之后、"——"副标题之前的正文行（跳过编号本身）
    title = None
    for i, ln in enumerate(merged):
        if "入库编号" in ln:
            buf = []
            for nxt in merged[i + 1:]:
                if nxt.startswith("——") or nxt in heads:
                    break
                buf.append(nxt)
            t = re.sub(r"^[A-Za-z]?\d{4}[\d\-]+", "", "".join(buf)).strip()
            if 6 <= len(t) <= 120:
                title = t
            break

    # ③ 按段标题切分
    sections: dict[str, list[str]] = {k: [] for k in ("fact", "process", "result", "comment")}
    cur = None
    for ln in merged:
        matched = None
        for h, key in _PDF_SECTION_MAP.items():
            if ln == h:
                matched = (key, "")
                break
            if ln.startswith(h) and len(ln) <= len(h) + 3:   # 标题与正文同行
                matched = (key, ln[len(h):])
                break
        if matched:
            cur = matched[0]
            if matched[1]:
                sections[cur].append(matched[1])
            continue
        if ln in _PDF_IGNORE_HEADS:
            cur = None
            continue
        if cur:
            sections[cur].append(ln)

    def clean(parts: list[str]) -> str | None:
        seg = "".join(parts)
        seg = re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", seg)  # 中文间空格
        return seg.strip() or None

    return {"title": title,
            **{k: clean(v) for k, v in sections.items()}}


def parse_case_md(text: str) -> dict:
    """案例 md → {title, fact, process, result, comment}。缺段为 None。"""
    text = _FRONT_MATTER.sub("", text)
    title = None
    sections: dict[str, list[str]] = {}
    cur_key: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line == _INFO_END.strip():
            continue
        if line.startswith("# "):
            if title is None:
                title = line[2:].strip()
            cur_key = None
            continue
        if line.startswith("##"):
            cur_key = None
            heading = line.lstrip("#").strip()
            for key, kws in _CASE_SECTIONS:
                if any(kw in heading for kw in kws):
                    cur_key = key
                    break
            continue
        if cur_key:
            sections.setdefault(cur_key, []).append(line)
    return {
        "title": title,
        **{k: ("\n".join(sections[k]).strip() if k in sections else None)
           for k, _ in _CASE_SECTIONS},
    }
