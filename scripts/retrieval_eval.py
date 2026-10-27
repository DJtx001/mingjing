# -*- coding: utf-8 -*-
"""检索质量评测：量化「无条件召回(改前) → BM25 语义门控 → +意图门控(现役)」三代行为。

跑法（项目根）：
  .venv/Scripts/python.exe scripts/retrieval_eval.py

评测集：scripts/retrieval_queries.json（138 正例 + 62 负例 = 200 条）。
正例标注预期法条来源关键词 / 案例标题关键词；负例期望召回 0 条。

指标：
  误召回率  负例里召回 >0 条的占比（越低越好，目标 0）
  law hit@4  正例前 4 条法条里至少 1 条相关的占比（越高越好）
  case hit@3 正例前 3 条案例里至少 1 条相关的占比（越高越好）

内部复刻 production retrieve() 的召回逻辑，用 gate/intent 参数切换三代行为，
不复用 production 函数本体——目的是把「改前基线」作为历史快照钉死在评测里。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.llm.embedding import embed_texts
from app.services import vector_service
from app.services.bm25_service import get_bm25_service
from app.services.retrieval_service import (MAX_DISTANCE, _rrf_fuse,
                                            INTENT_CASE_PASS_MAX, INTENT_LAW_MIN)

TOP_LAWS, TOP_CASES = 4, 3


def _retrieve(query: str, gate: bool, intent: bool = False):
    """与 production retrieve() 同逻辑。

    gate=True=语义门控（BM25 仅在向量命中后参与）；False=改前（BM25 无条件）。
    intent=True=意图门控（案例侧命中≤1 且法条侧最近距离>0.35 → 整体拒绝）。
    """
    qv = embed_texts([query])[0]
    bm25 = get_bm25_service()
    laws_col = vector_service.get_collection(vector_service.LAWS_COLLECTION)
    cases_col = vector_service.get_collection(vector_service.CASES_COLLECTION)

    v_laws, law_min = [], None
    if TOP_LAWS and laws_col.count():
        r = laws_col.query(query_embeddings=[qv], n_results=TOP_LAWS * 2)
        law_min = min(r["distances"][0])
        for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0]):
            if dist > MAX_DISTANCE:
                continue
            v_laws.append({"ref_id": f"law_{meta['law_id']}", "source": meta["source"],
                           "article": meta["article"], "chapter": meta["chapter"],
                           "text": doc, "distance": round(dist, 3)})

    v_cases, seen, case_pass = [], set(), None
    if TOP_CASES and cases_col.count():
        r = cases_col.query(query_embeddings=[qv], n_results=TOP_CASES * 3,
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
            if len(v_cases) >= TOP_CASES * 2:
                break

    if intent and case_pass is not None and law_min is not None \
            and case_pass <= INTENT_CASE_PASS_MAX and law_min > INTENT_LAW_MIN:
        return [], []

    b_laws = bm25.search_laws(query, TOP_LAWS * 2) if (v_laws or not gate) else []
    laws = _rrf_fuse(v_laws, b_laws, TOP_LAWS)

    b_cases = bm25.search_cases(query, TOP_CASES * 2) if (v_cases or not gate) else []
    cases = _rrf_fuse(v_cases, b_cases, TOP_CASES)

    return laws, cases


def _law_ok(law, kws):
    return any(k in (law.get("source") or "") for k in kws)


def _case_ok(case, kws):
    return any(k in (case.get("title") or "") for k in kws)


def evaluate(queries, gate, intent=False):
    stats = {"neg_total": 0, "neg_misrecall": 0, "neg_recalled": 0,
             "law_total": 0, "law_hit": 0, "case_total": 0, "case_hit": 0}
    detail = []
    for it in queries:
        q, lkws, ckws = it["q"], it["laws"], it["cases"]
        laws, cases = _retrieve(q, gate, intent)
        is_neg = not lkws and not ckws
        law_related = sum(_law_ok(l, lkws) for l in laws) if lkws else None
        case_related = sum(_case_ok(c, ckws) for c in cases) if ckws else None

        if is_neg:
            stats["neg_total"] += 1
            n = len(laws) + len(cases)
            stats["neg_recalled"] += n
            if n > 0:
                stats["neg_misrecall"] += 1
            detail.append({"q": q, "neg": True, "laws": [l["source"] for l in laws],
                           "cases": [c["title"] for c in cases]})
            continue

        if lkws:
            stats["law_total"] += 1
            if law_related > 0:
                stats["law_hit"] += 1
        if ckws:
            stats["case_total"] += 1
            if case_related > 0:
                stats["case_hit"] += 1
        detail.append({"q": q, "neg": False,
                       "law_ok": law_related, "laws": [(l["source"], l["article"]) for l in laws],
                       "case_ok": case_related, "cases": [c["title"] for c in cases]})
    return stats, detail


def _fmt(pct: float) -> str:
    return f"{pct * 100:.0f}%"


def main():
    data = json.loads((ROOT / "scripts" / "retrieval_queries.json").read_text("utf-8"))
    queries = data["queries"]

    print("等待 BM25 索引加载……", flush=True)
    get_bm25_service().ensure_loaded()

    rows = []
    details = {}
    runs = [
        (False, False, "改前(无条件召回)"),
        (True, False, "语义门控(上一步)"),
        (True, True, "语义门控+意图门控(现役)"),
    ]
    for gate, intent, label in runs:
        stats, detail = evaluate(queries, gate, intent)
        details[(gate, intent)] = detail
        neg_mr = stats["neg_misrecall"] / max(stats["neg_total"], 1)
        law_hit = stats["law_hit"] / max(stats["law_total"], 1)
        case_hit = stats["case_hit"] / max(stats["case_total"], 1)
        rows.append((label, neg_mr, law_hit, case_hit, stats))

    print("\n" + "=" * 84)
    print(f"{'':<24}{'误召回率(负例)':<14}{'law hit@4':<12}{'case hit@3':<12}{'负例误召条数'}")
    print("=" * 84)
    for label, neg_mr, law_hit, case_hit, stats in rows:
        print(f"{label:<24}{_fmt(neg_mr):<14}{_fmt(law_hit):<12}{_fmt(case_hit):<12}"
              f"{stats['neg_recalled']}/{stats['neg_total']}")
    print("=" * 84)

    # —— 明细（语义门控，不含意图门控），供校对 gt 是否合理 ——
    detail = details[(True, False)]
    print("\n===== 语义门控·正例明细（law_ok / case_ok 为 -1 表示该侧未标注） =====")
    for d in detail:
        if d["neg"]:
            continue
        lok = d["law_ok"] if d["law_ok"] is not None else -1
        cok = d["case_ok"] if d["case_ok"] is not None else -1
        flag = ""
        if d["law_ok"] == 0 or d["case_ok"] == 0:
            flag = "  <-- 未命中，检查 gt 或检索"
        print(f"\n[{lok}/{cok}] {d['q']}{flag}")
        print(f"  法条: " + ((" / ".join(f"{s}-{a}" for s, a in d['laws'])) or "（无）"))
        print(f"  案例: " + ((" / ".join(d['cases'])) or "（无）"))

    print("\n===== 改前·负例误召回明细（意图门控的靶子） =====")
    for d in details[(False, False)]:
        if d["neg"] and (d["laws"] or d["cases"]):
            print(f"\n{d['q']}")
            print(f"  法条: " + ((" / ".join(d["laws"])) or "（无）"))
            print(f"  案例: " + ((" / ".join(d["cases"])) or "（无）"))

    print("\n===== 意图门控·残余负例（未被拦截，需语义级判断） =====")
    for d in details[(True, True)]:
        if d["neg"] and (d["laws"] or d["cases"]):
            print(f"\n{d['q']}")
            print(f"  法条: " + ((" / ".join(d["laws"])) or "（无）"))
            print(f"  案例: " + ((" / ".join(d["cases"])) or "（无）"))

    print("\n===== 意图门控·误拒正例（应为已知语义混淆项） =====")
    gate_row = {d["q"]: d for d in details[(True, False)]}
    n_killed = 0
    for d in details[(True, True)]:
        if d["neg"] or d["laws"] or d["cases"]:
            continue
        g = gate_row.get(d["q"], {})
        n_killed += 1
        print(f"  {d['q']}" + ("（语义门控下也无引用）" if not g.get("laws") and not g.get("cases") else ""))
    print(f"  共 {n_killed} 条（0 条=无代价）")


if __name__ == "__main__":
    main()