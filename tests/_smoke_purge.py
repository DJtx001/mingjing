# -*- coding: utf-8 -*-
"""知识库删除的 Chroma 级联清理冒烟（_purge_structured 按 metadata 过滤删除）。

插 2 行 law + 1 行 case（file_key=MARK）+ 对应假向量块 → 调 _purge_structured →
断言 MySQL 行删净、Chroma 块删净（含一个「id 不合旧公式」的块——旧实现按
主键公式拼 id 删，删不到它，正是幽灵块的产生机制；新实现按 metadata 过滤可删净）。
自清理 MySQL + Chroma，可重跑。

跑法（项目根）：.venv/Scripts/python.exe tests/_smoke_purge.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymysql

from app.api.kb import _purge_structured
from app.core.config import config
from app.services import vector_service

MARK = "__smoke_purge__"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def main() -> int:
    conn = pymysql.connect(**config.MYSQL, autocommit=True)
    law_col = vector_service.get_collection(vector_service.LAWS_COLLECTION)
    case_col = vector_service.get_collection(vector_service.CASES_COLLECTION)
    law_ids, case_ids = [], []
    # 假向量维度从现库取，不猜
    dim = len(law_col.peek(1)["embeddings"][0])

    # 前置清理：上次异常退出可能留下残留（撞 unique 键会误报）
    with conn.cursor() as cur:
        cur.execute("DELETE FROM law WHERE file_key=%s", (MARK,))
        cur.execute("DELETE FROM case_ref WHERE file_key=%s", (MARK,))

    try:
        with conn.cursor() as cur:
            for i in (1, 2):
                cur.execute(
                    "INSERT INTO law (source, article, text, vector_synced, file_key)"
                    " VALUES (%s, %s, %s, 1, %s)",
                    (f"{MARK}法{i}", f"第{i}条", "测试条文", MARK))
                law_ids.append(cur.lastrowid)
            cur.execute(
                "INSERT INTO case_ref (title, fact, result, vector_synced, file_key)"
                " VALUES (%s, %s, %s, 1, %s)",
                (f"{MARK}冒烟案例", "案情", "结果", MARK))
            case_ids.append(cur.lastrowid)
        check("插入测试行", len(law_ids) == 2 and len(case_ids) == 1)

        v = [0.0] * dim
        law_col.upsert(
            ids=[f"law_{i}" for i in law_ids],
            documents=["测试条文"] * 2,
            embeddings=[v, v],
            metadatas=[{"law_id": i, "source": f"{MARK}法{k + 1}", "chunk_type": "child"}
                       for k, i in enumerate(law_ids)],
        )
        # legacy 块：模拟历史 id 与主键公式不符的块（旧实现在此留幽灵）
        case_col.upsert(
            ids=[f"case_{case_ids[0]}_p", f"case_{case_ids[0]}_legacy"],
            documents=["案例摘要", "历史残留块"],
            embeddings=[v, v],
            metadatas=[{"chunk_type": "parent", "case_ref_id": case_ids[0], "title": "冒烟"},
                       {"chunk_type": "child", "case_ref_id": case_ids[0], "title": "冒烟"}],
        )
        check("写入 Chroma 块（含 legacy 不合公式块）",
              len(law_col.get(where={"law_id": {"$in": law_ids}})["ids"]) == 2
              and len(case_col.get(where={"case_ref_id": {"$in": case_ids}})["ids"]) == 2)

        purged = _purge_structured(MARK)
        check("_purge_structured 返回计数", purged == {"laws": 2, "cases": 1}, str(purged))

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM law WHERE file_key=%s", (MARK,))
            n_law = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM case_ref WHERE file_key=%s", (MARK,))
            n_case = cur.fetchone()[0]
        check("MySQL 行删净", n_law == 0 and n_case == 0, f"law={n_law} case={n_case}")

        left_law = law_col.get(where={"law_id": {"$in": law_ids}})["ids"]
        left_case = case_col.get(where={"case_ref_id": {"$in": case_ids}})["ids"]
        check("Chroma 块删净（含 legacy，按 metadata 过滤）", not left_law and not left_case,
              f"law残留={left_law} case残留={left_case}")
    finally:
        # 幂等兜底清理（无论成败）
        with conn.cursor() as cur:
            cur.execute("DELETE FROM law WHERE file_key=%s", (MARK,))
            cur.execute("DELETE FROM case_ref WHERE file_key=%s", (MARK,))
        if law_ids:
            law_col.delete(where={"law_id": {"$in": law_ids}})
        if case_ids:
            case_col.delete(where={"case_ref_id": {"$in": case_ids}})
        conn.close()

    print()
    if fails:
        print("FAIL:", "、".join(fails))
        return 1
    print("全部 PASS ✓（_purge_structured 已按 metadata 过滤删除，不再产幽灵块）")
    return 0


if __name__ == "__main__":
    sys.exit(main())