# -*- coding: utf-8 -*-
"""清理 Chroma 案例幽灵块：MySQL 已删行、Chroma 仍留块 → 检索命中但 /citation 404。

ghost = Chroma 的 case_ref_id 集合 − MySQL 的 case_ref.id 集合。
纯删除、零重嵌（不调 embedding）。本地 / 云端（容器内）通用。

跑法：.venv/Scripts/python.exe scripts/_clean_ghost_cases.py [--apply]
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pymysql

from app.core.config import config
from app.services import vector_service

SECTIONS = ("fact", "process", "result", "comment")


def main() -> int:
    conn = pymysql.connect(**config.MYSQL)
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM case_ref")
        mysql_ids = {r[0] for r in cur.fetchall()}
    conn.close()

    col = vector_service.get_collection(vector_service.CASES_COLLECTION)
    metas = col.get(include=["metadatas"])["metadatas"]
    chroma_ids = {m["case_ref_id"] for m in metas if m.get("case_ref_id")}
    ghost = sorted(chroma_ids - mysql_ids)
    print(f"MySQL {len(mysql_ids)} 行；Chroma {len(chroma_ids)} 案例；幽灵 {len(ghost)} 个：{ghost}")
    if not ghost:
        print("无需清理 ✓")
        return 0
    ids = [f"case_{i}_p" for i in ghost] + \
          [f"case_{i}_{s}" for i in ghost for s in SECTIONS]
    exist = sorted(set(col.get(ids=ids)["ids"]))
    print(f"候选块 {len(ids)} 个，实际存在 {len(exist)} 个")
    if "--apply" not in sys.argv:
        print("dry-run：加 --apply 执行删除")
        return 0
    col.delete(ids=exist)
    print(f"已删除 {len(exist)} 块 ✓；删后案例块总数 {col.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())