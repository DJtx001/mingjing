"""会话记忆服务（Redis 热缓存 + MySQL 真相源）。

两层 Key 设计（Redis）：
  1. 用户维度：assist:user:{user_id}:sessions  → Sorted Set  TTL 30d
     存该用户的所有 session_id，score=最后活跃时间戳（毫秒）
  2. 会话维度：
     assist:sess:{session_id}       → Hash  TTL 7d   存 user_id, case_id, updated_at
     assist:sess:{session_id}:msgs  → List  TTL 7d   存近 10 轮消息（每条一个 JSON 字符串）

写入策略：先写 Redis（热路径，微秒级），再写 MySQL（真相源）。
MySQL 写失败只记日志不抛异常——不阻塞用户，数据靠后续补偿。
"""
import json
import logging
import time

from app.core.db import MySQLClient
from app.core.id_gen import gen_session_id
from app.core.redis import get_redis

logger = logging.getLogger(__name__)

# TTL 常量（秒）
_SESSION_TTL = 7 * 24 * 3600       # 会话 7 天
_USER_INDEX_TTL = 30 * 24 * 3600   # 用户会话索引 30 天
_MAX_MESSAGES = 10                  # 近 10 轮上下文


def _now_ms() -> int:
    """当前时间戳（毫秒），用作 Sorted Set 的 score。"""
    return int(time.time() * 1000)


def _now_str() -> str:
    """当前时间字符串，存到消息 created_at 字段。"""
    return time.strftime("%Y-%m-%dT%H:%M:%S+08:00")


# ================= MySQL 辅助查询（降级 + 回调用）=================

def _query_session_from_db(session_id: str) -> dict | None:
    """从 MySQL 查会话元数据，用于 Redis 未命中或异常时的降级/回放。"""
    db = MySQLClient()
    try:
        rows = db.execute(
            "SELECT session_id, user_id, case_id, updated_at FROM assist_session WHERE session_id = %s",
            (session_id,),
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "user_id": row["user_id"],
            "case_id": row["case_id"],
            "updated_at": str(row["updated_at"]) if row["updated_at"] else "",
        }
    finally:
        db.close()


def _query_messages_from_db(session_id: str) -> list[dict]:
    """从 MySQL 查近 10 轮消息（旧→新），用于 Redis 未命中或异常时的降级/回放。"""
    db = MySQLClient()
    try:
        rows = db.execute(
            "SELECT role, content, reply_id, citations, created_at FROM assist_message "
            "WHERE session_id = %s ORDER BY id DESC LIMIT %s",
            (session_id, _MAX_MESSAGES),
        )
        messages = []
        for row in rows:
            msg = {
                "role": row["role"],
                "content": row["content"],
                "created_at": str(row["created_at"]) if row["created_at"] else "",
            }
            if row["reply_id"]:
                msg["reply_id"] = row["reply_id"]
            citations = row.get("citations")
            if citations is not None:
                # pymysql 对 JSON 列返回字符串，需还原为对象再给前端
                msg["citations"] = json.loads(citations) if isinstance(citations, str) else citations
            messages.append(msg)
        # MySQL 按 id DESC 取的（最新在前），反转成旧→新
        messages.reverse()
        return messages
    finally:
        db.close()


def _query_user_sessions_from_db(user_id: str) -> list[dict]:
    """从 MySQL 查用户的所有会话，用于 Redis 异常时的降级。"""
    db = MySQLClient()
    try:
        rows = db.execute(
            "SELECT session_id, case_id, updated_at FROM assist_session "
            "WHERE user_id = %s ORDER BY updated_at DESC",
            (user_id,),
        )
        return [
            {
                "session_id": r["session_id"],
                "case_id": r["case_id"],
                "updated_at": str(r["updated_at"]) if r["updated_at"] else "",
            }
            for r in rows
        ]
    finally:
        db.close()


# ================= 第一层：用户维度 =================

def _user_index_key(user_id: str) -> str:
    return f"assist:user:{user_id}:sessions"


def _touch_user_index(user_id: str, session_id: str) -> None:
    """更新用户会话索引：ZADD（已存在则更新 score，不存在则添加）+ 续期。"""
    r = get_redis()
    r.zadd(_user_index_key(user_id), {session_id: _now_ms()})
    r.expire(_user_index_key(user_id), _USER_INDEX_TTL)


def list_user_sessions(user_id: str) -> list[dict]:
    """列出某用户的所有会话（按最后活跃时间倒序）。

    优先查 Redis；Redis 异常时降级查 MySQL。
    返回：[{"session_id": ..., "case_id": ..., "updated_at": ...}, ...]
    """
    try:
        r = get_redis()
        raw = r.zrevrange(_user_index_key(user_id), 0, -1, withscores=True)
        sessions = []
        for sid, score in raw:
            meta = get_session(sid)
            if meta:
                sessions.append({
                    "session_id": sid,
                    "case_id": meta.get("case_id"),
                    "updated_at": meta.get("updated_at"),
                })
        return sessions
    except Exception as e:
        # 降级：Redis 挂了直连 MySQL
        logger.warning("Redis 不可用，降级查 MySQL 会话列表 user_id=%s: %s", user_id, e)
        return _query_user_sessions_from_db(user_id)


# ================= 第二层：会话维度 =================

def _sess_key(session_id: str) -> str:
    return f"assist:sess:{session_id}"


def _msgs_key(session_id: str) -> str:
    return f"assist:sess:{session_id}:msgs"


def create_session(user_id: str, case_id: str | None = None) -> str:
    """创建新会话，返回 session_id。

    双写：
      1. Redis：assist:sess:{sid} Hash + assist:user:{uid}:sessions ZADD
      2. MySQL：INSERT assist_session（真相源）
    MySQL 失败不阻塞，只记日志。
    """
    session_id = gen_session_id()
    r = get_redis()
    now = _now_str()
    # 1. 写 Redis（热路径）
    r.hset(_sess_key(session_id), mapping={
        "user_id": user_id,
        "case_id": case_id or "",
        "updated_at": now,
    })
    r.expire(_sess_key(session_id), _SESSION_TTL)
    _touch_user_index(user_id, session_id)

    # 2. 写 MySQL（真相源），失败只记日志
    try:
        db = MySQLClient()
        try:
            db.execute(
                "INSERT INTO assist_session (session_id, user_id, case_id) VALUES (%s, %s, %s)",
                (session_id, user_id, case_id),
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.error("MySQL 写入 assist_session 失败 session_id=%s: %s", session_id, e)

    return session_id


def get_session(session_id: str) -> dict | None:
    """获取会话元数据 {user_id, case_id, updated_at}，不存在返回 None。

    读路径：
      1. 查 Redis → 命中直接返回
      2. Redis 没命中 → 查 MySQL（回放）→ 查到就回填 Redis
      3. Redis 异常 → 直接查 MySQL（降级）
    """
    # 1. 查 Redis
    try:
        r = get_redis()
        data = r.hgetall(_sess_key(session_id))
        if data:
            return {
                "user_id": data.get("user_id", ""),
                "case_id": data.get("case_id") or None,
                "updated_at": data.get("updated_at", ""),
            }
    except Exception as e:
        # 降级：Redis 挂了，直连 MySQL
        logger.warning("Redis 不可用，降级查 MySQL 会话 session_id=%s: %s", session_id, e)
        return _query_session_from_db(session_id)

    # 2. Redis 没命中 → 查 MySQL 并回填
    meta = _query_session_from_db(session_id)
    if meta:
        try:
            r = get_redis()
            r.hset(_sess_key(session_id), mapping={
                "user_id": meta["user_id"],
                "case_id": meta["case_id"] or "",
                "updated_at": meta["updated_at"],
            })
            r.expire(_sess_key(session_id), _SESSION_TTL)
        except Exception as e:
            logger.warning("回放 Redis 会话失败 session_id=%s: %s", session_id, e)
    return meta


def check_owner(session_id: str, user_id: str) -> bool:
    """校验会话归属：该 session 是否属于该 user。用于防越权。"""
    meta = get_session(session_id)
    return meta is not None and meta["user_id"] == user_id


def append_message(session_id: str, role: str, content: str,
                   reply_id: str | None = None, citations: list | None = None,
                   context: dict | None = None) -> None:
    """追加一条消息到会话。

    双写：
      1. Redis：LPUSH 到 List 头部 + LTRIM 只留近 10 轮
      2. MySQL：INSERT assist_message（真相源，永久保存）

    :param role: user / assistant
    :param content: 消息文本
    :param reply_id: 仅 assistant 消息有，采纳回流时定位用
    :param citations: 仅 assistant 消息有，引用卡片列表
    :param context: 仅 assistant 消息有，运行元数据 {model, provider, latency_ms, no_evidence}（统计源）
    """
    msg = {
        "role": role,
        "content": content,
        "created_at": _now_str(),
    }
    if reply_id:
        msg["reply_id"] = reply_id
    if citations is not None:
        msg["citations"] = citations

    r = get_redis()
    # 1. 写 Redis（热路径）
    r.lpush(_msgs_key(session_id), json.dumps(msg, ensure_ascii=False))
    r.ltrim(_msgs_key(session_id), 0, _MAX_MESSAGES - 1)
    r.expire(_msgs_key(session_id), _SESSION_TTL)
    r.expire(_sess_key(session_id), _SESSION_TTL)
    r.hset(_sess_key(session_id), "updated_at", _now_str())
    meta = get_session(session_id)
    if meta:
        _touch_user_index(meta["user_id"], session_id)

    # 2. 写 MySQL（真相源），失败只记日志
    try:
        db = MySQLClient()
        try:
            db.execute(
                "INSERT INTO assist_message (session_id, role, content, reply_id, citations, context) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (session_id, role, content, reply_id,
                 json.dumps(citations or [], ensure_ascii=False),
                 json.dumps(context, ensure_ascii=False) if context else None),
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.error("MySQL 写入 assist_message 失败 session_id=%s: %s", session_id, e)


def get_messages(session_id: str) -> list[dict]:
    """获取近 10 轮消息（按时间正序：最旧在前，最新在后）。

    读路径：
      1. 查 Redis List → 命中返回
      2. Redis 没命中 → 查 MySQL 近 10 轮（回放）→ 回填 Redis
      3. Redis 异常 → 直接查 MySQL（降级）
    """
    # 1. 查 Redis
    try:
        r = get_redis()
        raw = r.lrange(_msgs_key(session_id), 0, -1)
        if raw:
            messages = [json.loads(s) for s in raw]
            messages.reverse()   # List 头部是最新，反转成旧→新
            return messages
    except Exception as e:
        # 降级：Redis 挂了，直连 MySQL
        logger.warning("Redis 不可用，降级查 MySQL 消息 session_id=%s: %s", session_id, e)
        return _query_messages_from_db(session_id)

    # 2. Redis 没命中 → 查 MySQL 并回填
    messages = _query_messages_from_db(session_id)
    if messages:
        try:
            r = get_redis()
            # MySQL 返回的是旧→新，RPUSH 保持顺序（最新在尾部）
            for m in messages:
                r.rpush(_msgs_key(session_id), json.dumps(m, ensure_ascii=False))
            r.ltrim(_msgs_key(session_id), 0, _MAX_MESSAGES - 1)
            r.expire(_msgs_key(session_id), _SESSION_TTL)
        except Exception as e:
            logger.warning("回放 Redis 消息失败 session_id=%s: %s", session_id, e)
    return messages


def delete_session(session_id: str) -> None:
    """删除会话（三层清干净，不留僵尸）。

    1. Redis：会话 hash + 消息列表 + 用户索引条目（ZREM）
       —— 索引必须显式删除：只靠 30 天 TTL 会在列表里积压"点了没反应的僵尸项"
    2. MySQL：删 assist_session + assist_message（外键 CASCADE 自动删消息）
    """
    # 先取 user_id（清索引要定位到人的索引键）；hash 已丢则从 MySQL 拿
    user_id = None
    try:
        meta = get_session(session_id)
        if meta:
            user_id = meta.get("user_id")
    except Exception:
        pass

    r = get_redis()
    r.delete(_sess_key(session_id))
    r.delete(_msgs_key(session_id))
    if user_id:
        r.zrem(_user_index_key(user_id), session_id)

    try:
        db = MySQLClient()
        try:
            # assist_message 有外键 ON DELETE CASCADE，删 session 会自动删消息
            db.execute("DELETE FROM assist_session WHERE session_id = %s", (session_id,))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.error("MySQL 删除 assist_session 失败 session_id=%s: %s", session_id, e)
