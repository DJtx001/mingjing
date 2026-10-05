"""认证相关数据模型（DTO）：请求体校验 + 响应体结构。

Pydantic 会自动校验字段长度、枚举值，不合法直接返回 422，无需手写 if。
"""
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """登录请求体"""
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=64)


class UserInfo(BaseModel):
    """用户对象（登录响应和 /auth/me 共用），字段名严格对齐接口文档"""
    user_id: str
    username: str
    name: str
    # Literal 限定 role 只能是这三个值，与数据库 ENUM 一致
    role: Literal["intake_clerk", "reviewer", "admin"]
    org: str = ""


class LoginResponse(BaseModel):
    """登录成功响应体"""
    access_token: str
    token_type: str = "Bearer"      # 前端拼请求头：Authorization: Bearer <access_token>
    expires_in: int                 # 有效秒数（24h = 86400）
    user: UserInfo
