# -*- coding: utf-8 -*-
"""清理 Redis 会话消息缓存（assist:sess:*:msgs）中「顺序被固化颠倒」的脏数据。

背景：旧 get_messages 回填路径用 RPUSH（头=最旧），读取端却按「头=最新」反转，
凡走过该路径的会话顺序被固化颠倒——前端打开会话会「先显示答案再显示问题」。
根因已于 2026-10-19 修复（回填改逐条 LPUSH）；但已污染的缓存不会自愈，需清掉让它
按新逻辑重新回填。真相源在 MySQL（近 10 条），清理零数据损失。

判别：Redis 读路径的结果 ≠ MySQL 读路径的结果 → 污染。只删污染项，健康缓存不动。

跑法：
  本地：python scripts/_purge_session_msgs_cache.py [--purge]
  容器：docker compose cp 进 app 容器 + docker compose exec app python _purge_session_msgs_cache.py [--purge]
"""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent
sys.path.insert(0, str(_root if (_root / "app").is_dir() else _root.parent))

from app.core.redis import get_redis
from app.services import session_service as ss


def main() -> int:
    purge = "--purge" in sys.argv
    r = get_redis()
    keys = sorted(r.scan_iter("assist:sess:*:msgs"))
    bad = []
    for k in keys:
        sid = k.split(":")[2]
        try:
            redis_way = [(m["role"], m["content"]) for m in ss.get_messages(sid)]
            db_way = [(m["role"], m["content"]) for m in ss._query_messages_from_db(sid)]
        except Exception as e:
            print(f"  ? {sid} 检查失败：{e}")
            continue
        if redis_way != db_way:
            bad.append(k)
            print(f"  ✗ {sid} 顺序与真相源不一致（污染）")
    print(f"扫描 {len(keys)} 个 msgs List，污染 {len(bad)} 个")
    if purge and bad:
        r.delete(*bad)
        print(f"已清除 {len(bad)} 个污染 List（下次读取按新逻辑重新回填）")
    elif purge:
        print("无需清理")
    else:
        print("（dry-run，未修改；加 --purge 实删）")
    return 0


if __name__ == "__main__":
    sys.exit(main())