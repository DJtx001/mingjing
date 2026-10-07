"""I组 统计接口（对齐《受理Agent接口文档》I 组字段名）。

MVP 只做有真实数据源的维度：知识库存量 + AI 助手使用分析。
案件/核验/复核维度依赖受理流程开工，暂不提供。
所有登录用户可查看（受理员/复核员同样需要运营数据）。
"""
import json

import pymysql
from fastapi import APIRouter, Depends

from app.core.config import config
from app.core.deps import get_current_user

router = APIRouter(prefix="/stats", tags=["I-统计"])


def _conn():
    return pymysql.connect(**config.MYSQL)


@router.get("/kb")
def kb_stats(user=Depends(get_current_user)):
    """知识库维度：条数 / 文件数 / 灌库覆盖 / 法律部门分布。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM law")
            laws = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM case_ref")
            cases = cur.fetchone()[0]
            cur.execute("SELECT vector_synced, COUNT(*) FROM law GROUP BY vector_synced")
            sync = dict(cur.fetchall())  # {0: 待灌, 1: 已灌, 2: 跳过}
            cur.execute(
                "SELECT COALESCE(category, '未分类') AS c, COUNT(*) AS n"
                " FROM law GROUP BY c ORDER BY n DESC")
            categories = [{"name": r[0], "count": r[1]} for r in cur.fetchall()]
        return {
            "laws": laws, "cases": cases,
            "synced": sync.get(1, 0), "pending": sync.get(0, 0), "skipped": sync.get(2, 0),
            "categories": categories,
        }
    finally:
        conn.close()


@router.get("/assist")
def assist_stats(days: int = 30, user=Depends(get_current_user)):
    """AI 助手维度（对齐设计 I4 assist-usage）：会话/提问/延迟/采纳率/引用 Top/无依据率/趋势。"""
    conn = _conn()
    try:
        win = "created_at >= NOW() - INTERVAL %s DAY"
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM assist_session WHERE updated_at >= NOW() - INTERVAL %s DAY", (days,))
            sessions = cur.fetchone()["n"]
            cur.execute(f"SELECT COUNT(*) AS n FROM assist_message WHERE role='user' AND {win}", (days,))
            questions = cur.fetchone()["n"]
            # answers=全部回答；延迟/无依据只统计带元数据的消息（历史消息无 context，
            # AVG/SUM 自动跳过 NULL，分母用 n_meta 保证比率准确）
            cur.execute(
                f"SELECT COUNT(*) AS n,"
                f" SUM(context IS NOT NULL) AS n_meta,"
                f" AVG(JSON_EXTRACT(context, '$.latency_ms')) AS avg_lat,"
                f" SUM(JSON_EXTRACT(context, '$.no_evidence') = 1) AS no_ev"
                f" FROM assist_message"
                f" WHERE role='assistant' AND {win}", (days,))
            row = cur.fetchone()
            answers, n_meta = row["n"] or 0, row["n_meta"] or 0
            avg_lat, no_ev = row["avg_lat"], row["no_ev"] or 0
            cur.execute(f"SELECT COUNT(*) AS n FROM assist_adoption WHERE {win}", (days,))
            adoptions = cur.fetchone()["n"]
            # 趋势：按天提问数
            cur.execute(
                f"SELECT DATE(created_at) AS d, COUNT(*) AS n FROM assist_message"
                f" WHERE role='user' AND {win} GROUP BY DATE(created_at) ORDER BY d", (days,))
            daily = [{"date": str(r["d"]), "count": r["n"]} for r in cur.fetchall()]
            # 引用 Top：Python 聚合 citations（消息量级小，不做 JSON_TABLE）
            cur.execute(
                f"SELECT citations FROM assist_message"
                f" WHERE role='assistant' AND citations IS NOT NULL AND {win}", (days,))
            counter: dict[str, dict] = {}
            for r in cur.fetchall():
                cits = r["citations"]
                if isinstance(cits, str):  # pymysql 对 JSON 列返回字符串
                    cits = json.loads(cits)
                for c in (cits or []):
                    if c.get("citation_type") != "law" or not c.get("ref_id"):
                        continue
                    item = counter.setdefault(c["ref_id"], {"ref_id": c["ref_id"],
                                                            "title": c.get("title", ""), "count": 0})
                    item["count"] += 1
            top_cited_laws = sorted(counter.values(), key=lambda x: -x["count"])[:10]
        return {
            "window_days": days,
            "sessions": sessions, "questions": questions, "answers": answers,
            "avg_latency_ms": int(avg_lat) if avg_lat else None,
            "adoptions": adoptions,
            "adoption_rate": round(adoptions / answers, 3) if answers else 0.0,
            "no_evidence_rate": round(no_ev / n_meta, 3) if n_meta else 0.0,
            "top_cited_laws": top_cited_laws,
            "daily": daily,
        }
    finally:
        conn.close()
