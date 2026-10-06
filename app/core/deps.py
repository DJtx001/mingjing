"""FastAPI 依赖：从请求头解析当前登录用户。

用法：在任意接口参数里写  user: dict = Depends(get_current_user)
FastAPI 会在接口执行前自动解析，失败直接返回 401，接口代码不会被调用。
"""
from fastapi import Depends, Header, HTTPException

from app.core.security import decode_access_token


def get_current_user(authorization: str = Header(default="")) -> dict:
    """要求请求头形如：Authorization: Bearer eyJhbGciOi…
    解析成功返回用户字典；缺头/格式错/过期/伪造一律 401。
    """
    # 没带头，或不是 Bearer 方案
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401,
                            detail={"code": "AUTH_001", "message": "未登录或登录已失效"})

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401,
                            detail={"code": "AUTH_001", "message": str(e)})

    # 整理成业务里统一的用户结构返回（JWT 载荷里 sub=user_id）
    return {
        "user_id": payload["sub"],
        "username": payload.get("username", ""),
        "name": payload.get("name", ""),
        "role": payload.get("role", ""),
        "org": payload.get("org", ""),
    }


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理员专用依赖：在登录校验之上再加角色校验。

    用法：接口参数写 user: dict = Depends(require_admin)。
    非 admin 角色一律 403，前端统一提示"你没有权限"。
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=403,
                            detail={"code": "AUTHZ_002", "message": "你没有权限，请联系管理员 3112028466@qq.com"})
    return user
