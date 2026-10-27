"""一次性修复：law.category 从 file_key 重推。

背景：早期批量导入（补入库脚本时期）的 file_key 是双重前缀（laws/laws/行政法规/x.md），
_meta_category 取 parts[1] 得到无意义的 "laws"。本脚本从 file_key 重推正确部门并全量更新。
新增数据已走 _normalize_rel 归一化，key 正确，无需处理。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from app.core.config import config


def cat_from_key(key: str) -> str | None:
    """laws/laws/行政法规/x.md → 行政法规；laws/刑法.md → None（无部门目录）"""
    segs = [p for p in key.split("/")[:-1] if p]  # 去掉文件名，保留目录段
    while segs and segs[0] in ("laws", "cases"):
        segs.pop(0)
    return segs[0] if segs else None


def main():
    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT id, file_key FROM law WHERE file_key IS NOT NULL")
            rows = cur.fetchall()
            updates = []
            for r in rows:
                cat = cat_from_key(r["file_key"])
                if cat:
                    updates.append((cat, r["id"]))
            cur.executemany("UPDATE law SET category=%s WHERE id=%s", updates)
            cur.execute("SELECT category, COUNT(*) AS n FROM law GROUP BY category ORDER BY n DESC")
            print("修复后部门分布:")
            for r in cur.fetchall():
                print(f"  {r['n']:6d}  {r['category']}")
        conn.commit()
        print(f"已更新 {len(updates)} 行")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
