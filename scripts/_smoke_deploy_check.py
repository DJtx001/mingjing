# -*- coding: utf-8 -*-
"""部署前本地冒烟：登录 → 对话（RAG/FC 双路径）→ 复核队列/详情 → citation 全文。

覆盖链路：
- RAG 路径（DB 正则不命中）：材料回答必带 citations，引用 ref_id 可回查 /assist/citation
- FC 路径（DB 正则命中，如「多少…法律」）：LLM 调工具接管，引用卡片=工具命中记录（2026-10-19 起）
- 复核详情（预热后首次耗时）→ 类案 ref_id → citation 四段全文（复核页弹窗数据源）
跑法：.venv/Scripts/python.exe scripts/_smoke_deploy_check.py
"""
import json
import os
import re
import sys
import time

import requests

BASE = os.environ.get("MJ_BASE", "http://127.0.0.1:8000")   # 云端验证时把 MJ_BASE 指向部署地址
sys.stdout.reconfigure(encoding="utf-8")
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# 1. 登录
SMOKE_USER = os.environ.get("SMOKE_USER", "admin")
SMOKE_PASSWORD = os.environ.get("SMOKE_PASSWORD", "")
if not SMOKE_PASSWORD:
    print("跳过：未设置 SMOKE_PASSWORD")
    sys.exit(0)
r = requests.post(f"{BASE}/auth/login",
                  json={"username": SMOKE_USER, "password": SMOKE_PASSWORD}, timeout=10)
r.raise_for_status()
H = {"Authorization": f"Bearer {r.json()['access_token']}"}
check("登录 admin", True)


def chat_ask(msg, timeout=120):
    """发一条对话，收集 (status, citations, answer, error)。"""
    cites, ans, err = [], "", None
    with requests.post(f"{BASE}/assist/chat", json={"message": msg},
                       headers=H, stream=True, timeout=timeout) as resp:
        status = resp.status_code
        ev = None
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                d = json.loads(line[5:].strip())
                if ev == "delta":
                    ans += d.get("delta", "")
                elif ev == "citations":
                    cites = d.get("citations", [])
                elif ev == "error":
                    err = d
    return status, cites, ans, err


# 2a. RAG 路径：「彩礼返还」不命中 DB 正则 → 材料回答，必带引用
t0 = time.time()
st, cites, ans, err = chat_ask("彩礼返还的条件有哪些")
check("RAG 问答 HTTP 200", st == 200, f"总耗时 {time.time()-t0:.2f}s")
check("RAG 问答无 error", err is None, str(err or ""))
check("RAG 问答有回答", len(ans) > 30, f"{len(ans)} 字")
check("RAG 问答有引用", len(cites) > 0, f"{len(cites)} 条")
check("引用均含 ref_id", bool(cites) and all(c.get("ref_id") for c in cites))
# 引用卡片应是正文实际标过的材料：检索命中但正文判定无关的（模型会写「[6] 与本题无关」）
# 不该出现在卡片区。修复前此处 FAIL（卡片 7 条 > 正文标注 6 个，2026-10-19）。
used = {int(x) for x in re.findall(r"\[(\d+)\]", ans)}
check("引用卡片数 ≤ 正文标注数（无未引用卡片）", not used or len(cites) <= len(used),
      f"卡片 {len(cites)} 条 / 正文标注 {sorted(used)}")
print(f"    回答开头：{ans[:60]}…")

# 2b. 引用回查：law / case 引用都能取到原文（复核页弹窗 + AI 助手「查看原文」同接口）
for kind in ("law", "case"):
    ref = next((c["ref_id"] for c in cites if c.get("ref_id", "").startswith(kind + "_")), None)
    if not ref:
        check(f"{kind} 引用回查（该轮无 {kind} 引用，跳过）", True)
        continue
    r2 = requests.get(f"{BASE}/assist/citation", params={"ref_id": ref}, headers=H, timeout=30)
    ok = r2.status_code == 200
    check(f"{kind} 引用 {ref} 回查 200", ok, f"正文 {len(r2.json().get('content', '')) if ok else r2.text[:60]}")

# 2c. FC 路径：「多少…法律」命中 DB 正则 → LLM 调工具接管
st, cites, ans, err = chat_ask("民间借贷的利息超过多少不受法律保护")
check("FC 问答 HTTP 200", st == 200)
check("FC 问答无 error", err is None, str(err or ""))
check("FC 问答有回答", len(ans) > 30, f"{len(ans)} 字")
check("FC 问答带引用卡片（工具命中）", len(cites) > 0, f"{len(cites)} 条")
if cites:
    ref = cites[0]["ref_id"]
    r2 = requests.get(f"{BASE}/assist/citation", params={"ref_id": ref}, headers=H, timeout=30)
    check(f"FC 引用 {ref} 回查 200", r2.status_code == 200,
          f"{r2.text[:60]}" if r2.status_code != 200 else "")
print(f"    回答开头：{ans[:60]}…")

# 3. 复核队列 + 详情（预热后首次应 <2s；详情含类案参考）
r = requests.get(f"{BASE}/reviews", headers=H, timeout=30)
r.raise_for_status()
items = r.json().get("items", [])
check("复核队列非空", len(items) > 0, f"{len(items)} 件")
if items:
    cid = items[0]["case_id"]
    t0 = time.time()
    d = requests.get(f"{BASE}/reviews/{cid}", headers=H, timeout=60).json()
    dt = time.time() - t0
    scs = d.get("similar_cases", [])
    check("复核详情结构", "case" in d)
    check("详情首次耗时 <2s（预热生效）", dt < 2.0, f"{dt:.2f}s")
    check("类案参考非空", len(scs) > 0, f"{len(scs)} 条")
    if scs:
        # 4. 类案全文（复核页「查看全文」弹窗数据源）——幽灵块清理后应 200
        all_ok = True
        for sc in scs:
            r3 = requests.get(f"{BASE}/assist/citation", params={"ref_id": sc["ref_id"]},
                              headers=H, timeout=30)
            if r3.status_code != 200:
                all_ok = False
                check(f"类案 {sc['ref_id']} 全文 200", False, r3.text[:80])
        check("全部类案点开均 200（无幽灵 ref_id）", all_ok)
        if all_ok:
            j = requests.get(f"{BASE}/assist/citation", params={"ref_id": scs[0]["ref_id"]},
                             headers=H, timeout=30).json()
            print(f"    类案《{j.get('title', '')}》正文 {len(j.get('content', ''))} 字")

print()
if fails:
    print("FAIL:", "、".join(fails))
    sys.exit(1)
print("全部 PASS ✓")