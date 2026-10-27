"""一次性清理：删除旧版遗留表 kb_law/kb_case（已被 law/case_ref 取代，0 行数据）
及 law.status、case_ref.dispute_focus 两个超前字段。跑一次即可。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from app.core.config import config

conn = pymysql.connect(**config.MYSQL)
try:
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS kb_law, kb_case")
    cur.execute("ALTER TABLE law DROP COLUMN status")
    cur.execute("ALTER TABLE case_ref DROP COLUMN dispute_focus")
    conn.commit()
    cur.execute("SHOW TABLES")
    print("剩余表:", [r[0] for r in cur.fetchall()])
    cur.execute("SHOW COLUMNS FROM law")
    print("law 字段:", [r[0] for r in cur.fetchall()])
    cur.execute("SHOW COLUMNS FROM case_ref")
    print("case_ref 字段:", [r[0] for r in cur.fetchall()])
finally:
    conn.close()
