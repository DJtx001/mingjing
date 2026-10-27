# -*- coding: utf-8 -*-
"""刷新案例父块：按最新 _case_parent_text 逻辑重嵌全部父块（子块不动）。

父块文本改动（如 result 截断 100→200）不会自动生效——vector_synced=1 的行
不会被 reindex 重扫；本脚本重嵌父块并 upsert 覆盖。父块不参与向量检索
（检索按 chunk_type=child 过滤），刷新只影响命中后回读的摘要文本，检索排序不变。

产出：
1. 本地 Chroma 直接 upsert 刷新；
2. scripts/_parent_refresh.npz 导出包——云端用 _import_parent_cases.py 差分导入
   （纯写入零 embedding 调用，不违反云端计费铁律）。

跑法（项目根）：.venv/Scripts/python.exe scripts/_refresh_parent_cases.py
"""
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pymysql

from app.core.config import config
from app.services import vector_service
from app.services.reindex_service import _case_parent_text, _embed_batch

EXPORT = ROOT / "scripts" / "_parent_refresh.npz"
CHUNK = 500   # 大块循环只为进度可见；embed_texts 内部再按 10 条/请求分批


def main() -> int:
    conn = pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT id, title, fact, process, result, comment FROM case_ref ORDER BY id")
        rows = cur.fetchall()
    conn.close()
    print(f"案例 {len(rows)} 条，开始重嵌父块（chunk={CHUNK}）…")

    col = vector_service.get_collection(vector_service.CASES_COLLECTION)
    ok_ids, ok_docs, ok_vecs, ok_metas, bad_ids = [], [], [], [], []
    t0 = time.time()
    for s in range(0, len(rows), CHUNK):
        chunk = rows[s:s + CHUNK]
        texts = [_case_parent_text(r) for r in chunk]
        vecs, _ = _embed_batch(texts)
        for r, d, v in zip(chunk, texts, vecs):
            if v is None:
                bad_ids.append(r["id"])   # 坏条保留旧父块，不覆盖
                continue
            ok_ids.append(f"case_{r['id']}_p")
            ok_docs.append(d)
            ok_vecs.append(v)
            ok_metas.append({"chunk_type": "parent", "case_ref_id": r["id"], "title": r["title"]})
        print(f"  {min(s + CHUNK, len(rows))}/{len(rows)} 完成，坏条累计 {len(bad_ids)}")

    if ok_ids:
        col.upsert(ids=ok_ids, documents=ok_docs, embeddings=ok_vecs, metadatas=ok_metas)
    print(f"本地 Chroma 已刷新 {len(ok_ids)} 个父块；坏条 {len(bad_ids)}（保留旧父块）")
    if bad_ids:
        print(f"  坏条案例 id：{bad_ids[:10]}{'…' if len(bad_ids) > 10 else ''}")

    np.savez_compressed(
        EXPORT,
        ids=np.array(ok_ids),
        documents=np.array(ok_docs),
        embeddings=np.array(ok_vecs, dtype=np.float32),
        metadatas=np.array([json.dumps(m, ensure_ascii=False) for m in ok_metas]),
    )
    print(f"已导出 {EXPORT.name}（{EXPORT.stat().st_size / 1e6:.1f} MB），总耗时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())