"""Chroma 向量库服务：laws_v1（法条）+ case_refs_v1（案例）双 Collection。

Chroma 是可重建的派生数据（真相源在 MySQL），损坏时删目录重跑 reindex 即可。
"""
from chromadb import PersistentClient

from app.core.config import config

# Collection 命名带版本：分块策略/模型变更时新建 _v2 灌完再切，不原地改
LAWS_COLLECTION = "laws_v1"
CASES_COLLECTION = "case_refs_v1"

# 用注释式注解：PersistentClient 是工厂函数而非类，`X | None` 在 3.12 立即求值会 TypeError
# （本机 3.14 有 PEP 649 延迟求值所以不报，容器 3.12 会炸）
_client = None  # type: PersistentClient | None


def get_client() -> PersistentClient:
    """惰性单例：首次调用才建目录和连接，不阻塞应用启动。"""
    global _client
    if _client is None:
        _client = PersistentClient(path=config.CHROMA_PATH)
    return _client


def get_collection(name: str):
    """取 Collection（不存在则创建）。cosine 适合中文语义相似度。"""
    return get_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )
