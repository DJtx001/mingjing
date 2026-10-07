"""K组 操作日志接口（审计：登录 + 知识库操作留痕，仅管理员可见）"""
from fastapi import APIRouter, Depends, Query, Request

from app.core.db import MySQLClient
from app.core.deps import require_admin
from app.services import audit_service

router = APIRouter(prefix="/admin/logs", tags=["K-操作日志"])

# 建表 DDL：与《操作日志表设计.sql》保持一致（单一事实来源的代码侧副本）
_DDL = """
CREATE TABLE IF NOT EXISTS audit_log (
  id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '自增主键（查询按 id DESC，天然时序且高效）',
  user_id     VARCHAR(32)  NOT NULL COMMENT '操作者用户ID（user.user_id）',
  username    VARCHAR(64)  NOT NULL COMMENT '操作者账号（冗余快照，用户改名/删除后日志仍可读）',
  action      VARCHAR(32)  NOT NULL COMMENT '操作类型：login / kb_upload / kb_delete / rule_update / schema_save / prompt_save / kb_reindex / log_delete / log_clear',
  target      VARCHAR(255) DEFAULT NULL COMMENT '操作对象：文件名 / 规则ID / 纠纷类型 / 提示词key（登录为 NULL）',
  detail      JSON         DEFAULT NULL COMMENT '附加信息 JSON，如 {"enabled": false}、{"schema_version": 3}',
  ip          VARCHAR(45)  DEFAULT NULL COMMENT '来源 IP（45 长度兼容 IPv6）',
  created_at  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '操作时间（毫秒精度，与其他表一致）',
  KEY idx_action  (action),
  KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='操作审计日志（登录+知识库操作）'
"""

# 允许的 action 取值（查询过滤白名单，防拼 SQL 注入）
ACTIONS = ("login", "kb_upload", "kb_delete", "rule_update",
           "schema_save", "prompt_save", "kb_reindex", "log_delete", "log_clear")


def init_tables():
    """建 audit_log 表（幂等，启动时调用）。"""
    db = MySQLClient()
    try:
        db.execute(_DDL)
        db.commit()
    finally:
        db.close()


@router.get("")
def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str = Query(""),
    user=Depends(require_admin),
):
    """分页查询操作日志（按时间倒序）。仅管理员可见（require_admin 强校验）。"""
    where, args = "", []
    if action:
        # 白名单校验：只允许既定 action,杜绝任意值拼进 SQL 的隐患
        if action not in ACTIONS:
            return {"items": [], "total": 0}
        where = "WHERE action = %s"
        args.append(action)

    db = MySQLClient()
    try:
        total = db.execute(
            f"SELECT COUNT(*) AS n FROM audit_log {where}", tuple(args)
        )[0]["n"]
        rows = db.execute(
            f"SELECT id, user_id, username, action, target, detail, ip, created_at "
            f"FROM audit_log {where} ORDER BY id DESC LIMIT %s OFFSET %s",
            tuple(args) + (page_size, (page - 1) * page_size),
        )
        items = [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "username": r["username"],
                "action": r["action"],
                "target": r["target"],
                # pymysql 对 JSON 列返回字符串,这里原样给前端展示即可
                "detail": r["detail"],
                "ip": r["ip"],
                "created_at": str(r["created_at"]) if r["created_at"] else "",
            }
            for r in rows
        ]
        return {"items": items, "total": total}
    finally:
        db.close()


@router.delete("/{log_id}")
def delete_log(log_id: int, request: Request, user=Depends(require_admin)):
    """删除单条操作日志（仅管理员）。删除动作本身也记入审计，形成闭环。"""
    db = MySQLClient()
    try:
        db.execute("DELETE FROM audit_log WHERE id = %s", (log_id,))
        db.commit()
    finally:
        db.close()
    audit_service.record(user, "log_delete", target=str(log_id),
                         ip=request.client.host if request.client else "")
    return {"deleted": log_id}


@router.delete("")
def clear_logs(request: Request, user=Depends(require_admin)):
    """清空全部操作日志（仅管理员）。清空动作本身记一条审计，形成闭环。"""
    db = MySQLClient()
    try:
        n = db.execute("SELECT COUNT(*) AS n FROM audit_log")[0]["n"]
        db.execute("DELETE FROM audit_log")
        db.commit()
    finally:
        db.close()
    # 清空后立即补一条：日志表清空后仅剩这条「清空」痕迹
    audit_service.record(user, "log_clear", target="all", detail={"cleared": n},
                         ip=request.client.host if request.client else "")
    return {"cleared": n}
