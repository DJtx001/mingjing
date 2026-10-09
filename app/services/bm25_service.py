"""BM25 全文检索索引（内存），混合召回用。

首次查询时从 MySQL 全量加载建索引。写入新数据后重启 app 即可重载。
"""
import threading
import jieba
import pymysql
from rank_bm25 import BM25Okapi

from app.core.config import config


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

    def _load(self):
        """在后台线程中全量加载建索引。"""
        conn = pymysql.connect(**config.MYSQL)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, source, chapter, article, text FROM law")
                laws = cur.fetchall()
                cur.execute("SELECT id, title, fact, process, result, comment FROM case_ref")
                cases = cur.fetchall()
        finally:
            conn.close()

        # 法条
        self._law_data = []
        tok = []
        for row in laws:
            d = {"id": row[0], "source": row[1], "chapter": row[2] or "",
                 "article": row[3] or "", "text": row[4]}
            self._law_data.append(d)
            head = f"《{d['source']}》"
            if d["chapter"]:
                head += d["chapter"] + " "
            if d["article"]:
                head += d["article"] + "："
            tok.append(self._tokenize(head + d["text"]))
        self._laws_bm25 = BM25Okapi(tok)

        # 案例：全文（标题+四段）一条一块
        self._case_data = []
        tok = []
        for row in cases:
            d = {k: row[i] or "" for i, k in
                 enumerate(("id", "title", "fact", "process", "result", "comment"))}
            self._case_data.append(d)
            parts = [d["title"], d["fact"], d["process"], d["result"], d["comment"]]
            tok.append(self._tokenize("\n".join(parts)))
        self._cases_bm25 = BM25Okapi(tok)

        self._ready_event.set()

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