"""从 OSS 全量补入库到 MySQL（一次性修复脚本）。

背景：历史批量导入时后端为旧进程（未重启，不解析），1528 个文件只落在 OSS
未写 MySQL。本脚本按 OSS 现状 key 逐个下载解析补入库；向量库随后由前端
「重建索引」按钮灌入（本脚本顺带清空 Chroma 里主键已失效的孤儿块）。
跳过 _index.md / README.md / 模板等非内容文件。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from app.api.kb import _import_law
from app.core.config import config
from app.services.oss_service import download_file, list_files
from app.services import vector_service

SKIP_NAMES = ("_index.md", "README.md", "法律法规模版.md")


def main():
    if os.environ.get("CONFIRM_PURGE") != "1":
        print("危险操作：本脚本会清空 law / case_ref 及两个 Chroma Collection。")
        print("确认后设置 CONFIRM_PURGE=1 再运行。")
        sys.exit(2)

    files = [f for f in list_files("laws/")
             if f["key"].lower().endswith(".md") and Path(f["key"]).name not in SKIP_NAMES]
    print(f"待处理 {len(files)} 个文件", flush=True)

    # 清掉此前测试导的旧数据（file_key 无双重 laws 前缀的那批）与旧案例
    conn = pymysql.connect(**config.MYSQL)
    with conn.cursor() as cur:
        cur.execute("DELETE FROM law WHERE file_key NOT LIKE 'laws/laws/%%'")
        print(f"清理历史测试 law: {cur.rowcount} 行", flush=True)
        cur.execute("DELETE FROM case_ref")
        print(f"清理历史测试 case_ref: {cur.rowcount} 行", flush=True)
    conn.commit()
    conn.close()

    # 清空 Chroma：旧块 id 绑定已删除的 MySQL 主键，留着重灌会产生孤儿块
    client = vector_service.get_client()
    for name in (vector_service.LAWS_COLLECTION, vector_service.CASES_COLLECTION):
        try:
            client.delete_collection(name)
            print(f"已清空 Chroma Collection: {name}", flush=True)
        except Exception:
            pass

    total, n_empty, fails = 0, 0, []
    for i, f in enumerate(files, 1):
        try:
            n = _import_law(download_file(f["key"]).decode("utf-8"), f["key"])
            total += n
            if n == 0:
                n_empty += 1
        except Exception as e:
            fails.append((f["key"], str(e)[:80]))
        if i % 200 == 0:
            print(f"  …{i}/{len(files)}，累计 {total} 条", flush=True)

    print(f"完成：{len(files)} 个文件 → {total} 条法条；解析为空 {n_empty} 个；失败 {len(fails)} 个", flush=True)
    for k, e in fails[:10]:
        print("  失败:", k, e)


if __name__ == "__main__":
    main()
