"""认证接口：login + /me（单 token 方案，无 refresh/logout）

流程：POST /auth/login 校验账号密码 → 签发 JWT 返回；
      GET /auth/me 凭请求头里的 JWT 返回当前用户。
"""
from fastapi import APIRouter, Depends, HTTPException, Request

import pymysql

from app.core.config import config
from app.core.db import MySQLClient, get_conn
from app.core.deps import get_current_user
from app.core.security import verify_password, create_access_token
from app.schemas.auth import LoginRequest, LoginResponse, UserInfo
from app.services import audit_service

router = APIRouter(prefix="/auth", tags=["A-认证"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    """账号密码登录。成功返回 JWT，前端存 localStorage。"""
    # 1. 查用户（按账号）。建库后把这里换成查 user 表的 SQL：
    #    SELECT user_id, username, password_hash, name, role, org, status
    #    FROM user WHERE username = %s AND status = 'active'
    user = _query_user_by_username(body.username)

    # 2. 验密码 + 用户是否启用。账号不存在和密码错误用同一句提示，
    #    防止攻击者靠提示差异判断账号是否真实存在。
    if not user or not verify_password(body.password, user["password_hash"]) \
            or user["status"] != "active":
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_001", "message": "账号或密码错误"},
        )

    # 3. 生成 JWT
    access = create_access_token(user)

    # 4. 记录登录审计（audit_service 内部降级：写失败不影响登录）
    audit_service.record(user, "login", ip=request.client.host if request.client else "")

    return LoginResponse(
        access_token=access,
        expires_in=config.ACCESS_EXPIRE_HOURS * 3600,
        user=UserInfo(
            user_id=user["user_id"],
            username=user["username"],
            name=user["name"],
            role=user["role"],
            org=user.get("org", ""),
        ),
    )


@router.get("/me", response_model=UserInfo)
async def me(user: dict = Depends(get_current_user)):
    """当前登录用户信息。前端刷新页面后靠它恢复登录态和角色。"""
    return UserInfo(**user)


def _query_user_by_username(username: str) -> dict | None:
    """按账号查 user 表，返回用户行（含 password_hash），查不到返回 None。

    只查启用账号（status='active'）；参数用 %s 占位，避免 SQL 注入。
    """
    db = MySQLClient()
    try:
        rows = db.execute(
            "SELECT user_id, username, password_hash, name, role, org, status "
            "FROM user WHERE username = %s AND status = 'active'",
            (username,),
        )
        return rows[0] if rows else None
    finally:
        db.close()


# ---------- 用户表（幂等建表 + 空库种子账号） ----------
_DDL_USER = """
CREATE TABLE IF NOT EXISTS user (
  user_id VARCHAR(16) PRIMARY KEY COMMENT '用户ID，如 u_001',
  username VARCHAR(32) NOT NULL UNIQUE COMMENT '登录账号',
  password_hash VARCHAR(128) NOT NULL COMMENT 'bcrypt 哈希',
  name VARCHAR(32) NOT NULL COMMENT '姓名',
  role ENUM('intake_clerk','reviewer','admin') NOT NULL COMMENT '角色',
  org VARCHAR(64) DEFAULT NULL COMMENT '所属机构',
  status ENUM('active','disabled') DEFAULT 'active' COMMENT '账号状态',
  created_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)
) COMMENT='系统用户'
"""

# 演示种子账号（仅空表时写入；密码统一 123456，生产必改）
_USER_SEED = [
    ("u_001", "zhangming", "张明", "intake_clerk"),
    ("u_002", "admin", "系统管理员", "admin"),
    ("u_003", "lisi", "李四", "intake_clerk"),
    ("u_004", "wangwu", "王五", "reviewer"),
    ("u_005", "zhaoliu", "赵六", "intake_clerk"),
    ("u_006", "sunqi", "孙七", "intake_clerk"),
]


def init_tables():
    """幂等建 user 表；表为空时写入 6 个演示账号。

    必须在 assist.init_tables() 之前调用——assist 表有外键引用 user。
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(_DDL_USER)
            cur.execute("SELECT COUNT(*) FROM user")
            if cur.fetchone()[0] == 0:
                from app.core.security import hash_password
                pwd = hash_password("123456")
                cur.executemany(
                    "INSERT INTO user (user_id, username, password_hash, name, role)"
                    " VALUES (%s,%s,%s,%s,%s)",
                    [(uid, uname, pwd, name, role) for uid, uname, name, role in _USER_SEED],
                )
        conn.commit()
    finally:
        conn.close()

