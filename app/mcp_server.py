"""MCP Server — 将明镜系统的案件/法条/统计能力暴露为 MCP Tool。

用法（stdio 模式，给 Claude Code / Claude Desktop）：
  python -m app.mcp_server

配置到 .claude/settings.local.json：
  {
    "mcpServers": {
      "mingjing": {
        "command": "python",
        "args": ["-m", "app.mcp_server"],
        "cwd": "C:\\Code\\Project\\ai-qiuzhao\\mingjing-intake"
      }
    }
  }
"""
import sys
from pathlib import Path

# Windows 下强制 stdout 用 UTF-8，否则中文输出炸
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 确保能找到项目包（从任意 cwd 启动都能 import app.xxx）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import json
import pymysql
from mcp.server.mcpserver import MCPServer

from app.core.config import config
from app.services.retrieval_service import retrieve

server = MCPServer(
    "明镜·要素式智能受理系统",
    instructions=(
        "明镜系统的知识库与案件查询接口。你可以搜索法条、搜索案例、"
        "查看案例/法条详情、查询统计信息。所有搜索使用混合检索"
        "（向量语义 + BM25 关键词），返回最相关的结果。"
    ),
)


def _conn():
    return pymysql.connect(**config.MYSQL)


# ── 工具函数 ──────────────────────────────────────────────


@server.add_tool
def search_law(query: str) -> str:
    """在法律知识库中搜索相关法条。query: 搜索问题/关键词"""
    try:
        r = retrieve(query, top_laws=5, top_cases=0)
    except Exception as e:
        return f"检索出错：{e}"
    if not r["laws"]:
        return "未找到相关法条。"
    lines = []
    for l in r["laws"]:
        src = l["source"]
        art = l.get("article") or ""
        dist = l.get("distance", "N/A")
        bm25 = l.get("bm25_score", "N/A")
        head = f"《{src}》"
        if art:
            head += f"第{art}条"
        if isinstance(dist, float):
            head += f"  [语义相关度={1-dist:.2f}]"
        if isinstance(bm25, float) and bm25 > 0:
            head += f"  [关键词匹配={bm25:.1f}]"
        lines.append(head)
        lines.append(l["text"][:500])
        lines.append("")
    return "\n".join(lines)


@server.add_tool
def search_case(query: str) -> str:
    """在案例库中搜索相关案例。query: 搜索问题/案情描述"""
    try:
        r = retrieve(query, top_laws=0, top_cases=5)
    except Exception as e:
        return f"检索出错：{e}"
    if not r["cases"]:
        return "未找到相关案例。"
    lines = []
    for c in r["cases"]:
        dist = c.get("distance", "N/A")
        bm25 = c.get("bm25_score", "N/A")
        head = f"🟦 {c['title']}"
        if isinstance(dist, float):
            head += f"  [语义相关度={1-dist:.2f}]"
        if isinstance(bm25, float) and bm25 > 0:
            head += f"  [关键词匹配={bm25:.1f}]"
        lines.append(head)
        lines.append(f"摘要：{c['summary'][:300]}")
        lines.append(f"相关段落：{c['hit_text'][:200]}")
        lines.append(f"ID：{c['ref_id']}")
        lines.append("")
    return "\n".join(lines)


@server.add_tool
def get_case(case_id: int) -> str:
    """按 ID 查询案例详情。case_id: 案例数字 ID（如从 search_case 返回的 case_xxx 中提取的数字）"""
    try:
        conn = _conn()
    except Exception as e:
        return f"数据库连接失败：{e}"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source, fact, process, result, comment FROM case_ref WHERE id=%s",
                (case_id,),
            )
            r = cur.fetchone()
    except Exception as e:
        return f"查询出错：{e}"
    finally:
        conn.close()
    if not r:
        return f"未找到案例 ID={case_id}。可用 search_case 搜索。"
    return (
        f"标题：{r[1]}\n"
        f"来源：{r[2] or '未知'}\n\n"
        f"【案件事实】\n{r[3][:800] if r[3] else '无'}\n\n"
        f"【裁判理由/处理过程】\n{r[4][:800] if r[4] else '无'}\n\n"
        f"【判决/处理结果】\n{r[5][:800] if r[5] else '无'}\n\n"
        f"【相关法条/评析】\n{r[6][:800] if r[6] else '无'}"
    )


@server.add_tool
def get_law(law_id: int) -> str:
    """按 ID 查询法条详情。law_id: 法条数字 ID"""
    try:
        conn = _conn()
    except Exception as e:
        return f"数据库连接失败：{e}"
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source, chapter, article, text, category FROM law WHERE id=%s",
                (law_id,),
            )
            r = cur.fetchone()
    except Exception as e:
        return f"查询出错：{e}"
    finally:
        conn.close()
    if not r:
        return f"未找到法条 ID={law_id}。可用 search_law 搜索。"
    _, source, chapter, article, text, category = r
    head = f"《{source}》"
    if chapter:
        head += f" {chapter}"
    if article:
        head += f" 第{article}条"
    return f"{head}\n分类：{category or '未分类'}\n\n{text[:1500]}"


@server.add_tool
def get_stats() -> str:
    """查询知识库统计信息：法条总数、案例总数、向量化覆盖率"""
    try:
        conn = _conn()
    except Exception as e:
        return f"数据库连接失败：{e}"
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM law")
            laws = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM case_ref")
            cases = cur.fetchone()[0]
            cur.execute("SELECT vector_synced, COUNT(*) FROM law GROUP BY vector_synced")
            lsync = dict(cur.fetchall())
            cur.execute("SELECT vector_synced, COUNT(*) FROM case_ref GROUP BY vector_synced")
            csync = dict(cur.fetchall())
    except Exception as e:
        return f"查询出错：{e}"
    finally:
        conn.close()
    lpct = (lsync.get(1, 0) / laws * 100) if laws else 0
    cpct = (csync.get(1, 0) / cases * 100) if cases else 0
    return (
        f"法条：{laws} 条（已灌库 {lsync.get(1,0)}、待灌 {lsync.get(0,0)}、跳过 {lsync.get(2,0)}）覆盖率 {lpct:.0f}%\n"
        f"案例：{cases} 条（已灌库 {csync.get(1,0)}、待灌 {csync.get(0,0)}、跳过 {csync.get(2,0)}）覆盖率 {cpct:.0f}%"
    )


@server.add_tool
def search_case_by_title(keyword: str) -> str:
    """按案号/标题关键词精确搜索案例。keyword: 案号或标题关键词（支持模糊匹配）"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source FROM case_ref WHERE title LIKE %s ORDER BY id LIMIT 15",
                (f"%{keyword}%",),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    if not rows:
        return f"未找到标题含「{keyword}」的案例。尝试 search_case 语义搜索。"
    lines = [f"找到 {len(rows)} 个匹配案例："]
    for r in rows:
        lines.append(f"  ID={r[0]}  {r[1][:60]}")
        if r[2]:
            lines[-1] += f"  [{r[2]}]"
    return "\n".join(lines)


if __name__ == "__main__":
    server.run(transport="stdio")