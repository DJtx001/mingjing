"""统一清理所有对话数据（一次性重置，用户要求）。

背景：历史阶段存在 Redis 索引僵尸、MySQL 空壳会话、未入库对话等，
Redis 与 MySQL 数据不一致。本脚本全量清空后从干净状态重新开始。

清理范围：
  Redis:  assist:* 全部键（用户索引 / 会话 hash / 消息列表）
  MySQL:  assist_message / assist_session / assist_adoption
保留（非对话数据）：
  case_note（案件备注=案件资料，采纳内容仍可见）
  audit_log（审计）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from app.core.config import config
from app.core.redis import get_redis


def main():
    r = get_redis()
    keys = list(r.scan_iter("assist:*", count=1000))
    if keys:
        r.delete(*keys)
    print(f"Redis 清理 assist:* 键：{len(keys)} 个")

    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor() as cur:
            for t in ("assist_message", "assist_session", "assist_adoption"):
                cur.execute(f"DELETE FROM {t}")
                print(f"MySQL 清理 {t}：{cur.rowcount} 行")
            cur.execute("SELECT COUNT(*) FROM case_note")
            print(f"保留 case_note（案件备注）：{cur.fetchone()[0]} 行")
        conn.commit()
    finally:
        conn.close()

    # 验证干净
    left = list(r.scan_iter("assist:*", count=100))
    print(f"验证：Redis 残留 assist 键 {len(left)} 个")


if __name__ == "__main__":
    main()
