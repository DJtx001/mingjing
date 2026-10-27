"""Redis 连接封装。

和 db.py 的区别：
- MySQL 用连接池（短事务，归还前 rollback）；
- Redis 用连接池 + 单例，因为 Redis 命令都是短平快，复用连接性能更好。

故障快速失败：本机实测 Redis 不可达时默认重试累计约 26s，
期间会话读写会把首 token 拖到 10s+。这里 1s 超时 + 不重试，
异常直接落到 session_service 的降级分支。
"""
import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from app.core.config import config

_RETRY = Retry(NoBackoff(), 0)

# 连接池：模块加载时创建一次，所有 get_redis() 共享
# decode_responses 已在 config 里开，读出来直接是 str
_pool = redis.ConnectionPool(
    **config.REDIS,
    socket_connect_timeout=1,
    socket_timeout=1,
    retry=_RETRY,
)


def get_redis() -> redis.Redis:
    """获取 Redis 客户端（基于共享连接池）。

    每次调用返回的 Redis 对象底层从连接池取连接，用完自动归还，
    不需要手动 close。
    """
    return redis.Redis(connection_pool=_pool, retry=_RETRY)