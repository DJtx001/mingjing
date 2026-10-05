"""安全工具：密码哈希 + JWT 生成解析（全系统唯一出口，别处不许自己拼 token）

安全红线：
1. 密码绝不存明文、绝不明文比对，统一走 bcrypt（单向、自带盐、计算慢）；
2. JWT 任何人都能解开看内容，载荷里【不能放密码等敏感信息】。
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import config


# ================= 密码哈希（bcrypt） =================

def hash_password(plain: str) -> str:
    """明文 → bcrypt 哈希字符串，用于入库。cost=12，每次盐随机，结果不可预测。"""
    salt = bcrypt.gensalt(rounds=12)
    # bcrypt 库只认 bytes，哈希完再解码成 str 方便存 VARCHAR
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    """校验明文与哈希是否匹配。盐藏在 password_hash 里，checkpw 会自己取。"""
    return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))


# ================= JWT =================

def create_access_token(user: dict) -> str:
    """为用户签发 access token（默认 24 小时）。

    载荷里只放"身份信息"，绝对不放密码。
    :param user: 至少含 user_id / username / name / role
    """
    now = datetime.now(timezone.utc)               # 统一带时区 UTC，避免本机时区歧义
    payload = {
        "sub": user["user_id"],                    # subject：token 归属主体，约定放用户 ID
        "username": user.get("username", ""),
        "name": user["name"],
        "role": user["role"],
        "org": user.get("org", ""),
        "iat": now,                                 # 签发时间
        "exp": now + timedelta(hours=config.ACCESS_EXPIRE_HOURS),  # 过期时间
    }
    # 用密钥签名后得到 头.载荷.签名 三段字符串
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解析并验签 token，成功返回载荷；过期/伪造抛 ValueError（上层转成 401）。"""
    try:
        # decode 会自动校验签名和 exp（过期时间）
        return jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("登录已过期，请重新登录")
    except jwt.PyJWTError:
        # 签名错误、伪造、格式损坏等一切其他情况
        raise ValueError("无效的登录凭证")
