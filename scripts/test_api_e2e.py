"""两个页面（案件 / 统计看板）相关接口的端到端测试。

用项目自己的 JWT 工具自签测试 token（无需密码），覆盖：
  案件：鉴权、列表/筛选/字段、详情/备注
  统计：kb（与 SQL 对账）、assist（字段完整性）
  采纳回流：adopt 落两表 → 详情可见备注 → 清理
  案件感知：_load_case / _case_block / 无命中 SSE 输出（不调 LLM，零成本）
用法：python scripts/test_api_e2e.py（需后端在 8000 运行）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql
import requests

from app.core.config import config
from app.core.security import create_access_token
from app.api import assist as assist_mod

BASE = "http://127.0.0.1:8000"
PASSED, FAILED = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASSED if cond else FAILED).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def _conn():
    return pymysql.connect(**config.MYSQL)


def _users():
    conn = _conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT user_id, username, name, role FROM user ORDER BY role")
            return cur.fetchall()
    finally:
        conn.close()


def token_of(user: dict) -> str:
    return create_access_token(user)


def h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def main():
    users = _users()
    admin = next(u for u in users if u["role"] == "admin")
    clerk = next((u for u in users if u["role"] != "admin"), admin)
    t_admin, t_clerk = token_of(admin), token_of(clerk)

    print("== 案件接口 ==")
    r = requests.get(f"{BASE}/cases")
    check("未登录访问案件列表 → 401", r.status_code == 401, f"got {r.status_code}")

    r = requests.get(f"{BASE}/cases?page_size=50", headers=h(t_admin))
    d = r.json()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM case_info")
            n_cases = cur.fetchone()[0]
    finally:
        conn.close()
    check(f"登录后列表 200 且 total 与库对账 ({n_cases})",
          r.status_code == 200 and d["total"] == n_cases, str(d.get("total")))
    it = d["items"][0]
    check("列表项字段齐全", all(k in it for k in
          ("case_id", "dispute_type", "applicant_name", "status", "status_label", "triage", "updated_at")))
    check("status_label 为中文", any("一" <= ch <= "鿿" for ch in it["status_label"]), it["status_label"])

    r = requests.get(f"{BASE}/cases?status=pending_review,reject_suggested", headers=h(t_admin))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM case_info"
                        " WHERE status IN ('pending_review','reject_suggested')")
            n_multi = cur.fetchone()[0]
    finally:
        conn.close()
    check(f"status 多值筛选生效（对账 {n_multi}）", r.json()["total"] == n_multi, str(r.json()["total"]))

    case_id = "AJ2026-10086"
    r = requests.get(f"{BASE}/cases/{case_id}", headers=h(t_admin))
    d = r.json()
    check("详情返回 case+notes 结构", "case" in d and "notes" in d)
    check("详情案件正确", d["case"]["case_id"] == case_id)
    check("详情 triage=pass", d["case"]["triage"] == "pass")

    r = requests.get(f"{BASE}/cases/AJ9999-00000", headers=h(t_admin))
    check("不存在案件 → error 结构", "error" in r.json())

    print("== 采纳回流 ==")
    adopt_body = {"case_id": case_id, "session_id": "sess_e2e_test", "from_reply_id": "rep_e2e",
                  "citation_type": "law", "ref_id": "law_1", "title": "《测试法》 第一条",
                  "content": "端到端测试采纳内容", "target": "case_note"}
    r = requests.post(f"{BASE}/assist/adopt", json=adopt_body, headers=h(t_admin))
    d = r.json()
    check("采纳 200 且返回 note_id", r.status_code == 200 and d.get("note_id"), str(d))
    note_id = d.get("note_id")

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM assist_adoption WHERE session_id='sess_e2e_test'")
            check("assist_adoption 落库", cur.fetchone()[0] == 1)
            cur.execute("SELECT COUNT(*) FROM case_note WHERE from_adoption_id IS NULL AND content='端到端测试采纳内容'")
            check("case_note 落库", cur.fetchone()[0] == 1)
    finally:
        conn.close()

    r = requests.get(f"{BASE}/cases/{case_id}", headers=h(t_admin))
    notes = r.json()["notes"]
    check("详情备注区可见采纳内容", any(n["content"] == "端到端测试采纳内容" for n in notes))

    r = requests.post(f"{BASE}/assist/adopt", json={**adopt_body, "case_id": "AJ0000-0000"}, headers=h(t_admin))
    check("采纳到不存在案件 → 404", r.status_code == 404, str(r.status_code))

    print("== 统计接口 ==")
    r = requests.get(f"{BASE}/stats/kb", headers=h(t_clerk))
    # 统计看板对全部登录用户开放（受理员/复核员同样需要运营数据）
    check("受理员访问统计 → 200", r.status_code == 200, str(r.status_code))

    r = requests.get(f"{BASE}/stats/kb", headers=h(t_admin))
    kb = r.json()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM law")
            n_law = cur.fetchone()[0]
    finally:
        conn.close()
    check(f"kb.laws 与 SQL 对账 ({n_law})", kb["laws"] == n_law, str(kb["laws"]))
    check("kb 部门分布非空（13 部门）", len(kb["categories"]) >= 13, str(len(kb["categories"])))
    check("kb.synced = laws（全部已灌）", kb["synced"] == kb["laws"])

    r = requests.get(f"{BASE}/stats/assist?days=30", headers=h(t_admin))
    a = r.json()
    need = ("sessions", "questions", "answers", "adoptions", "adoption_rate",
            "no_evidence_rate", "top_cited_laws", "daily")
    check("assist 字段齐全", all(k in a for k in need), str([k for k in need if k not in a]))
    check("采纳数已对应（含 e2e 记录）", a["adoptions"] >= 1, str(a["adoptions"]))
    check("daily 为日期序列", all("date" in x and "count" in x for x in a["daily"]))

    print("== 案件感知（AI 上下文注入）==")
    case = assist_mod._load_case(case_id)
    check("_load_case 拿到案件+备注", case and case["case_id"] == case_id and len(case["notes"]) >= 1)
    block = assist_mod._case_block(case)
    check("案件块含案号/当事人/备注", case_id in block and "王某" in block and "法条" in block)
    check("_load_case 空 id → None", assist_mod._load_case(None) is None)
    check("_load_case 不存在案件 → None", assist_mod._load_case("AJ0000-0000") is None)

    # 无命中 + 有案件 → 案件卡片 + 无依据声明（确定性输出，不调 LLM）
    from app.services import session_service
    sid = session_service.create_session(admin["user_id"], case_id)
    try:
        text = []
        for evt in assist_mod._sse_stream(sid, assist_mod.ChatRequest(
                session_id=sid, case_id=case_id, message="今天天气怎么样-测试无命中")):
            if evt.startswith("event:delta"):
                text.append(json.loads(evt.split("data: ", 1)[1])["delta"])
        out = "".join(text)
        check("无命中 SSE 输出含案件卡片", "【本案信息】" in out and case_id in out)
        check("无命中 SSE 仍含无依据声明", assist_mod.NO_HIT_REPLY in out)
        # 落库 context.no_evidence 应为 1
        conn = _conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT context FROM assist_message WHERE session_id=%s AND role='assistant'"
                            " ORDER BY id DESC LIMIT 1", (sid,))
                ctx = cur.fetchone()[0]
                ctx = json.loads(ctx) if isinstance(ctx, str) else ctx
                check("no_evidence 标记已落库", ctx.get("no_evidence") == 1, str(ctx))
        finally:
            conn.close()
    finally:
        session_service.delete_session(sid)

    print("== 清理测试数据 ==")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM case_note WHERE content='端到端测试采纳内容'")
            print(f"  清理 case_note: {cur.rowcount} 行")
            cur.execute("DELETE FROM assist_adoption WHERE session_id='sess_e2e_test'")
            print(f"  清理 assist_adoption: {cur.rowcount} 行")
        conn.commit()
    finally:
        conn.close()

    print()
    print(f"结果：{len(PASSED)} 通过 / {len(FAILED)} 失败")
    if FAILED:
        print("失败项：", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
