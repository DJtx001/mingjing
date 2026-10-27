"""知识库检索：AI 助手对话的 RAG 召回层。

混合召回 = 向量语义 + BM25 全文，RRF 融合排序。
意图门控：案例侧无实质命中且法条侧距离超阈 → 判非领域查询，整体拒绝（不产出引用）。
"""
import functools

from app.llm.embedding import embed_texts
from app.services import vector_service
from app.services.bm25_service import get_bm25_service


@functools.lru_cache(maxsize=500)
def _embed_query_cached(query: str) -> tuple:
    """查询向量进程内缓存：同一问题重复提问省一次 embedding API 往返（约 0.5s）。

    只缓存查询向量，不缓存最终材料——检索结果仍每次实时计算。
    返回 tuple 以便 lru_cache 缓存；调用方用 list() 转回。
    """
    return tuple(embed_texts([query])[0])

MAX_DISTANCE = 0.42   # cosine 距离阈值：实测真相关 ≤0.39、无关 ≥0.57。
                      # 收到 0.42（留 0.03 边际）——0.42~0.45 的"勉强命中"多为弱相关，
                      # 塞给 LLM 会产出"材料不适用却硬引用"的回答，宁缺毋滥。
RRF_K = 60            # RRF 融合常数

# ———— 意图门控（2026-10 新增）————
# 半专业沾边查询（"股票怎么买""该不该辞职"）不在知识库可回答范围内，
# 但向量/BM25 都有弱命中。200 条人工标注集标定：案例侧无实质命中
# + 法条侧最近距离 >0.35 → 整体拒绝。实测拦截 50/62 负例、误拒 1/138
# 正例（"善意取得"与"辞职"特征完全重合：law_min 同为 0.355，调阈值无解）。
# 仅当法条/案例两侧通道都启用时判定——单侧检索的调用方（文书生成等）不适用。
INTENT_CASE_PASS_MAX = 1   # 案例侧 ≤MAX_DISTANCE 的条数 ≤ 此值 = 无实质命中
INTENT_LAW_MIN = 0.35      # 法条侧最近距离阈值（含阈值外候选，非 v_laws）


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
    """混合召回：向量语义 + BM25 全文检索，RRF 融合。

    返回 {"laws", "cases", "intent_rejected"}；被意图门控拒绝时两列表为空。
    """
    qv = list(_embed_query_cached(query))
    bm25 = get_bm25_service()
    laws_col = vector_service.get_collection(vector_service.LAWS_COLLECTION)
    cases_col = vector_service.get_collection(vector_service.CASES_COLLECTION)

    # ———— 法条：向量候选（law_min 记录含阈值外的最近距离，意图门控用） ————
    v_laws, law_min = [], None
    if top_laws and vector_service.count_cached(vector_service.LAWS_COLLECTION):
        r = laws_col.query(query_embeddings=[qv], n_results=top_laws * 2)
        law_min = min(r["distances"][0])
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
            if dist > MAX_DISTANCE:
                continue
            v_laws.append({"ref_id": f"law_{meta['law_id']}", "source": meta["source"],
                           "article": meta["article"], "chapter": meta["chapter"],
                           "text": doc, "distance": round(dist, 3)})

    # ———— 案例：向量候选（case_pass 按阈值内命中数原始计数，去重前） ————
    v_cases, seen, case_pass = [], set(), None
    if top_cases and vector_service.count_cached(vector_service.CASES_COLLECTION):
        r = cases_col.query(query_embeddings=[qv], n_results=top_cases * 3,
                            where={"chunk_type": "child"})
        case_pass = sum(1 for d in r["distances"][0] if d <= MAX_DISTANCE)
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

    # ———— 意图门控：两侧通道都有证据才判定，判非领域则整体拒绝 ————
    if (law_min is not None and case_pass is not None
            and case_pass <= INTENT_CASE_PASS_MAX and law_min > INTENT_LAW_MIN):
        return {"laws": [], "cases": [], "intent_rejected": True}

    # BM25 只在向量路证明「查询与知识库语义相关」后参与召回。
    # 无关短问（"现在是什么时间""你会什么"）向量 0 命中，但 BM25 词面命中
    # 会硬凑满 top_k 垃圾引用（实测无关查询 BM25-only 分数 6~19，正例 19~43）。
    # ponytail: 纯词面匹配的查询（人名、案号）若向量 0 命中会全弃，FC 工具兜底。
    b_laws = bm25.search_laws(query, top_laws * 2) if v_laws else []
    laws = _rrf_fuse(v_laws, b_laws, top_laws)

    b_cases = bm25.search_cases(query, top_cases * 2) if v_cases else []
    cases = _rrf_fuse(v_cases, b_cases, top_cases)

    return {"laws": laws, "cases": cases, "intent_rejected": False}


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