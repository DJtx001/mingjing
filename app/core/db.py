"""MySQL 连接封装（进程内连接池）。

为什么池化：每次 pymysql.connect 在本机约 31ms（skip_name_resolve=OFF 时更久），
而 SQL 本身只有 0.2~0.9ms。复用连接能把接口与会话写入的 DB 段压到 1ms 级。

对外接口不变：MySQLClient() / execute() / commit() / close()。
- 取出时 ping(reconnect=True)，坏连接自动重建；
- 归还前 rollback()，未提交事务与旧行为（close 即回滚）一致；
- 池满时多余连接直接关闭，不阻塞调用方。
"""
import queue

import pymysql
from pymysql.cursors import DictCursor

from app.core.config import config

POOL_SIZE = 20
_POOL: "queue.LifoQueue" = queue.LifoQueue(maxsize=POOL_SIZE)


def _new_conn():
    return pymysql.connect(**config.MYSQL)


def _acquire():
    try:
        conn = _POOL.get_nowait()
    except queue.Empty:
        return _new_conn()
    try:
        conn.ping(reconnect=False)
        return conn
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return _new_conn()


def _release(conn):
    try:
        conn.rollback()
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return
    try:
        _POOL.put_nowait(conn)
    except queue.Full:
        try:
            conn.close()
        except Exception:
            pass


class MySQLClient:
    def __init__(self):
        self.connection = _acquire()
        self.cursor = self.connection.cursor(DictCursor)

    def close(self):
        try:
            self.cursor.close()
        except Exception:
            pass
        _release(self.connection)

    def execute(self, sql, params=None):
        self.cursor.execute(sql, params or ())
        return self.cursor.fetchall()

    def commit(self):
        self.connection.commit()


class PooledConnection:
    """池化裸连接的包装：保持 conn.cursor()/commit()/close() 的原有用法。

    默认返回元组游标；需要字典游标时传 cursorclass，避免改变既有调用的取值方式。
    """

    def __init__(self, cursorclass=None):
        self._conn = _acquire()
        self._cursorclass = cursorclass

    def cursor(self, *args, **kwargs):
        if args or kwargs:
            return self._conn.cursor(*args, **kwargs)
        if self._cursorclass is not None:
            return self._conn.cursor(self._cursorclass)
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        _release(self._conn)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_conn(cursorclass=None) -> PooledConnection:
    """从进程内连接池取一条连接，用完必须 close() 归还。"""
    return PooledConnection(cursorclass)


def reset_pool():
    """清空连接池。切换 config.MYSQL 数据库（测试）前调用，否则会取到旧库连接。"""
    while True:
        try:
            conn = _POOL.get_nowait()
        except queue.Empty:
            break
        try:
            conn.close()
        except Exception:
            pass