# -*- coding: utf-8 -*-
"""演示测试数据播种：用真引擎新建 5 个案件，覆盖各流程节点（供列表/队列/徽章/调解测试）。

分布：pending_review ×2（R5 分歧）· reject_suggested ×1（R4 已起诉）·
      documents_ready ×1（干净侵权案）· issued ×1（干净借贷案，可直接测调解结案）。

用法：PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/seed_demo_cases.py
幂等：陈述带"〔演示数据 D〕"标记——重跑先清理旧演示数据再重建（真 LLM 抽取约 30~60 秒）。
"""
import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

import pymysql
import requests

from app.core.config import config
from app.core.security import create_access_token

BASE = "http://127.0.0.1:8000"
MARK = "〔演示数据 D〕"

# (陈述, 纠纷类型, 当事人, 目标状态)
CASES = [
    ("2026年4月，邻居王某以孩子上学为由向我借款 5 万元，通过微信转账 3 万、现金 2 万，"
     "约定 10 月归还。到期后我多次催讨，对方说资金紧张要再缓半年，双方分歧过大谈不拢；"
     "我要求先还一半，他不同意调解，拒绝沟通。", "民间借贷", "陈某 vs 王某", "pending_review"),
    ("某物业公司称我拖欠 2024-2025 年度物业费共计 8600 元，多次催缴未果。但该纠纷已经起诉到"
     "区人民法院，法院已经立案受理。现物业公司又来找我要求先调解。", "物业服务", "某物业公司 vs 周先生", "reject_suggested"),
    ("2026年5月，我在小区内被邻居家饲养的宠物狗扑倒摔伤，右手腕骨折，花费医疗费 6800 元，"
     "有医院票据和监控视频。我要求对方赔偿医疗费和误工费共计 1 万元，对方只愿赔 3000 元。",
     "侵权赔偿", "林某 vs 郑某", "documents_ready"),
    ("我与丈夫 2018 年登记结婚，育有一子 7 岁。因性格不合长期争吵，双方都同意离婚，"
     "但对房产分割分歧过大——他主张婚前首付部分归个人所有，我要求平均分割；"
     "孩子抚养权双方都不愿让步，谈不拢。", "婚姻家庭", "刘某 vs 韩某", "pending_review"),
    # 姓名要点明：第一人称「我」抽不出「出借人」要素 → 核心要素待补 → 会掉进 pending_review
    ("2026年2月，吴某借给同事李某 2 万元应急，约定一个月内归还，至今未还，吴某多次催讨无果。"
     "当时只有口头约定，没有借条，微信聊天记录可以证明。", "民间借贷", "吴某 vs 李某", "issued"),
]


def _conn():
    return pymysql.connect(**config.MYSQL, cursorclass=pymysql.cursors.DictCursor)


def token_of_admin():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, username, name, role, org FROM user WHERE username='admin'")
            return create_access_token(cur.fetchone())
    finally:
        conn.close()


def h(tok):
    return {"Authorization": f"Bearer {tok}"}


def cleanup_old():
    """清理旧的演示数据（按陈述标记匹配，连带全部派生数据）。"""
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT case_id FROM case_info WHERE narrative LIKE %s", (MARK + "%",))
            ids = [r["case_id"] for r in cur.fetchall()]
            for cid in ids:
                cur.execute("SELECT doc_id FROM document WHERE case_id=%s", (cid,))
                doc_ids = [r["doc_id"] for r in cur.fetchall()]
                if doc_ids:
                    fmt = ",".join(["%s"] * len(doc_ids))
                    cur.execute(f"DELETE FROM document_annotation WHERE doc_id IN ({fmt})", doc_ids)
                for t in ("document", "review_decision", "review_task", "mediation_result",
                          "element_confirm_log", "element", "verification_report",
                          "case_status_history", "case_note", "assist_adoption", "case_info"):
                    cur.execute(f"DELETE FROM {t} WHERE case_id=%s", (cid,))
        conn.commit()
    finally:
        conn.close()
    if ids:
        print(f"已清理旧演示数据：{ids}")


def main():
    tok = token_of_admin()
    cleanup_old()
    print(f"开始播种 {len(CASES)} 个演示案件（真 LLM 抽取，约 30~60 秒）…\n")

    for narrative, dtype, applicant, target in CASES:
        t0 = time.time()
        r = requests.post(f"{BASE}/cases", headers=h(tok), timeout=120, json={
            "narrative": MARK + narrative, "dispute_type": dtype, "applicant": {"name": applicant}})
        if r.status_code != 201:
            print(f"✗ 建案失败：{r.status_code} {r.text[:120]}")
            continue
        cid = r.json()["case_id"]

        if target == "awaiting_confirmation":
            final = "awaiting_confirmation"
        else:
            # 确认全部要素 → 自动核验分流
            els = requests.get(f"{BASE}/cases/{cid}/elements", headers=h(tok)).json()["elements"]
            actions = [{"element_id": e["element_id"], "action": "confirm"} for e in els]
            vr = requests.put(f"{BASE}/cases/{cid}/elements", headers=h(tok),
                              json={"elements": actions}, timeout=60).json()
            level = vr["verification"]["level"]
            final = {"auto_pass": "auto_passed", "pending_review": "pending_review",
                     "reject_suggestion": "reject_suggested"}[level]

            if target in ("documents_ready", "issued"):
                gr = requests.post(f"{BASE}/cases/{cid}/documents/generate", headers=h(tok),
                                   json={}, timeout=180)
                if gr.status_code != 200:
                    # 状态守卫（如核验分流出 pending_review）会返回 409——别把 final 写成成功
                    print(f"✗ {cid} 生成文书失败 {gr.status_code}：{gr.text[:100]}")
                    continue
                final = "documents_ready"
            if target == "issued":
                docs = requests.get(f"{BASE}/cases/{cid}/documents", headers=h(tok)).json()["items"]
                fid = next((d["doc_id"] for d in docs if d["type"] == "intake_form"), None)
                if not fid:
                    print(f"✗ {cid} 未生成受理登记表（状态 {final}），跳过签发")
                    continue
                requests.post(f"{BASE}/cases/{cid}/documents/{fid}/issue",
                              headers=h(tok), json={})
                final = "issued"

        ok = "✓" if final == target else "✗"
        print(f"{ok} {cid}  {dtype}｜{applicant} → {final}（目标 {target}，{time.time()-t0:.0f}s）")
        if final != target:
            print(f"   注意：核验分流为 {final}，与目标 {target} 不符（检查陈述文案与规则词表）")

    print("\n完成。当前案件分布：")
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, COUNT(*) n FROM case_info GROUP BY status ORDER BY n DESC")
            for r in cur.fetchall():
                print(f"  {r['status']:24s} {r['n']}")
            cur.execute("SELECT COUNT(*) n FROM review_task WHERE status='pending'")
            print(f"  复核队列 pending：{cur.fetchone()['n']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
