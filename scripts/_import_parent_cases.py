# -*- coding: utf-8 -*-
"""云端容器内导入父块刷新包（本地 _refresh_parent_cases.py 导出）。

纯 upsert 写入 Chroma，零 embedding 调用（云端计费铁律：勿在云端重嵌）。
导入后需 docker compose restart app（HNSW 内存索引重载）。

跑法（容器内）：python _import_parent_cases.py [_parent_refresh.npz]
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

from app.services import vector_service

path = sys.argv[1] if len(sys.argv) > 1 else "_parent_refresh.npz"
data = np.load(path, allow_pickle=False)
ids = [str(x) for x in data["ids"]]
docs = [str(x) for x in data["documents"]]
embs = np.asarray(data["embeddings"], dtype=np.float32).tolist()
metas = [json.loads(str(x)) for x in data["metadatas"]]
print(f"读取 {len(ids)} 条父块（{path}）")

col = vector_service.get_collection(vector_service.CASES_COLLECTION)
before = col.count()
col.upsert(ids=ids, documents=docs, embeddings=embs, metadatas=metas)
print(f"upsert 完成：{before} → {col.count()} 块")

one = col.get(ids=[ids[0]])
print(f"抽验 {ids[0]}：摘要 {len(one['documents'][0])} 字")