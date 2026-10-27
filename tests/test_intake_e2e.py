"""受理流程端到端测试：新建 → LLM 抽取 → 人工确认 → 核验分流 → 时间线。

真实调用 LLM（DeepSeek）与规则引擎；产物入库后自动清理测试案件。
用法：python tests/test_intake_e2e.py（需后端在 8000 运行）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql
import requests

from app.core.config import config
from app.core.security import create_access_token

BASE = "http://127.0.0.1:8000"
PASSED, FAILED = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASSED if cond else FAILED).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def _conn():
    return pymysql.connect(**config.MYSQL)


def admin_token() -> str:
    conn = _conn()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT user_id, username, name, role FROM user WHERE role='admin' LIMIT 1")
            return create_access_token(cur.fetchone())
    finally:
        conn.close()


NARRATIVE_OK = (
    "2026年3月12日，我的同乡王某以资金周转为由向我借款人民币3万元，"
    "当时在他家里现金交付，他手写了一张借条，约定2026年6月30日前归还，"
    "口头说给一点利息但没有写明确利率。到期后我多次打电话催讨，他一直推脱，"
    "到现在还有2万元没有还。我想请调解组织帮我们要回这笔钱。")

NARRATIVE_BAD = (
    "2025年8月，李某拉我参与网络赌博，我输了钱之后又借给他5万元用于继续赌博，"
    "他现在不还钱。这个纠纷我们之前已经起诉到法院，法院已经判决过了，"
    "我觉得判决不公，想让你们再调解一次。")

CASE_IDS = []


def cleanup():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            for cid in CASE_IDS:
                for t in ("element", "element_confirm_log", "verification_report",
                          "case_status_history", "case_note",
                          "review_decision", "review_task",   # 核验分流会自动入队（M2）
                          "case_info"):
                    cur.execute(f"DELETE FROM {t} WHERE case_id=%s", (cid,))
        conn.commit()
    finally:
        conn.close()
    print(f"  已清理测试案件：{CASE_IDS}")


def main():
    tok = admin_token()
    h = {"Authorization": f"Bearer {tok}"}

    print("== ① 新建受理（同步 LLM 抽取）==")
    r = requests.post(f"{BASE}/cases", json={"narrative": NARRATIVE_OK,
                     "dispute_type": "民间借贷", "applicant": {"name": "张某"}}, headers=h)
    d = r.json()
    check("新建返回 201 + case_id", r.status_code == 201 and d.get("case_id"), str(d))
    cid = d.get("case_id")
    CASE_IDS.append(cid)
    check("抽取要素数 ≥ 4", d.get("elements_count", 0) >= 4, str(d.get("elements_count")))
    check("状态为待确认", d.get("status") == "awaiting_confirmation")

    r = requests.post(f"{BASE}/cases", json={"narrative": "太短"}, headers=h)
    check("过短陈述 → 422", r.status_code == 422, str(r.status_code))

    print("== ② 要素表（含原文对齐）==")
    d = requests.get(f"{BASE}/cases/{cid}/elements", headers=h).json()
    els = d["elements"]
    check("返回要素列表", len(els) >= 4)
    with_quote = [e for e in els if e["quote"]]
    check("多数要素带原文引句", len(with_quote) >= 3, f"{len(with_quote)}/{len(els)}")
    aligned = [e for e in with_quote if e["start_offset"] is not None]
    check("引句 offset 成功对齐原文", len(aligned) == len(with_quote),
          f"对齐 {len(aligned)}/{len(with_quote)}")
    if aligned:
        e = aligned[0]
        check("offset 指向的原文==引句", d["narrative"][e["start_offset"]:e["end_offset"]] == e["quote"])
    amount = next((e for e in els if e["name"] == "借款金额"), None)
    check("借款金额抽取正确（3万）", amount and "3万" in (amount["value"] or ""),
          str(amount and amount["value"]))

    print("== ③ 人工确认（含修正，自动触发核验）==")
    acts = []
    first = True
    for e in els:
        if first and e["value"]:
            acts.append({"element_id": e["element_id"], "action": "modify",
                         "value": e["value"], "reason": "演示：修正确认无误（测试理由）"})
            first = False
        elif e["value"]:
            acts.append({"element_id": e["element_id"], "action": "confirm"})
        else:
            acts.append({"element_id": e["element_id"], "action": "mark_missing"})
    r = requests.put(f"{BASE}/cases/{cid}/elements", json={"elements": acts}, headers=h)
    d = r.json()
    check("确认接口 200", r.status_code == 200, str(d))
    check("统计正确（确认/修正/缺失）", d.get("confirmed_count", 0) >= 1 and d.get("modified_count") == 1)
    check("自动核验返回 level", d.get("verification", {}).get("level") in
          ("auto_pass", "pending_review", "reject_suggestion"))
    level_clean = d["verification"]["level"]

    r = requests.put(f"{BASE}/cases/{cid}/elements",
                     json={"elements": [{"element_id": els[0]["element_id"], "action": "modify", "value": "x"}]},
                     headers=h)
    check("修正缺理由 → 400", r.status_code == 400, str(r.status_code))

    print("== ④ 硬伤案件：规则命中 → 不予受理建议 ==")
    r = requests.post(f"{BASE}/cases", json={"narrative": NARRATIVE_BAD,
                     "dispute_type": "民间借贷", "applicant": {"name": "王某"}}, headers=h)
    cid2 = r.json().get("case_id")
    CASE_IDS.append(cid2)
    els2 = requests.get(f"{BASE}/cases/{cid2}/elements", headers=h).json()["elements"]
    acts2 = [{"element_id": e["element_id"],
              "action": "confirm" if e["value"] else "mark_missing"} for e in els2]
    d = requests.put(f"{BASE}/cases/{cid2}/elements", json={"elements": acts2}, headers=h).json()
    check("含赌博/已判决 → reject_suggestion", d["verification"]["level"] == "reject_suggestion",
          d["verification"]["level"])
    hits = [f["rule_id"] for f in d["verification"]["findings"]]
    check("命中 R1（刑事）与 R4（已判决）", "R1" in hits and "R4" in hits, str(hits))
    check("结论含规则依据", "依据" in d["verification"]["conclusion"] or "不予受理" in d["verification"]["conclusion"])

    print("== ⑤ 核验报告 + 详情时间线 ==")
    rep = requests.get(f"{BASE}/cases/{cid2}/verification", headers=h).json()
    check("报告含 hard_findings", len(rep.get("hard_findings", [])) >= 2, str(rep.get("hard_findings")))
    det = requests.get(f"{BASE}/cases/{cid}", headers=h).json()
    check("详情含陈述原文", det["case"]["narrative"] == NARRATIVE_OK)
    hist = [h2["to_status"] for h2 in det["history"]]
    check("流转时间线完整（draft→extracting→awaiting→核验态）",
          "extracting" in hist and "awaiting_confirmation" in hist and len(hist) >= 3, str(hist))
    check(f"干净案件分流级别合理（{level_clean}）", level_clean in ("auto_pass", "pending_review"))

    print("== 清理 ==")
    cleanup()

    print()
    print(f"结果：{len(PASSED)} 通过 / {len(FAILED)} 失败")
    if FAILED:
        print("失败项：", FAILED)
        sys.exit(1)


if __name__ == "__main__":
    main()
