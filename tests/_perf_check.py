"""性能优化回归断言。用法：.venv/Scripts/python.exe tests/_perf_check.py [关键字]"""
import pathlib
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000"


def test_pool_reuse():
    """连续两次 MySQLClient 应复用同一底层连接。"""
    from app.core import db
    c1 = db.MySQLClient()
    id1 = id(c1.connection)
    c1.close()
    c2 = db.MySQLClient()
    id2 = id(c2.connection)
    c2.close()
    assert id1 == id2, f"未复用：{id1} != {id2}"


def test_count_cache_exists():
    from app.services import vector_service
    assert hasattr(vector_service, "count_cached"), "缺少 count_cached"


def test_embed_query_cache():
    """同一 query 第二次不应再调 embedding API。"""
    from app.services import retrieval_service as rs
    calls = []
    orig = rs.embed_texts

    def fake(texts):
        calls.append(list(texts))
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    rs.embed_texts = fake
    try:
        rs._embed_query_cached("_perf_check_唯一查询_A")
        rs._embed_query_cached("_perf_check_唯一查询_A")
    finally:
        rs.embed_texts = orig
    assert len(calls) == 1, f"embedding 被调用 {len(calls)} 次"


def test_stats_kb_cached():
    """连续两次 /stats/kb，第二次应命中缓存。"""
    import requests
    from app.core.security import create_access_token

    tok = create_access_token({"user_id": "u_002", "username": "admin",
                               "name": "系统管理员", "role": "admin"})
    h = {"Authorization": f"Bearer {tok}"}
    t = []
    for _ in range(5):
        s = time.perf_counter()
        r = requests.get(f"{BASE}/stats/kb", headers=h, timeout=30)
        t.append((time.perf_counter() - s) * 1000)
        assert r.status_code == 200, r.status_code
    # 缓存未命中时每次约 60ms；命中时 1~4ms。用最小值判定，避免依赖“第一次一定冷”
    assert min(t) < 25, f"没有命中缓存的迹象：{[round(x,1) for x in t]}"


def test_bm25_cache_fast_load():
    """BM25 分词缓存存在，且加载耗时应远低于全量重建（约 60s）。"""
    from app.services import bm25_service as b
    if not b.CACHE_PATH.exists():
        print("SKIP: BM25 缓存未生成（首次运行需先触发一次 BM25Service 建索引）")
        return
    t0 = time.time()
    svc = b.BM25Service()
    svc.ensure_loaded()
    dt = time.time() - t0
    assert svc.ready, "BM25 未就绪"
    assert dt < 10, f"缓存加载 {dt:.1f}s"


TESTS = [
    test_pool_reuse,
    test_count_cache_exists,
    test_embed_query_cache,
    test_stats_kb_cached,
    test_bm25_cache_fast_load,
]


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    failed = 0
    for t in TESTS:
        if only and only not in t.__name__:
            continue
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    sys.exit(1 if failed else 0)