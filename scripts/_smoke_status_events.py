"""验证 SSE 状态事件：首帧 start 立即发出；问候/时间类不检索不调 LLM；普通问题有检索+思考两条状态。

全部依赖打桩，不碰真实 Redis / MySQL / Chroma / LLM。
"""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from app.api import assist  # noqa: E402

# ---- 打桩 ----
assist.session_service.get_messages = lambda sid: []
assist.session_service.append_message = lambda *a, **k: None
assist._load_case = lambda cid: None
calls = {"retrieve": 0}


def fake_retrieve(q):
    calls["retrieve"] += 1
    return {"laws": [], "cases": [], "intent_rejected": True}


assist.retrieval_service.retrieve = fake_retrieve
assist.retrieval_service.build_context = lambda r: ("", [])
assist._try_function_calling = lambda m, q: (False, m, [])


def run(msg, cid=None):
    events = []
    for chunk in assist._sse_stream(
        "s_test", assist.ChatRequest(session_id="s_test", case_id=cid, message=msg)
    ):
        part = chunk.strip()
        ev = part.split("\n")[0].removeprefix("event:")
        data = json.loads(part.split("\n")[1].removeprefix("data:"))
        events.append((ev, data))
    return events


# 1) 问候：无 status、不检索，首帧 start
ev = run("你好")
types = [e[0] for e in ev]
assert types[0] == "start", types
assert "status" not in types, types
assert calls["retrieve"] == 0, "问候不该走检索"
assert ev[1][1]["delta"].startswith("你好，我是明镜"), ev[1][1]["delta"][:20]
print("PASS 问候:", types)

# 2) 时间类：同样短路
ev = run("现在几点了")
types = [e[0] for e in ev]
assert "status" not in types and calls["retrieve"] == 0, types
assert "现在是" in ev[1][1]["delta"], ev[1][1]["delta"][:20]
print("PASS 时间类:", types)

# 3) 普通法律问题：start → status(检索) → status(思考) → delta → done
ev = run("催讨的诉讼时效从什么时候起算？")
types = [e[0] for e in ev]
assert types[:3] == ["start", "status", "status"], types
assert "正在检索" in ev[1][1]["text"], ev[1][1]
assert "正在思考" in ev[2][1]["text"], ev[2][1]
assert calls["retrieve"] == 1, calls
assert types[-1] == "done", types
print("PASS 法律问题:", types, "|", ev[1][1]["text"], "/", ev[2][1]["text"])

print("\n全部通过")