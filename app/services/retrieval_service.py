"""知识库检索：AI 助手对话的 RAG 召回层。

法条直取（document 自带《法名》章 条号前缀）；案例命中子块后上溯父块摘要。
"""
from app.llm.embedding import embed_texts
from app.services import vector_service

MAX_DISTANCE = 0.42   # cosine 距离阈值：实测真相关 ≤0.39、无关 ≥0.57。
                      # 收到 0.42（留 0.03 边际）——0.42~0.45 的"勉强命中"多为弱相关，
                      # 塞给 LLM 会产出"材料不适用却硬引用"的回答，宁缺毋滥。


def retrieve(query: str, top_laws: int = 4, top_cases: int = 3) -> dict:
    """混合召回：法条 top_laws 条 + 案例 top_cases 个（按 case_ref_id 去重）。"""
    qv = embed_texts([query])[0]
    laws_col = vector_service.get_collection(vector_service.LAWS_COLLECTION)
    cases_col = vector_service.get_collection(vector_service.CASES_COLLECTION)

    laws = []
    if top_laws and laws_col.count():   # top_laws=0：只要案例/只要法条的调用方跳过对应分支
        r = laws_col.query(query_embeddings=[qv], n_results=top_laws)
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
            if dist > MAX_DISTANCE:
                continue
            laws.append({"ref_id": f"law_{meta['law_id']}", "source": meta["source"],
                         "article": meta["article"], "chapter": meta["chapter"],
                         "text": doc, "distance": round(dist, 3)})

    cases, seen = [], set()
    if top_cases and cases_col.count():
        # 多取一倍再按案例去重：同一案例多个子块命中只留最近的一条
        r = cases_col.query(query_embeddings=[qv], n_results=top_cases * 2,
                            where={"chunk_type": "child"})
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
            if dist > MAX_DISTANCE or meta["case_ref_id"] in seen:
                continue
            seen.add(meta["case_ref_id"])
            parent = cases_col.get(ids=[meta["parent_id"]])
            summary = parent["documents"][0] if parent["documents"] else ""
            cases.append({"ref_id": f"case_{meta['case_ref_id']}", "title": meta["title"],
                          "summary": summary, "hit_text": doc, "distance": round(dist, 3)})
            if len(cases) >= top_cases:
                break
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
