"""reindex 后台任务：vector_synced=0 → embedding → Chroma upsert → 置 vector_synced=1。

幂等：块 ID 由 MySQL 主键推导（law_{id} / case_{id}_p / case_{id}_{段}），
重跑同数据覆盖不重复；中断后重跑自动从 vector_synced=0 处续，无需任务队列。
"""
import threading

import pymysql

from app.core.config import config
from app.llm.embedding import embed_texts
from app.services import vector_service

# 单进程内单任务（uvicorn 单 worker 假设）；多 worker 部署时换任务队列
state = {"task_id": None, "status": "idle", "total": 0, "processed": 0, "skipped": 0, "error": None}
BATCH = 64  # 每批行数；embedding 内部再按 10 条/请求分批

_SECTIONS = ("fact", "process", "result", "comment")
_SECTION_NAMES = {"fact": "基本案情", "process": "诉讼请求", "result": "裁判结果", "comment": "案例分析"}


def _conn():
    return pymysql.connect(**config.MYSQL)


def start(task_id: str) -> None:
    # 同步置 running：避免 POST 返回后、线程尚未启动时前端轮询读到旧的 error 状态
    state.update(task_id=task_id, status="running", processed=0, skipped=0, error=None)
    threading.Thread(target=_run, args=(task_id,), daemon=True).start()


def _run(task_id: str) -> None:
    try:
        state["total"] = _pending_count()
        _run_laws()
        _run_cases()
        state["status"] = "done"
    except Exception as e:
        state["status"] = "error"
        state["error"] = str(e)


def _embed_batch(docs: list[str]) -> tuple[list, list[int]]:
    """批向量化容错：整批失败时逐条重试，仍失败的条目返回坏下标。

    防"毒条炸全任务"：单条文本无法向量化时只跳过它（置 vector_synced=2），
    不影响其余条目的灌入。
    """
    try:
        return embed_texts(docs), []
    except Exception:
        vectors, bad = [], []
        for i, d in enumerate(docs):
            try:
                vectors.append(embed_texts([d])[0])
            except Exception as e:
                vectors.append(None)
                bad.append(i)
                print(f"[reindex] 跳过无法向量化的条目: {str(e)[:120]}", flush=True)
        return vectors, bad


def _pending_count() -> int:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM law WHERE vector_synced=0")
            n = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM case_ref WHERE vector_synced=0")
            return n + cur.fetchone()[0]
    finally:
        conn.close()


def _run_laws() -> None:
    """法条：每条一个块。document 带法名/章/条号前缀，命中后可直接作引用。"""
    conn = _conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            while True:
                cur.execute(
                    "SELECT id, source, chapter, article, text, category"
                    " FROM law WHERE vector_synced=0 ORDER BY id LIMIT %s", (BATCH,))
                rows = cur.fetchall()
                if not rows:
                    break
                ids, docs, metas, row_ids = [], [], [], []
                for r in rows:
                    head = f"《{r['source']}》"
                    if r["chapter"]:
                        head += r["chapter"] + " "
                    if r["article"]:
                        head += r["article"] + "："
                    ids.append(f"law_{r['id']}")
                    row_ids.append(r["id"])
                    docs.append(head + r["text"])
                    # Chroma metadata 不收 None，统一转空串
                    metas.append({"law_id": r["id"], "source": r["source"],
                                  "chapter": r["chapter"] or "", "article": r["article"] or "",
                                  "category": r["category"] or "", "chunk_type": "child"})
                vectors, bad = _embed_batch(docs)
                ok = [i for i, v in enumerate(vectors) if v is not None]
                if ok:
                    col = vector_service.get_collection(vector_service.LAWS_COLLECTION)
                    col.upsert(ids=[ids[i] for i in ok], documents=[docs[i] for i in ok],
                               embeddings=[vectors[i] for i in ok], metadatas=[metas[i] for i in ok])
                with conn.cursor() as cur2:
                    if ok:
                        cur2.executemany("UPDATE law SET vector_synced=1 WHERE id=%s",
                                         [(row_ids[i],) for i in ok])
                    if bad:  # 2=无法向量化，跳过不再重试（防每次重跑卡同一处）
                        cur2.executemany("UPDATE law SET vector_synced=2 WHERE id=%s",
                                         [(row_ids[i],) for i in bad])
                        state["skipped"] += len(bad)
                conn.commit()
                state["processed"] += len(rows)
    finally:
        conn.close()


def _case_parent_text(r: dict) -> str:
    """案例父块摘要（约 350 字）：标题 + 案情[:120] + 结果/评析[:200]。

    与 scripts/_refresh_parent_cases.py 共用同一拼装逻辑（改这里即可全量刷新）。
    """
    summary = [f"【案例】{r['title']}"]
    if r["fact"]:
        summary.append("案情：" + r["fact"][:120])
    tail, tag = (r["result"], "结果") if r["result"] else (r["comment"], "评析")
    if tail:
        summary.append(f"{tag}：" + tail[:200])
    return "\n".join(summary)


def _run_cases() -> None:
    """案例：1 父块（程序拼接摘要，~350 字）+ 非空段子块，parent_id 关联。"""
    conn = _conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            while True:
                cur.execute(
                    "SELECT id, title, fact, process, result, comment"
                    " FROM case_ref WHERE vector_synced=0 ORDER BY id LIMIT %s", (BATCH,))
                rows = cur.fetchall()
                if not rows:
                    break
                ids, docs, metas = [], [], []
                row_of = []   # 块下标 → 行 id（子块失败要回溯到所属行标状态）
                for r in rows:
                    pid = f"case_{r['id']}_p"
                    ids.append(pid)
                    docs.append(_case_parent_text(r))
                    metas.append({"chunk_type": "parent", "case_ref_id": r["id"], "title": r["title"]})
                    row_of.append(r["id"])
                    for sec in _SECTIONS:
                        body = r[sec]
                        if not body:
                            continue   # 缺段不入库
                        ids.append(f"case_{r['id']}_{sec}")
                        docs.append(f"【{r['title']}·{_SECTION_NAMES[sec]}】{body}")
                        metas.append({"chunk_type": "child", "parent_id": pid,
                                      "case_ref_id": r["id"], "title": r["title"], "section": sec})
                        row_of.append(r["id"])
                vectors, bad = _embed_batch(docs)
                ok = [i for i, v in enumerate(vectors) if v is not None]
                # 块下标 → 行 id：一行任一子块失败即整行标 2（案例不完整、不再重试），
                # 否则重跑会永远卡在同一毒块上（与 _run_laws 同语义）
                bad_rows = {row_of[i] for i in bad}
                ok_rows = {row_of[i] for i in ok} - bad_rows
                if ok:
                    col = vector_service.get_collection(vector_service.CASES_COLLECTION)
                    col.upsert(ids=[ids[i] for i in ok], documents=[docs[i] for i in ok],
                               embeddings=[vectors[i] for i in ok], metadatas=[metas[i] for i in ok])
                with conn.cursor() as cur2:
                    if ok_rows:
                        cur2.executemany("UPDATE case_ref SET vector_synced=1 WHERE id=%s",
                                         [(i,) for i in ok_rows])
                    if bad_rows:  # 2=无法向量化，跳过不再重试（防每次重跑卡同一处）
                        cur2.executemany("UPDATE case_ref SET vector_synced=2 WHERE id=%s",
                                         [(i,) for i in bad_rows])
                        state["skipped"] += len(bad_rows)
                conn.commit()
                state["processed"] += len(rows)
    finally:
        conn.close()
