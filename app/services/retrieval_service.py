"""知识库检索：AI 助手对话的 RAG 召回层。

混合召回 = 向量语义 + BM25 全文，RRF 融合排序。
"""
from app.llm.embedding import embed_texts
from app.services import vector_service
from app.services.bm25_service import get_bm25_service

MAX_DISTANCE = 0.42   # cosine 距离阈值：实测真相关 ≤0.39、无关 ≥0.57。
                      # 收到 0.42（留 0.03 边际）——0.42~0.45 的"勉强命中"多为弱相关，
                      # 塞给 LLM 会产出"材料不适用却硬引用"的回答，宁缺毋滥。
RRF_K = 60            # RRF 融合常数


def _rrf_fuse(v_items: list[dict], b_items: list[dict], top_k: int):
    """RRF 融合两路召回，按 ref_id 合并，返回 top_k。"""
    v_rank = {x["ref_id"]: i for i, x in enumerate(v_items)}
    b_rank = {x["ref_id"]: i for i, x in enumerate(b_items)}
    all_refs = set(v_rank) | set(b_rank)

    # BM25 分数附着到向量结果上；BM25-only 的结果补 distance=None
    b_by_ref = {x["ref_id"]: x for x in b_items}
    merged = {}
    for x in v_items:
        x["bm25_score"] = b_by_ref[x["ref_id"]].get("bm25_score", 0) if x["ref_id"] in b_by_ref else 0
        merged[x["ref_id"]] = x
    for ref, x in b_by_ref.items():
        if ref not in merged:
            x["distance"] = None
            merged[ref] = x

    def rrf(ref):
        s = 0.0
        if ref in v_rank:
            s += 1.0 / (RRF_K + v_rank[ref])
        if ref in b_rank:
            s += 1.0 / (RRF_K + b_rank[ref])
        return s

    return sorted(merged.values(), key=lambda x: -rrf(x["ref_id"]))[:top_k]


def retrieve(query: str, top_laws: int = 4, top_cases: int = 3) -> dict:
    """混合召回：向量语义 + BM25 全文检索，RRF 融合。"""
    qv = embed_texts([query])[0]
    bm25 = get_bm25_service()
    laws_col = vector_service.get_collection(vector_service.LAWS_COLLECTION)
    cases_col = vector_service.get_collection(vector_service.CASES_COLLECTION)

    # ———— 法条 ————
    v_laws = []
    if top_laws and laws_col.count():
        r = laws_col.query(query_embeddings=[qv], n_results=top_laws * 2)
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
            if dist > MAX_DISTANCE:
                continue
            v_laws.append({"ref_id": f"law_{meta['law_id']}", "source": meta["source"],
                           "article": meta["article"], "chapter": meta["chapter"],
                           "text": doc, "distance": round(dist, 3)})

    # BM25 只在向量路证明「查询与知识库语义相关」后参与召回。
    # 无关短问（"现在是什么时间""你会什么"）向量 0 命中，但 BM25 词面命中
    # 会硬凑满 top_k 垃圾引用（实测无关查询 BM25-only 分数 6~19，正例 19~43）。
    # ponytail: 纯词面匹配的查询（人名、案号）若向量 0 命中会全弃，FC 工具兜底。
    b_laws = bm25.search_laws(query, top_laws * 2) if v_laws else []
    laws = _rrf_fuse(v_laws, b_laws, top_laws)

    # ———— 案例 ————
    v_cases, seen = [], set()
    if top_cases and cases_col.count():
        r = cases_col.query(query_embeddings=[qv], n_results=top_cases * 3,
                            where={"chunk_type": "child"})
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
            if dist > MAX_DISTANCE or meta["case_ref_id"] in seen:
                continue
            seen.add(meta["case_ref_id"])
            parent = cases_col.get(ids=[meta["parent_id"]])
            summary = parent["documents"][0] if parent["documents"] else ""
            v_cases.append({"ref_id": f"case_{meta['case_ref_id']}", "title": meta["title"],
                            "summary": summary, "hit_text": doc, "distance": round(dist, 3)})
            if len(v_cases) >= top_cases * 2:
                break

    b_cases = bm25.search_cases(query, top_cases * 2) if v_cases else []
    cases = _rrf_fuse(v_cases, b_cases, top_cases)

    return {"laws": laws, "cases": cases}


def build_context(result: dict) -> tuple[str, list]:
    """检索结果 → (拼进 prompt 的参考材料文本, citations 引用卡片)。编号连续，回答用 [n] 标注。"""
    lines, citations = [], []
    n = 0
    if result["laws"]:
        lines.append("【参考法条】")
        for l in result["laws"]:
            n += 1
            lines.append(f"[{n}] {l['text']}")
            citations.append({"citation_type": "law", "ref_id": l["ref_id"],
                              "title": f"《{l['source']}》 {l['article']}".strip(), "snippet": l["text"][:120]})
    if result["cases"]:
        lines.append("【参考案例】")
        for c in result["cases"]:
            n += 1
            lines.append(f"[{n}] {c['summary']}\n相关段落：{c['hit_text'][:200]}")
            citations.append({"citation_type": "similar_case", "ref_id": c["ref_id"],
                              "title": c["title"], "snippet": c["summary"][:120]})
    return ("\n".join(lines), citations) if lines else ("", [])