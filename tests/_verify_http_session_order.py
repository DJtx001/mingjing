"""用户视角验证：打开历史会话，消息顺序应为 旧→新（首条是 user）。

用于确认「Redis 缓存被清理后，按新逻辑回填」在 HTTP 层呈现正确。
用法：MJ_BASE=<部署地址> SMOKE_PASSWORD=<密码> python tests/_verify_http_session_order.py
"""
import os
import sys

import requests

BASE = os.environ.get("MJ_BASE", "http://127.0.0.1:8000")

SMOKE_USER = os.environ.get("SMOKE_USER", "admin")
SMOKE_PASSWORD = os.environ.get("SMOKE_PASSWORD", "")
if not SMOKE_PASSWORD:
    print("跳过：未设置 SMOKE_PASSWORD")
    sys.exit(0)

r = requests.post(f"{BASE}/auth/login",
                  json={"username": SMOKE_USER, "password": SMOKE_PASSWORD}, timeout=30)
r.raise_for_status()
h = {"Authorization": f"Bearer {r.json()['access_token']}"}

items = requests.get(f"{BASE}/assist/sessions", headers=h, timeout=30).json()["items"]
print(f"admin 会话 {len(items)} 个")
if not items:
    print("无会话可校验：先登录并发一条消息后重跑")
    sys.exit(2)
seen = bad = 0
for it in items:
    sid = it["session_id"]
    msgs = requests.get(f"{BASE}/assist/sessions/{sid}/messages", headers=h, timeout=30).json()["messages"]
    roles = [m["role"] for m in msgs]
    ok = bool(roles) and roles[0] == "user"
    if not ok:
        bad += 1
    seen += 1
    print(f"  {'✓' if ok else '✗'} {sid} {roles}  标题={it['title'][:18]!r}")
print(f"抽查被清理会话 {seen} 个，顺序异常 {bad} 个")
sys.exit(1 if bad else 0)