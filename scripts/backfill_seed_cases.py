"""种子案件回填真实过程：为 8 个演示案件配陈述，用真引擎（LLM 抽取 + 规则核验）跑通，
使每个案件都有完整的"陈述 → 要素（原文引句）→ 核验 → 流转时间线"。

陈述设计原则：内容贴合案件已有的当事人/类型/状态——核验结果与种子状态一致
（如 pending_review 的案子陈述含"拒绝调解"等 warn 词，reject 的含"已判决"）。
一次性脚本，可重复跑（会先清空该案件的旧过程数据再重建）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql

from app.core.config import config
from app.services import intake_service

# case_id -> (陈述, 流程深度)
# 流程深度：note=只录陈述(draft)；extract=抽取到待确认；full=抽取+核验；full+then=再推进终态
SEED_DATA = {
    # 草稿：只录入陈述
    "AJ2026-10062": (
        "我是某物业公司的工作人员。业主周先生从2024年1月起就没有交过物业费，"
        "到现在累计欠费8600元。我们上门和电话都催过很多次，他一直说过段时间交，"
        "但始终没有付。小区的保洁、绿化、安保服务我们都正常提供，也想通过调解把费用收回来。",
        "note"),
    # 待要素确认：抽取完成停住
    "AJ2026-10055": (
        "我和刘某2018年登记结婚，婚后一起买了一套房子写的是两个人的名字，"
        "还有一辆车和十几万存款。现在感情破裂准备离婚，房子他想留给孩子、"
        "存款他想分一半多，我不同意。孩子今年7岁，抚养权我们也谈不拢，"
        "希望调解组织帮我们就财产分割和抚养问题说一说理。",
        "extract"),
    # 待复核 ×3：陈述含 warn 关键词，核验自然落 pending_review
    "AJ2026-10075": (
        "去年10月楼上吴某家水管爆裂漏水，把我家的墙面和地板都泡坏了，"
        "维修花了我12000多元。我找他协商赔偿，他说不是他家的问题，"
        "到现在一分钱不给。我们已经找社区调过一次，他当场拒绝调解、"
        "态度强硬，双方分歧过大谈不拢，我只好来申请调解。",
        "full"),
    "AJ2026-10081": (
        "我们小区业委会与物业公司在2025年的物业费标准上有争议，"
        "部分业主认为服务打折扣不愿意按新标准交费，物业公司说要起诉业主。"
        "我们组织双方开过两次协调会，物业公司拒绝调解让步，"
        "业主这边也觉得分歧过大无法沟通，想请调解组织再出面协调一次。",
        "full"),
    "AJ2026-10083": (
        "2025年6月我借给朋友周某8万元用于店面周转，有转账记录和微信聊天记录为证，"
        "约定三个月归还。到期后他只还了3万。我催了很多次，他总说生意亏了没有钱，"
        "我们因为还款计划谈了很多次，分歧过大无法沟通，希望帮我们调解一下。",
        "full"),
    # 建议不予受理：陈述含"已经判决"，规则 R4 命中
    "AJ2026-10078": (
        "钱某2024年向我借了5万元，到现在没有还。这个事情我们之前已经起诉到法院，"
        "法院已经判决过了，判决他返还本金，但我觉得判决的利息算少了，"
        "对结果不满意，想让你们再帮我调解一次，把利息要回来。",
        "full"),
    # 完整过程 → 推进到待签发
    "AJ2026-10086": (
        "2026年3月12日，我的同乡张某以资金周转为由向我借款人民币3万元，"
        "当时在他家里现金交付，他手写了一张借条，约定2026年6月30日前归还，"
        "口头说给一点利息但没有写明确利率。到期后我多次打电话催讨，他一直推脱，"
        "到现在还有2万元没有还。我想请调解组织帮我们要回这笔钱。",
        "full+documents_ready"),
    # 完整过程 → 推进到已结案
    "AJ2026-10070": (
        "2025年11月王某向我借了2万元装修房子，说好年底还。结果到了2026年春节都没还，"
        "我去他家要过两次，邻居都看到了。后来社区调解员介入，我们签了还款计划，"
        "他现在已经按期还清，想请调解组织出具书面协议确认一下这件事已经了结。",
        "full+closed"),
}


def _clean_case(case_id: str) -> None:
    """清空该案件的旧过程数据（可重复执行）。"""
    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor() as cur:
            for t in ("element", "element_confirm_log", "verification_report", "case_status_history"):
                cur.execute(f"DELETE FROM {t} WHERE case_id=%s", (case_id,))
        conn.commit()
    finally:
        conn.close()


def _admin_id() -> str:
    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM user WHERE role='admin' LIMIT 1")
            return cur.fetchone()[0]
    finally:
        conn.close()


def main():
    uid = _admin_id()
    for case_id, (narrative, depth) in SEED_DATA.items():
        _clean_case(case_id)
        conn = pymysql.connect(**config.MYSQL)
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE case_info SET narrative=%s, status='draft' WHERE case_id=%s",
                            (narrative, case_id))
            conn.commit()
        finally:
            conn.close()

        if depth == "note":
            print(f"  {case_id} 只录陈述（草稿态）✓")
            continue

        intake_service.set_status(case_id, "extracting", uid, "建案，进入要素抽取")
        els = intake_service.extract_elements(case_id, by_user_id=uid)
        n_quote = sum(1 for e in els if e["quote"])
        if depth == "extract":
            print(f"  {case_id} 抽取 {len(els)} 项要素（{n_quote} 项带原文引句）→ 待确认 ✓")
            continue

        rep = intake_service.run_verification(case_id, by_user_id=uid)
        print(f"  {case_id} 抽取 {len(els)} 项（{n_quote} 引句）→ 核验 {rep['level']}"
              f"（命中 {[f['rule_id'] for f in rep['findings']]}）")
        if depth.startswith("full+"):
            target = depth.split("+")[1]
            note = {"documents_ready": "核验通过，文书生成待签发",
                    "closed": "协议书已签发，结案"}[target]
            intake_service.set_status(case_id, target, uid, note)
            print(f"      → 推进到 {target} ✓")

    print("\n回填完成。逐个核实：")
    conn = pymysql.connect(**config.MYSQL)
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT c.case_id, c.status,
              (SELECT COUNT(*) FROM element e WHERE e.case_id=c.case_id AND e.is_current=1),
              (SELECT COUNT(*) FROM element e WHERE e.case_id=c.case_id AND e.is_current=1 AND e.quote IS NOT NULL),
              (SELECT COUNT(*) FROM verification_report v WHERE v.case_id=c.case_id),
              (SELECT COUNT(*) FROM case_status_history h WHERE h.case_id=c.case_id)
              FROM case_info c ORDER BY c.case_id""")
            print(f'{"案号":<14}{"状态":<22}{"要素":<5}{"引句":<5}{"核验":<5}{"时间线"}')
            for r in cur.fetchall():
                print(f"{r[0]:<14}{r[1]:<22}{r[2]:<5}{r[3]:<5}{r[4]:<5}{r[5]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
