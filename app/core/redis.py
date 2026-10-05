"""Redis 连接封装。

和 db.py 的区别：
- MySQL 用短连接（每次 MySQLClient() 新建，用完 close），因为事务需要独立连接；
- Redis 用连接池 + 单例，因为 Redis 命令都是短平快，复用连接性能更好。

用法：
    from app.core.redis import get_redis
    r = get_redis()
    r.set("key", "value")
    r.get("key")
"""
import redis

from app.core.config import config

# 连接池：模块加载时创建一次，所有 get_redis() 共享
# decode_responses 已在 config 里开，读出来直接是 str
_pool = redis.ConnectionPool(**config.REDIS)


def get_redis() -> redis.Redis:
    """获取 Redis 客户端（基于共享连接池）。

    每次调用返回的 Redis 对象底层从连接池取连接，用完自动归还，
    不需要手动 close。
    """
    return redis.Redis(connection_pool=_pool)
