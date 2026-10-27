# -*- coding: utf-8 -*-
"""案例路坏条标记冒烟（新问题.md 2026-10-18 灌库 bug 修复的验证）。

mock 向量化让含「毒条」的块失败（返回 None），驱动真实 _run_cases()，
断言：毒块所在行 vector_synced=2（不完整·不再重试）、同批其余行=1、
state["skipped"] 按行计 1；Chroma 里毒块未写入、父块/正常块已写入。

前置：本地库 case_ref 无 vector_synced=0 行（当前 4826 全为 1）——只有
本脚本插入的 3 行临时案例会被处理，向量化被 mock，零 token、零残留。

跑法：.venv/Scripts/python.exe scripts/_smoke_reindex_bad.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymysql

from app.core.config import config
from app.services import reindex_service, vector_service

MARK = "__smoke_reindex__"
SECTIONS = ("fact", "process", "result", "comment")


def _chunk_ids(cid: int) -> list:
    return [f"case_{cid}_p"] + [f"case_{cid}_{s}" for s in SECTIONS]


def main() -> int:
    conn = pymysql.connect(**config.MYSQL, autocommit=True)
    col = vector_service.get_collection(vector_service.CASES_COLLECTION)
    try:
        with conn.cursor() as cur:
            # 前置：库里不应有其它待灌行（否则 _run_cases 会连它们一起处理）
            # 排除本脚本自己的残留（下面会清理），只挡真实数据
            cur.execute("SELECT COUNT(*) FROM case_ref WHERE vector_synced=0 AND title NOT LIKE %s",
                        (MARK + "%",))
            pending = cur.fetchone()[0]
            if pending:
                print(f"FAIL: 库中已有 {pending} 行待灌，先处理后再跑本冒烟")
                return 1
            # 幂等重跑：清上次残留（MySQL + Chroma）
            cur.execute("SELECT id FROM case_ref WHERE title LIKE %s", (MARK + "%",))
            old = [r[0] for r in cur.fetchall()]
            if old:
                cur.execute("DELETE FROM case_ref WHERE title LIKE %s", (MARK + "%",))
                col.delete(ids=[i for cid in old for i in _chunk_ids(cid)])

            # 插 3 行：A/C 全正常；B 的 fact 正常（父块正常）仅 comment 段为毒条
            cur.executemany(
                "INSERT INTO case_ref (title, source, fact, process, result, comment, vector_synced)"
                " VALUES (%s,'smoke',%s,NULL,%s,%s,0)",
                [(f"{MARK}A", "正常案情A", "正常结果A", None),
                 (f"{MARK}B", "正常案情B", "正常结果B", "毒条评析B"),
                 (f"{MARK}C", "正常案情C", "正常结果C", None)])
            cur.execute("SELECT title, id FROM case_ref WHERE title LIKE %s", (MARK + "%",))
            row = dict(cur.fetchall())

        # mock 向量化：含「毒条」的块置 None+坏下标，其余给假向量（不烧 token）
        dim = len(col.peek(1)["embeddings"][0])

        def fake_embed(docs):
            vecs, bad = [], []
            for i, d in enumerate(docs):
                if "毒条" in d:
                    vecs.append(None)
                    bad.append(i)
                else:
                    vecs.append([0.0] * dim)
            return vecs, bad

        reindex_service._embed_batch = fake_embed
        reindex_service.state["skipped"] = 0
        reindex_service._run_cases()

        # 断言
        fails = []
        a, b, c = row[f"{MARK}A"], row[f"{MARK}B"], row[f"{MARK}C"]
        with conn.cursor() as cur:
            cur.execute("SELECT id, vector_synced FROM case_ref WHERE title LIKE %s", (MARK + "%",))
            synced = dict(cur.fetchall())
        if synced.get(a) != 1:
            fails.append(f"A vector_synced={synced.get(a)} 应=1")
        if synced.get(b) != 2:
            fails.append(f"B(毒条行) vector_synced={synced.get(b)} 应=2（坏块不再重试）")
        if synced.get(c) != 1:
            fails.append(f"C vector_synced={synced.get(c)} 应=1")
        if reindex_service.state["skipped"] != 1:
            fails.append(f"state['skipped']={reindex_service.state['skipped']} 应=1（按行计）")
        got = col.get(ids=_chunk_ids(b))["ids"]
        if f"case_{b}_comment" in got:
            fails.append("B 的 comment 毒块不应写入 Chroma")
        if f"case_{b}_p" not in got:
            fails.append("B 的父块（正常）应写入 Chroma")
        if not col.get(ids=[f"case_{a}_p"])["ids"]:
            fails.append("A 的父块应写入 Chroma")

        # 清理（MySQL + Chroma）
        with conn.cursor() as cur:
            cur.execute("DELETE FROM case_ref WHERE title LIKE %s", (MARK + "%",))
        col.delete(ids=[i for cid in (a, b, c) for i in _chunk_ids(cid)])

        if fails:
            print("FAIL:")
            for f in fails:
                print("  -", f)
            return 1
        print("PASS: 毒条行=2、正常行=1、skipped=1、Chroma 毒块未写入/正常块已写入")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())