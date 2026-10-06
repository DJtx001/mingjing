"""认证接口：login + /me（单 token 方案，无 refresh/logout）

流程：POST /auth/login 校验账号密码 → 签发 JWT 返回；
      GET /auth/me 凭请求头里的 JWT 返回当前用户。
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.config import config
from app.core.db import MySQLClient
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

