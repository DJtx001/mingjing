"""BM25 全文检索索引（内存），混合召回用。

首次查询时加载建索引。分词结果落盘缓存（data/bm25_cache.pkl），
重启后直接读缓存重建 BM25，避免每次启动重复 50s 的 MySQL 全量 + jieba 分词。
缓存按 (law 条数/最大id, case_ref 条数/最大id) 校验，数据变动自动重建。
"""
import logging
import pickle
import threading
from pathlib import Path

import jieba
from rank_bm25 import BM25Okapi

from app.core.db import get_conn

logger = logging.getLogger(__name__)

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "bm25_cache.pkl"
CACHE_VERSION = 1


class BM25Service:
    def __init__(self):
        self._laws_bm25: BM25Okapi | None = None
        self._cases_bm25: BM25Okapi | None = None
        self._law_data: list[dict] = []
        self._case_data: list[dict] = []
        self._ready_event = threading.Event()
        # 后台线程启动异步加载
        threading.Thread(target=self._load, daemon=True).start()

    def _tokenize(self, text: str) -> list[str]:
        return list(jieba.cut(text))

    @property
    def ready(self) -> bool:
        return self._ready_event.is_set()

    def _db_version(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM law")
            lc, lm = cur.fetchone()
            cur.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM case_ref")
            cc, cm = cur.fetchone()
        return (lc, lm, cc, cm)

    def _read_cache(self, ver):
        try:
            with open(CACHE_PATH, "rb") as f:
                data = pickle.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.warning("BM25 缓存读取失败，将重建: %s", e)
            return None
        if data.get("version") == CACHE_VERSION and data.get("db") == ver:
            return data
        logger.info("BM25 缓存版本不匹配，将重建")
        return None

    def _write_cache(self, ver, law_tokens, case_tokens):
        payload = {
            "version": CACHE_VERSION,
            "db": ver,
            "laws": self._law_data,
            "cases": self._case_data,
            "law_tokens": [" ".join(t) for t in law_tokens],
            "case_tokens": [" ".join(t) for t in case_tokens],
        }
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE_PATH.with_suffix(".tmp")
            tmp.write_bytes(pickle.dumps(payload, protocol=4))
            tmp.replace(CACHE_PATH)
        except Exception as e:
            logger.warning("BM25 缓存写入失败（不影响本次索引）: %s", e)

    @staticmethod
    def _split(joined: str) -> list[str]:
        return joined.split(" ") if joined else []

    def _load(self):
        """后台线程：优先读缓存，否则全量构建并落盘。失败只记 error，保持未就绪。"""
        try:
            conn = get_conn()
            try:
                ver = self._db_version(conn)
                cached = self._read_cache(ver)
                if cached:
                    self._law_data = cached["laws"]
                    self._case_data = cached["cases"]
                    self._laws_bm25 = BM25Okapi([self._split(t) for t in cached["law_tokens"]])
                    self._cases_bm25 = BM25Okapi([self._split(t) for t in cached["case_tokens"]])
                    self._ready_event.set()
                    logger.info("BM25 索引已从缓存加载 version=%s", ver)
                    return

                with conn.cursor() as cur:
                    cur.execute("SELECT id, source, chapter, article, text FROM law")
                    laws = cur.fetchall()
                    cur.execute("SELECT id, title, fact, process, result, comment FROM case_ref")
                    cases = cur.fetchall()
            finally:
                conn.close()

            # 法条
            self._law_data = []
            law_tok = []
            for row in laws:
                d = {"id": row[0], "source": row[1], "chapter": row[2] or "",
                     "article": row[3] or "", "text": row[4]}
                self._law_data.append(d)
                head = f"《{d['source']}》"
                if d["chapter"]:
                    head += d["chapter"] + " "
                if d["article"]:
                    head += d["article"] + "："
                law_tok.append(self._tokenize(head + d["text"]))

            # 案例：全文（标题+四段）一条一块
            self._case_data = []
            case_tok = []
            for row in cases:
                d = {k: row[i] or "" for i, k in
                     enumerate(("id", "title", "fact", "process", "result", "comment"))}
                self._case_data.append(d)
                parts = [d["title"], d["fact"], d["process"], d["result"], d["comment"]]
                case_tok.append(self._tokenize("\n".join(parts)))

            self._laws_bm25 = BM25Okapi(law_tok)
            self._cases_bm25 = BM25Okapi(case_tok)
            self._write_cache(ver, law_tok, case_tok)
            self._ready_event.set()
            logger.info("BM25 索引构建完成：law=%d case=%d", len(law_tok), len(case_tok))
        except Exception as e:
            logger.error("BM25 索引加载失败，检索将退化为纯向量: %s", e)

    def ensure_loaded(self):
        """等待 BM25 索引加载完成（首次调用会阻塞）。"""
        self._ready_event.wait()

    def search_laws(self, query: str, top_k: int = 10) -> list[dict]:
        """返回 [{ref_id, source, article, chapter, text, bm25_score}, …]"""
        if not self._ready_event.is_set():
            return []  # 未就绪：降级为空结果，交由纯向量召回
        self.ensure_loaded()
        tokens = self._tokenize(query)
        scores = self._laws_bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: -x[1])
        out = []
        for i, s in ranked:
            if s <= 0:
                continue
            d = self._law_data[i]
            out.append({"ref_id": f"law_{d['id']}", "source": d["source"],
                        "article": d["article"], "chapter": d["chapter"],
                        "text": f"《{d['source']}》{d['chapter']+' ' if d['chapter'] else ''}"
                                f"{d['article']+'：' if d['article'] else ''}{d['text']}",
                        "bm25_score": round(s, 3)})
            if len(out) >= top_k:
                break
        return out

    def search_cases(self, query: str, top_k: int = 10) -> list[dict]:
        """返回 [{ref_id, title, summary, hit_text, bm25_score}, …]"""
        if not self._ready_event.is_set():
            return []
        tokens = self._tokenize(query)
        scores = self._cases_bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: -x[1])
        out = []
        for i, s in ranked:
            if s <= 0:
                continue
            d = self._case_data[i]
            # summary 手拼（跟 reindex_service 父块格式一致）
            parts = [f"【案例】{d['title']}"]
            if d["fact"]:
                parts.append("案情：" + d["fact"][:120])
            tail, tag = (d["result"], "结果") if d["result"] else (d["comment"], "评析")
            if tail:
                parts.append(f"{tag}：" + tail[:100])
            hit = d["fact"] or d["process"] or d["result"] or d["comment"] or d["title"]
            out.append({"ref_id": f"case_{d['id']}", "title": d["title"],
                        "summary": "\n".join(parts), "hit_text": hit,
                        "bm25_score": round(s, 3)})
            if len(out) >= top_k:
                break
        return out


_SERVICE = None


def get_bm25_service() -> BM25Service:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = BM25Service()
    return _SERVICE


def reload_bm25():
    """写入新数据后调用以重载索引（后台异步加载）。"""
    global _SERVICE
    _SERVICE = BM25Service()