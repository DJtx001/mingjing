"""ID 生成工具。

一期用 UUID（全局唯一、零依赖）；二期分布式部署时可换雪花算法。
session_id 格式：sess_ + 12位十六进制，共 17 字符，符合 assist_session.session_id VARCHAR(20)。
"""
import uuid


def gen_session_id() -> str:
    """生成会话 ID：sess_a1b2c3d4e5f6

    uuid4().hex 是 32 位十六进制随机串，取前 12 位足够唯一
    （2^48 种可能，碰撞概率可忽略）。
    """
    return "sess_" + uuid.uuid4().hex[:12]
