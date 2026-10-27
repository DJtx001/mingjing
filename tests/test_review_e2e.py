# -*- coding: utf-8 -*-
"""复核工作台端到端测试（E 组）。需后端 8000 与 MySQL 在跑。

用法：PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tests/test_review_e2e.py
覆盖：权限 → 队列（优先级排序/过滤）→ 详情 → 裁决（理由校验/supplement 追问回落/
pass/reject/重复裁决 409）→ 重核验重新入队。
测试后自动清理：重置夹具（清 task/decision、恢复状态、按核验结论重新入队）、清时间线。
"""
import io
import sys
from datetime import datetime

sys.path.insert(0, ".")

import pymysql
import requests

from app.core.config import config
from app.core.security import create_access_token
from app.services import review_service

BASE = "http://127.0.0.1:8000"
PASSED, FAILED = [], []
START = datetime.now()
C = "AJ2026-10083"     # 夹具①：pending_review（normal）
R = "AJ2026-10078"     # 夹具②：reject_suggested（high）
BASE_STATUS = {C: "pending_review", R: "reject_suggested"}


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


def _latest_conclusion(case_id):
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT conclusion FROM verification_report WHERE case_id=%s"
                        " ORDER BY id DESC LIMIT 1", (case_id,))
            row = cur.fetchone()
            return row["conclusion"] if row else None
    finally:
        conn.close()


def reset_fixture(case_id, base_status):
    """重置复核夹具：清 task/decision → 恢复状态 → 按核验结论重新入队（幂等）。

    注意：夹具是演示种子案件，数据可随时由流程重新产生；真实业务案件不受影响。
    """
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM review_decision WHERE case_id=%s", (case_id,))
            cur.execute("DELETE FROM review_task WHERE case_id=%s", (case_id,))
            cur.execute("UPDATE case_info SET status=%s WHERE case_id=%s", (base_status, case_id))
        conn.commit()
    finally:
        conn.close()
    review_service.enqueue(case_id, base_status, _latest_conclusion(case_id))


def cleanup():
    for case_id, base in BASE_STATUS.items():
        reset_fixture(case_id, base)
        conn = _conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM case_status_history WHERE case_id=%s AND created_at >= %s",
                            (case_id, START))
            conn.commit()
        finally:
            conn.close()
    print("（已清理：夹具已重置为演示基线）")


def main():
    t_reviewer = token_of("wangwu")    # u_004 reviewer
    t_clerk = token_of("lisi")         # u_003 intake_clerk
    t_admin = token_of("admin")

    reset_fixture(C, BASE_STATUS[C])
    reset_fixture(R, BASE_STATUS[R])

    print("== 权限 ==")
    r = requests.get(f"{BASE}/reviews", headers=h(t_clerk))
    check("受理员访问复核队列 → 403", r.status_code == 403, str(r.status_code))
    r = requests.get(f"{BASE}/reviews", headers=h(t_reviewer))
    check("复核员访问复核队列 → 200", r.status_code == 200, str(r.status_code))

    print("== 队列（E1） ==")
    d = r.json()
    ids = [i["case_id"] for i in d["items"]]
    check("队列含两个夹具案件", C in ids and R in ids, str(ids))
    prios = [i["priority"] for i in d["items"]]
    first_normal = prios.index("normal") if "normal" in prios else len(prios)
    check("high 优先级全部排在 normal 之前", "high" not in prios[first_normal:], str(prios))
    it = d["items"][0]
    check("队列字段齐全", all(k in it for k in
          ("task_id", "case_id", "dispute_type", "applicant_name", "level_reason",
           "priority", "waiting_since", "case_status", "case_status_label")))

    r2 = requests.get(f"{BASE}/reviews?status=decided", headers=h(t_reviewer))
    check("decided 过滤为空（尚未裁决）", r2.json()["items"] == [])

    print("== 详情（E2） ==")
    r = requests.get(f"{BASE}/reviews/{C}", headers=h(t_reviewer))
    d = r.json()
    check("详情结构齐全", r.status_code == 200 and all(
        k in d for k in ("case", "elements", "verification", "similar_cases",
                         "task", "previous_decisions")))
    check("详情带要素与核验", len(d["elements"]) > 0 and d["verification"] is not None)
    check("case.status_label 为中文", any("一" <= ch <= "鿿" for ch in d["case"]["status_label"]))

    print("== 裁决（E3） ==")
    r = requests.post(f"{BASE}/reviews/{C}/decision", headers=h(t_reviewer),
                      json={"decision": "supplement", "reason": "理由太短"})
    check("理由 <10 字 → 422 REV_002",
          r.status_code == 422 and r.json()["error"]["code"] == "REV_002", str(r.status_code))

    r = requests.post(f"{BASE}/reviews/{C}/decision", headers=h(t_reviewer),
                      json={"decision": "supplement",
                            "reason": "借款用途表述含糊，需当面核实用途与款项交付细节",
                            "questions": ["请当事人提供转账凭证以核实实际出借金额",
                                          "请说明借款的具体用途"]})
    d = r.json()
    check("裁决 supplement → 回要素确认", r.status_code == 200 and d["new_status"] == "awaiting_confirmation", str(d))

    r = requests.get(f"{BASE}/cases/{C}", headers=h(t_reviewer))
    fu = r.json().get("review_followup")
    check("案件详情带出追问清单", fu and len(fu["questions"]) == 2 and "用途" in fu["reason"], str(fu))

    r = requests.post(f"{BASE}/reviews/{C}/decision", headers=h(t_reviewer),
                      json={"decision": "pass", "reason": "重复裁决应被拒绝（测试）"})
    check("无待办任务再裁决 → 409 REV_001",
          r.status_code == 409 and r.json()["error"]["code"] == "REV_001", str(r.status_code))

    print("== 重核验重新入队 ==")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT element_id FROM element WHERE case_id=%s AND is_current=1 LIMIT 1", (C,))
            el = cur.fetchone()["element_id"]
    finally:
        conn.close()
    r = requests.put(f"{BASE}/cases/{C}/elements", headers=h(t_admin),
                     json={"elements": [{"element_id": el, "action": "confirm"}]})
    check("确认要素触发重核验 200", r.status_code == 200, str(r.status_code))
    d = requests.get(f"{BASE}/reviews?status=pending", headers=h(t_reviewer)).json()
    check("重新分流后重新入队", any(i["case_id"] == C for i in d["items"]))

    print("== 裁决 pass / reject ==")
    r = requests.post(f"{BASE}/reviews/{C}/decision", headers=h(t_reviewer),
                      json={"decision": "pass", "reason": "要素已补齐，纠纷属调解范围，同意受理转入文书生成"})
    check("裁决 pass → auto_passed", r.status_code == 200 and r.json()["new_status"] == "auto_passed")

    r = requests.post(f"{BASE}/reviews/{R}/decision", headers=h(t_reviewer),
                      json={"decision": "reject", "reason": "已由法院判决生效，依法不予受理，出具不予受理通知书"})
    check("裁决 reject → reject_suggested", r.status_code == 200 and r.json()["new_status"] == "reject_suggested")

    d = requests.get(f"{BASE}/reviews/{R}", headers=h(t_reviewer)).json()
    check("reject 后任务已关闭（task=null）", d["task"] is None)
    check("历史裁决留档可见", len(d["previous_decisions"]) >= 1
          and d["previous_decisions"][0]["decision"] == "reject")

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
