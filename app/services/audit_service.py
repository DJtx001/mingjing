"""操作审计日志服务：全系统统一的日志写入入口。

设计约定：
- 只记「成功」的操作（登录成功、写操作提交成功后才调用）；
- 写失败只记 warning，绝不阻断业务主流程（与 session_service 的降级哲学一致）。
"""
import json
import logging

from app.core.db import MySQLClient

logger = logging.getLogger(__name__)


def record(user: dict, action: str, target: str | None = None,
           detail: dict | None = None, ip: str = "") -> None:
    """写一条审计日志。

    :param user: 操作者（含 user_id / username，取自登录态或 DB 用户行）
    :param action: 操作类型，取值见《操作日志表设计.sql》：
                   login / kb_upload / kb_delete / rule_update / schema_save / prompt_save / kb_reindex
    :param target: 操作对象（文件名 / 规则ID / 纠纷类型 / 提示词key；登录传 None）
    :param detail: 附加信息（如 {"enabled": false}），可空
    :param ip: 来源 IP，可空
    """
    try:
        db = MySQLClient()
        try:
            db.execute(
                "INSERT INTO audit_log (user_id, username, action, target, detail, ip) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    user.get("user_id", ""),
                    user.get("username", ""),
                    action,
                    target,
                    json.dumps(detail, ensure_ascii=False) if detail else None,
                    ip or None,
                ),
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        # 审计写失败不能影响业务：只记日志
        logger.warning("审计日志写入失败 action=%s target=%s: %s", action, target, e)
