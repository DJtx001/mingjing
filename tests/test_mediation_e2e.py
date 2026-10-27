# -*- coding: utf-8 -*-
"""调解结果与协议书端到端测试（G 组 · M3 结案）。需后端 8000 与 MySQL 在跑。

用法：PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_mediation_e2e.py
覆盖：状态门槛 → 校验三码（分期/期限/金额/终结原因）→ 录入（快照+协议书草案）→
协议书内容 → 重录覆盖（旧草案清理）→ 未达成（终结书）→ 达成签发结案（closed+30日）→
结案后禁止重录/重签。测试后自动清理（删文书与调解结果、恢复夹具状态与文书基线）。
"""
import io
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, ".")

import pymysql
import requests

from app.core.config import config
from app.core.security import create_access_token

BASE = "http://127.0.0.1:8000"
PASSED, FAILED = [], []
START = datetime.now()
C = "AJ2026-10086"     # 夹具：重置后走 M1 全链至 issued
OTHER = "AJ2026-10083" # 非 issued（pending_review）负例


def check(name, cond, detail=""):
    mark = "✓" if cond else "✗"
    (PASSED if cond else FAILED).append(name)
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def _conn():
    return pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)


def token_of(username):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, username, name, role, org FROM user WHERE username=%s",
                        (username,))
            return create_access_token(cur.fetchone())
    finally:
        conn.close()


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def reset_fixture():
    """重置夹具：清文书/注解/调解结果 → 恢复 documents_ready（演示基线）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT doc_id FROM document WHERE case_id=%s", (C,))
            ids = [r["doc_id"] for r in cur.fetchall()]
            if ids:
                fmt = ",".join(["%s"] * len(ids))
                cur.execute(f"DELETE FROM document_annotation WHERE doc_id IN ({fmt})", ids)
                cur.execute("DELETE FROM document WHERE case_id=%s", (C,))
            cur.execute("DELETE FROM mediation_result WHERE case_id=%s", (C,))
            cur.execute("UPDATE case_info SET status='documents_ready' WHERE case_id=%s", (C,))
        conn.commit()
    finally:
        conn.close()


def cleanup():
    reset_fixture()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM case_status_history WHERE case_id=%s AND created_at >= %s",
                        (C, START))
        conn.commit()
    finally:
        conn.close()
    print("（已清理：夹具已重置为演示基线）")


def main():
    t = token_of("admin")
    reset_fixture()

    print("== 状态门槛 ==")
    r = requests.get(f"{BASE}/cases/{OTHER}/mediation-result", headers=h(t))
    check("读取非 issued 案件 → 200（只读）", r.status_code == 200, str(r.status_code))
    r = requests.put(f"{BASE}/cases/{OTHER}/mediation-result", headers=h(t),
                     json={"reached": True, "settlement": {"principal_agreed": 100}})
    check("非 issued 案件录入 → 409 MED_005",
          r.status_code == 409 and r.json()["error"]["code"] == "MED_005", str(r.status_code))

    # 走 M1 链路：生成四产出物 → 签发登记表 → issued
    r = requests.post(f"{BASE}/cases/{C}/documents/generate", json={}, headers=h(t), timeout=120)
    check("生成四产出物", r.status_code == 200 and len(r.json()["generated"]) == 4)
    doc_id = [g["doc_id"] for g in r.json()["generated"] if g["type"] == "intake_form"][0]
    r = requests.post(f"{BASE}/cases/{C}/documents/{doc_id}/issue", json={}, headers=h(t))
    check("签发登记表 → issued", r.status_code == 200 and r.json()["case_status"] == "issued")

    print("== 读取（inherit 继承） ==")
    r = requests.get(f"{BASE}/cases/{C}/mediation-result", headers=h(t))
    d = r.json()
    check("inherited 非空且带溯源", len(d["inherited"]) >= 7 and all(
        k in d["inherited"][0] for k in ("field", "from_element", "value", "origin")))
    check("result 未录为 null", d["result"] is None)

    print("== 校验（422 三码） ==")
    base_sett = {"principal_agreed": 30000, "interest_waived": True, "pay_method": "银行转账"}
    r = requests.put(f"{BASE}/cases/{C}/mediation-result", headers=h(t),
                     json={"reached": True, "settlement": {**base_sett, "installments": [
                         {"seq": 1, "due_date": str(date.today() + timedelta(days=30)), "amount": 10000},
                         {"seq": 2, "due_date": str(date.today() + timedelta(days=60)), "amount": 15000}]}})
    check("分期合计≠本金 → MED_001", r.status_code == 422 and "MED_001" in r.json()["error"]["message"])

    r = requests.put(f"{BASE}/cases/{C}/mediation-result", headers=h(t),
                     json={"reached": True, "settlement": {**base_sett, "installments": [
                         {"seq": 1, "due_date": str(date.today() - timedelta(days=1)), "amount": 30000}]}})
    check("期限早于签署日 → MED_002", r.status_code == 422 and "MED_002" in r.json()["error"]["message"])

    r = requests.put(f"{BASE}/cases/{C}/mediation-result", headers=h(t),
                     json={"reached": True, "settlement": {"principal_agreed": -1}})
    check("金额为负 → MED_003", r.status_code == 422 and "MED_003" in r.json()["error"]["message"])

    r = requests.put(f"{BASE}/cases/{C}/mediation-result", headers=h(t),
                     json={"reached": False, "settlement": {}})
    check("未达成缺终结原因 → 422", r.status_code == 422 and "终结原因" in r.json()["error"]["message"])

    print("== 录入达成（生成协议书草案） ==")
    d1 = str(date.today() + timedelta(days=30))
    d2 = str(date.today() + timedelta(days=60))
    r = requests.put(f"{BASE}/cases/{C}/mediation-result", headers=h(t),
                     json={"reached": True, "judicial_confirmation": True,
                           "settlement": {**base_sett, "installments": [
                               {"seq": 1, "due_date": d1, "amount": 10000},
                               {"seq": 2, "due_date": d2, "amount": 20000}]}})
    d = r.json()
    check("录入成功且返回协议书草案", r.status_code == 200 and d["valid"]
          and d["agreement_doc"]["type"] == "agreement" and d["agreement_doc"]["status"] == "draft",
          str(d))
    ag_doc = d["agreement_doc"]["doc_id"]

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT reached, judicial_confirmation, inherited_snapshot FROM mediation_result WHERE case_id=%s", (C,))
            row = cur.fetchone()
    finally:
        conn.close()
    check("调解结果落库（快照非空）", row and row["reached"] == 1
          and row["judicial_confirmation"] == 1 and row["inherited_snapshot"])

    r = requests.get(f"{BASE}/cases/{C}/documents/{ag_doc}", headers=h(t))
    content = r.json()["doc"]["content_md"]
    check("协议书含分期条款与司法确认", "人民调解协议书" in content and "第1期" in content
          and "司法确认" in content and "30,000" in content, content[:120])
    check("协议书带溯源锚点", len(r.json()["annotations"]) >= 1)

    print("== 重录覆盖（换方案/换类型清旧稿） ==")
    r = requests.put(f"{BASE}/cases/{C}/mediation-result", headers=h(t),
                     json={"reached": False, "settlement": {"termination_reason": "双方在履行期限上分歧过大，未能达成一致"}})
    d = r.json()
    check("改录未达成 → 生成终结书", r.status_code == 200 and d["agreement_doc"]["type"] == "termination")
    items = requests.get(f"{BASE}/cases/{C}/documents", headers=h(t)).json()["items"]
    tdoc = [i for i in items if i["type"] in ("agreement", "termination")]
    check("旧协议书草案已清（只剩终结书）", len(tdoc) == 1 and tdoc[0]["type"] == "termination",
          str([(i["type"], i["status"]) for i in tdoc]))

    r = requests.put(f"{BASE}/cases/{C}/mediation-result", headers=h(t),
                     json={"reached": True, "judicial_confirmation": True,
                           "settlement": {**base_sett, "installments": [
                               {"seq": 1, "due_date": d1, "amount": 10000},
                               {"seq": 2, "due_date": d2, "amount": 20000}]}})
    ag_doc = r.json()["agreement_doc"]["doc_id"]
    check("改回达成 → 重新生成协议书", r.status_code == 200 and r.json()["agreement_doc"]["type"] == "agreement")

    print("== 签发结案（G3） ==")
    r = requests.post(f"{BASE}/cases/{C}/agreement/issue", json={}, headers=h(t))
    d = r.json()
    expect_deadline = (date.today() + timedelta(days=30)).isoformat()
    check("签发结案 → closed", r.status_code == 200 and d["status"] == "closed", str(d))
    check("返回司法确认 30 日期限", d["judicial_confirmation_deadline"] == expect_deadline,
          str(d.get("judicial_confirmation_deadline")))

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM case_info WHERE case_id=%s", (C,))
            check("案件状态 closed", cur.fetchone()["status"] == "closed")
            cur.execute("SELECT to_status, note FROM case_status_history WHERE case_id=%s ORDER BY id DESC LIMIT 1", (C,))
            hrow = cur.fetchone()
            check("时间线记录结案", hrow["to_status"] == "closed" and "结案" in (hrow["note"] or ""), str(hrow))
            cur.execute("SELECT status FROM document WHERE doc_id=%s", (ag_doc,))
            check("协议书已签发", cur.fetchone()["status"] == "issued")
    finally:
        conn.close()

    print("== 结案后边界 ==")
    r = requests.put(f"{BASE}/cases/{C}/mediation-result", headers=h(t),
                     json={"reached": True, "settlement": base_sett})
    check("结案后重录 → 409", r.status_code == 409, str(r.status_code))
    r = requests.post(f"{BASE}/cases/{C}/agreement/issue", json={}, headers=h(t))
    check("重复签发结案 → 409", r.status_code == 409, str(r.status_code))

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
