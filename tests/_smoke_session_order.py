"""会话消息顺序回归（复现「先显示答案再显示问题」）。

场景：Redis 的 msgs List 丢失（Redis 重启 / 被清理）后，get_messages 走 MySQL 回填。
回填方向必须与 append_message 的 LPUSH 约定一致（**头=最新**），否则读取端的
messages.reverse() 会把「旧→新」反转成「新→旧」，前端就变成先显示答案再显示问题；
且 LTRIM(0,9) 在错误方向下保留的是「最旧 10 条」而不是「最新 10 条」。

用法：python tests/_smoke_session_order.py（需本地 Redis + MySQL）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.db import MySQLClient
from app.core.redis import get_redis
from app.services import session_service as ss


def seq(sid: str) -> list[str]:
    return [m["role"] for m in ss.get_messages(sid)]


def main():
    # assist_session.user_id 有外键，必须用库里真实用户
    db = MySQLClient()
    try:
        uid = db.execute("SELECT user_id FROM user ORDER BY user_id LIMIT 1")[0]["user_id"]
    finally:
        db.close()
    sid = ss.create_session(uid, None)
    try:
        for role, text in [("user", "问1"), ("assistant", "答1"),
                           ("user", "问2"), ("assistant", "答2")]:
            ss.append_message(sid, role, text)
        got = seq(sid)
        print("① 正常写入（LPUSH 路径）→", got)
        assert got == ["user", "assistant", "user", "assistant"], got

        # 模拟 Redis 丢消息 List（Redis 重启/清理后）
        get_redis().delete(ss._msgs_key(sid))
        got = seq(sid)
        print("② Redis 丢失 → MySQL 回填后 →", got)
        assert got == ["user", "assistant", "user", "assistant"], f"回填后顺序颠倒: {got}"

        # 回填后再追加，仍须与前文保持正序（回填方向与 LPUSH 一致才成立）
        ss.append_message(sid, "user", "问3")
        ss.append_message(sid, "assistant", "答3")
        got = seq(sid)
        print("③ 回填后继续追加 →", got)
        assert got == ["user", "assistant", "user", "assistant", "user", "assistant"], got

        # 超 10 条：保留的应是「最新 10 条」（早期内容被挤掉）
        for i in range(8):
            ss.append_message(sid, "user", f"x{i}")
            ss.append_message(sid, "assistant", f"y{i}")
        msgs = ss.get_messages(sid)
        contents = [m["content"] for m in msgs]
        print("④ 超 10 条 →", len(msgs), "条，含问1?", "问1" in contents)
        assert len(msgs) == 10, len(msgs)
        assert "问1" not in contents, "应保留最新 10 条，却残留了最旧消息"
        assert contents[-1] == "y7", contents[-1]
        print("全部 PASS")
    finally:
        ss.delete_session(sid)


if __name__ == "__main__":
    main()