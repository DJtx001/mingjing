"""向量模型封装：阿里云 DashScope text-embedding-v3（openai 兼容模式）。

所有 embedding 调用的唯一出口，后续换模型/加降级只改这里。
"""
import time

from openai import OpenAI

from app.core.config import config

# text-embedding-v3 单请求最多 10 条文本，超出需分批（DashScope 限制）
BATCH_SIZE = 10
# 单条文本 token 上限 8192；中文约 1 字 1 token。超长文本（如按"一、二、"编号的
# 整文件"修改决定"，可达 3 万字）直接调 API 会 400 拒绝，截断保护（丢尾部）
MAX_CHARS = 8000

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.EMBEDDING_API_KEY, base_url=config.EMBEDDING_BASE_URL)
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """批量向量化。自动按 BATCH_SIZE 分批，遇限速/网络错误退避重试 3 次。

    # ponytail: 无主动限速，靠重试兜底；灌库触发 429 频繁时再加速率控制
    """
    if not texts:
        return []
    client = _get_client()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = [t[:MAX_CHARS] for t in texts[i : i + BATCH_SIZE]]
        for attempt in range(3):
            try:
                resp = client.embeddings.create(model=config.EMBEDDING_MODEL, input=batch)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)  # 1s → 2s 退避
        vectors.extend(d.embedding for d in resp.data)
    return vectors
