# -*- coding: utf-8 -*-
"""文书模块端到端测试（F6 生成 + F7 签发）。需后端 8000 与 MySQL 在跑。

用法：cd mingjing-intake && .venv/Scripts/python.exe tests/test_documents_e2e.py
覆盖：列表/权限/负例 → 生成（锚点合法性、联表 label、幂等重生成）→ 状态推进 →
      逐份签发（终态判定、残稿归档）→ 重复签发/已签发重生成/C2 守卫 → reject 链路。
测试后自动清理：删除测试产生的文书与注解、按快照恢复案件状态、清测试期时间线。
"""
import sys
import io
from datetime import datetime

sys.path.insert(0, ".")

import pymysql
import requests

from app.core.config import config
from app.core.security import create_access_token

BASE = "http://127.0.0.1:8000"
PASSED, FAILED = [], []
SNAPSHOT = {}   # case_id -> {"status": 原状态, "start": 测试开始时间}
START = datetime.now()


def check(name, cond, detail=""):
    mark = "✓" if cond else "✗"
    (PASSED if cond else FAILED).append(name)
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def _conn():
    return pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)


def admin_token():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, username, name, role, org FROM user WHERE username='admin'")
            return create_access_token(cur.fetchone())
    finally:
        conn.close()


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def snapshot(case_id):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM case_info WHERE case_id=%s", (case_id,))
            SNAPSHOT[case_id] = {"status": cur.fetchone()["status"], "start": START}
    finally:
        conn.close()


def reset_fixture(case_id, base_status):
    """把演示种子案件重置到干净基线（清其文书 + 恢复状态）。

    注意：夹具是演示种子案件（AJ2026-10086 / AJ2026-10078）——数据可随时由
    界面重新生成；真实业务案件不受本脚本影响。
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT doc_id FROM document WHERE case_id=%s", (case_id,))
            doc_ids = [r["doc_id"] for r in cur.fetchall()]
            if doc_ids:
                fmt = ",".join(["%s"] * len(doc_ids))
                cur.execute(f"DELETE FROM document_annotation WHERE doc_id IN ({fmt})", doc_ids)
                cur.execute("DELETE FROM document WHERE case_id=%s", (case_id,))
            cur.execute("UPDATE case_info SET status=%s WHERE case_id=%s", (base_status, case_id))
        conn.commit()
    finally:
        conn.close()


def cleanup():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            for case_id, snap in SNAPSHOT.items():
                cur.execute("SELECT doc_id FROM document WHERE case_id=%s", (case_id,))
                doc_ids = [r["doc_id"] for r in cur.fetchall()]
                if doc_ids:
                    fmt = ",".join(["%s"] * len(doc_ids))
                    cur.execute(f"DELETE FROM document_annotation WHERE doc_id IN ({fmt})", doc_ids)
                    cur.execute("DELETE FROM document WHERE case_id=%s", (case_id,))
                cur.execute("UPDATE case_info SET status=%s WHERE case_id=%s",
                            (snap["status"], case_id))
                cur.execute("DELETE FROM case_status_history WHERE case_id=%s AND created_at >= %s",
                            (case_id, snap["start"]))
        conn.commit()
    finally:
        conn.close()
    print(f"（已清理：{len(SNAPSHOT)} 个案件的文书与状态已恢复）")


def main():
    tok = admin_token()
    C, R = "AJ2026-10086", "AJ2026-10078"     # 夹具：待签发(auto_pass) / 不予受理意见
    reset_fixture(C, "documents_ready")       # 重置到干净基线（可重复跑，不受试用痕迹影响）
    reset_fixture(R, "reject_suggested")
    snapshot(C)
    snapshot(R)

    print("== 列表与权限 ==")
    r = requests.get(f"{BASE}/cases/{C}/documents", headers=h(tok))
    d = r.json()
    check("文书列表 200 且结构正确", r.status_code == 200 and d["case_id"] == C and d["case_status"] == "documents_ready")
    check("重置后：尚无文书", d["items"] == [])

    r = requests.get(f"{BASE}/cases/{C}/documents")
    check("未登录访问 → 401", r.status_code == 401, str(r.status_code))

    r = requests.get(f"{BASE}/cases/AJ9999-00000/documents", headers=h(tok))
    check("案件不存在 → DOC_001/404", r.status_code == 404 and r.json()["error"]["code"] == "DOC_001")

    print("== 生成（负例与单份） ==")
    r = requests.post(f"{BASE}/cases/AJ2026-10083/documents/generate", json={}, headers=h(tok))
    check("pending_review 案件生成 → 409 DOC_003",
          r.status_code == 409 and r.json()["error"]["code"] == "DOC_003", str(r.status_code))

    r = requests.post(f"{BASE}/cases/{C}/documents/generate", json={"types": ["intake_form"]},
                      headers=h(tok), timeout=90)
    d = r.json()
    check("生成受理登记表 200", r.status_code == 200 and len(d["generated"]) == 1)
    g = d["generated"][0]
    check("doc_id 格式正确", g["doc_id"].startswith("doc_"), g.get("doc_id"))
    check("登记表内容充实（>400字）", g["chars"] > 400, str(g.get("chars")))
    check("锚点数量 >= 7（有值要素数）", g["annotations"] >= 7, str(g.get("annotations")))
    doc_id_form = g["doc_id"]

    print("== 锚点合法性（SQL 校验） ==")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content_md FROM document WHERE doc_id=%s", (doc_id_form,))
            content = cur.fetchone()["content_md"]
            cur.execute("SELECT anchor_start, anchor_end, ref_type, ref_id FROM document_annotation"
                        " WHERE doc_id=%s ORDER BY anchor_start", (doc_id_form,))
            anns = cur.fetchall()
    finally:
        conn.close()
    ok_range = all(0 <= a["anchor_start"] < a["anchor_end"] <= len(content) for a in anns)
    ok_slice = all(content[a["anchor_start"]:a["anchor_end"]].strip() for a in anns)
    check("锚点区间均合法", ok_range)
    check("每个锚点切片非空", ok_slice)
    has_name = any("借款金额" in content[a["anchor_start"]:a["anchor_end"]] for a in anns)
    check("金额行锚点切片含要素名（借款金额）", has_name)
    # 防回归：锚点不能吞掉行首 markdown 语法标记（| / - / # / >），否则前端注入 <span> 会破坏表格/列表渲染
    ok_no_marker = all(
        not content[a["anchor_start"]:a["anchor_end"]].lstrip().startswith(("|", "-", "#", ">"))
        for a in anns)
    check("锚点不吞 markdown 语法标记", ok_no_marker)
    check("锚点类型均为 element_source", all(a["ref_type"] == "element" for a in anns if a["ref_type"]))

    print("== 详情与联表 label ==")
    r = requests.get(f"{BASE}/cases/{C}/documents/{doc_id_form}", headers=h(tok))
    d = r.json()
    labels = {(a["label"], a["sub_label"]) for a in d["annotations"]}
    check("详情返回正文与注解", r.status_code == 200 and d["doc"]["content_md"] == content)
    check("联表 label 正确（借款金额/3万元）",
          any(lbl == "借款金额" and "3万" in (sub or "") for lbl, sub in labels), str(list(labels)[:3]))
    check("覆盖率统计存在", d["stats"]["annotations"] >= 7 and d["stats"]["lines"] > 0, str(d.get("stats")))

    print("== 幂等重生成 ==")
    r = requests.post(f"{BASE}/cases/{C}/documents/generate", json={"types": ["intake_form"]},
                      headers=h(tok), timeout=90)
    g2 = r.json()["generated"][0]
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM document WHERE case_id=%s AND type='intake_form'", (C,))
            n_doc = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM document_annotation WHERE doc_id=%s", (doc_id_form,))
            n_ann = cur.fetchone()["n"]
    finally:
        conn.close()
    check("重生成 doc_id 不变", g2["doc_id"] == doc_id_form)
    check("同案同类型仍只有 1 份", n_doc == 1, str(n_doc))
    check("注解不翻倍", n_ann == len(anns), f"{n_ann} vs {len(anns)}")

    print("== 状态推进（模拟 auto_passed 起点） ==")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE case_info SET status='auto_passed' WHERE case_id=%s", (C,))
        conn.commit()
    finally:
        conn.close()
    r = requests.post(f"{BASE}/cases/{C}/documents/generate", json={}, headers=h(tok), timeout=120)
    d = r.json()
    check("缺省生成四产出物（真 LLM）", r.status_code == 200 and len(d["generated"]) == 4,
          str([g["type"] for g in d.get("generated", [])]))
    types_now = {g["type"] for g in d["generated"]}
    check("四类齐全", types_now == {"case_profile", "verify_report", "intake_form", "similar_cases"},
          str(types_now))
    check("案件状态 → documents_ready", d["case_status"] == "documents_ready", d["case_status"])
    check("case_profile 含降级/正常两段之一", any(
        "无争议事实" in (requests.get(f"{BASE}/cases/{C}/documents/{g['doc_id']}", headers=h(tok)).json()["doc"]["content_md"])
        for g in d["generated"] if g["type"] == "case_profile"))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM case_status_history WHERE case_id=%s AND created_at >= %s",
                        (C, START))
            check("时间线新增流转记录", cur.fetchone()["n"] >= 1)
    finally:
        conn.close()

    print("== 逐份签发与终态判定 ==")
    docs = requests.get(f"{BASE}/cases/{C}/documents", headers=h(tok)).json()["items"]
    by_type = {i["type"]: i["doc_id"] for i in docs}
    check("文书列表 4 份皆草案", len(docs) == 4 and all(i["status"] == "draft" for i in docs))

    r = requests.post(f"{BASE}/cases/{C}/documents/{by_type['verify_report']}/issue", json={}, headers=h(tok))
    d = r.json()
    check("单独签发核验报告 200", r.status_code == 200 and d["status"] == "issued")
    check("案件仍为 documents_ready（未触发终态）", d["case_status"] == "documents_ready", d["case_status"])

    r = requests.post(f"{BASE}/cases/{C}/documents/generate", json={"types": ["verify_report"]},
                      headers=h(tok), timeout=90)
    check("重生成已签发文书 → 409 DOC_002",
          r.status_code == 409 and r.json()["error"]["code"] == "DOC_002", str(r.status_code))

    r = requests.post(f"{BASE}/cases/{C}/documents/{by_type['intake_form']}/issue", json={}, headers=h(tok))
    d = r.json()
    check("签发受理登记表 → 案件 issued", r.status_code == 200 and d["case_status"] == "issued", str(d))
    check("残稿一并归档（also_issued 2 份）", len(d["also_issued"]) == 2, str(d["also_issued"]))
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM document WHERE case_id=%s AND status='draft'", (C,))
            check("无残留草案", cur.fetchone()["n"] == 0)
    finally:
        conn.close()

    print("== 签发边界 ==")
    r = requests.post(f"{BASE}/cases/{C}/documents/{by_type['intake_form']}/issue", json={}, headers=h(tok))
    check("重复签发 → 409 DOC_004",
          r.status_code == 409 and r.json()["error"]["code"] == "DOC_004", str(r.status_code))
    r = requests.post(f"{BASE}/cases/{C}/documents/generate", json={}, headers=h(tok))
    check("issued 案件生成 → 409 DOC_003",
          r.status_code == 409 and r.json()["error"]["code"] == "DOC_003", str(r.status_code))

    # C2 守卫：已签发案件不可再改要素
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT element_id FROM element WHERE case_id=%s AND is_current=1 LIMIT 1", (C,))
            el_id = cur.fetchone()["element_id"]
    finally:
        conn.close()
    r = requests.put(f"{BASE}/cases/{C}/elements", headers=h(tok),
                     json={"elements": [{"element_id": el_id, "action": "confirm"}]})
    check("已签发案件 C2 确认 → 409", r.status_code == 409, str(r.status_code))

    print("== reject 链路（AJ2026-10078） ==")
    r = requests.post(f"{BASE}/cases/{R}/documents/generate", json={}, headers=h(tok), timeout=90)
    d = r.json()
    check("reject_suggested 生成通知书 1 份",
          r.status_code == 200 and [g["type"] for g in d["generated"]] == ["reject_notice"], str(d))
    check("生成后案件仍 reject_suggested", d["case_status"] == "reject_suggested", d["case_status"])
    notice_id = d["generated"][0]["doc_id"]

    r = requests.get(f"{BASE}/cases/{R}/documents/{notice_id}", headers=h(tok))
    content = r.json()["doc"]["content_md"]
    check("通知书含硬规则依据（R4 已判决）", "已判决或已受理" in content and "不予受理通知书" in content)

    r = requests.post(f"{BASE}/cases/{R}/documents/{notice_id}/issue", json={}, headers=h(tok))
    d = r.json()
    check("签发通知书 → 案件 rejected 终态", r.status_code == 200 and d["case_status"] == "rejected", str(d))
    r = requests.post(f"{BASE}/cases/{R}/documents/{notice_id}/issue", json={}, headers=h(tok))
    check("rejected 后重复签发 → 409", r.status_code == 409, str(r.status_code))

    print(f"\n== 结果：{len(PASSED)} 通过 / {len(FAILED)} 失败 ==")
    if FAILED:
        for f in FAILED:
            print("  ✗", f)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    try:
        main()
    finally:
        cleanup()
    sys.exit(1 if FAILED else 0)
