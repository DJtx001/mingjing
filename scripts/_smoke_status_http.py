"""真实 HTTP 验证：SSE 首帧时延 + 状态事件 + 问候短路。

用法：后端在 8000 运行；python scripts/_smoke_status_http.py
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

BASE = os.environ.get("MJ_BASE", "http://127.0.0.1:8000")

def login():
    user = os.environ.get("SMOKE_USER", "admin")
    pwd = os.environ.get("SMOKE_PASSWORD", "")
    if not pwd:
        print("跳过：未设置 SMOKE_PASSWORD")
        sys.exit(0)
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": user, "password": pwd}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def chat(token, message):
    t0 = time.time()
    first = None
    events = []
    with requests.post(f"{BASE}/assist/chat",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"session_id": None, "case_id": None, "message": message},
                       stream=True, timeout=180) as r:
        r.raise_for_status()
        buf = ""
        for chunk in r.iter_content(chunk_size=None):
            if first is None:
                first = time.time() - t0
            buf += chunk.decode("utf-8")
            while "\n\n" in buf:
                part, buf = buf.split("\n\n", 1)
                ev = part.split("\n")[0].removeprefix("event:")
                data = json.loads(part.split("\n")[1].removeprefix("data:"))
                events.append((ev, data))
    return first, events, time.time() - t0


token = login()

first, ev, total = chat(token, "你好")
types = [e[0] for e in ev]
print(f"你好：首帧 {first:.2f}s / 总 {total:.2f}s / 事件 {types}")
assert first < 1.5, f"首帧太慢：{first:.2f}s"
assert "status" not in types, types
assert ev[1][1]["delta"].startswith("你好，我是明镜"), ev[1][1]["delta"][:30]

first, ev, total = chat(token, "催讨的诉讼时效从什么时候起算？")
types = [e[0] for e in ev]
print(f"法律问题：首帧 {first:.2f}s / 总 {total:.2f}s / 事件 {types[:5]}…")
assert first < 1.5, f"首帧太慢：{first:.2f}s"
assert types[:3] == ["start", "status", "status"], types
print("\n全部通过")