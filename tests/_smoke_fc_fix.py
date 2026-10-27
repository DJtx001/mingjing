# -*- coding: utf-8 -*-
"""FC 分支修复冒烟（08bf924 缩进事故的回归防线）。

mock 掉检索 / LLM provider / 会话层，直接驱动 assist._sse_stream 覆盖 6 个分支场景：
  ① 无命中+问候        → 确定性问候文案（零 LLM）
  ② 无命中+时间        → 确定性时间文案
  ③ 无命中+正则+不调工具 → NO_HIT_REPLY 兜底（零流式）
  ④ 无命中+正则+调工具   → FC 流式（DB 结果注入）        【bug A 回归点】
  ⑤ 有材料+正则+不调工具 → 材料正常回答，不被兜底吞掉    【bug B 回归点】
  ⑥ 有材料+无正则       → 材料正常回答（不尝试 FC）

跑法（项目根）：.venv/Scripts/python.exe tests/_smoke_fc_fix.py
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.api import assist

MATERIAL = "【参考法条】\n[1] 某条文内容"
CITATION = {"citation_type": "law", "ref_id": "law_1", "title": "《测试法》第一条", "snippet": "…"}
FC_REF = {"citation_type": "similar_case", "ref_id": "case_1", "title": "模拟案例", "snippet": ""}


def run(message: str, context: str = "", tool_calls=None):
    """驱动 _sse_stream 收集输出。返回 (输出文本, chat 调用列表, stream 消息列表, append 调用列表)。"""
    body = assist.ChatRequest(message=message, case_id=None)
    fake = mock.Mock()
    chat_calls, stream_msgs, appends = [], [], []
    fake.chat = lambda msgs, **kw: (chat_calls.append(msgs) or SimpleNamespace(tool_calls=tool_calls))

    def fake_stream(msgs, **kw):
        stream_msgs.append(msgs)
        yield "回答片段"

    fake.stream = fake_stream

    retrieved = {"laws": [], "cases": [], "intent_rejected": False}
    with mock.patch.object(assist, "provider", fake), \
         mock.patch.object(assist, "_exec_db_tool", return_value=("（模拟）案例 ID=1", [FC_REF])), \
         mock.patch.object(assist.retrieval_service, "retrieve", return_value=retrieved), \
         mock.patch.object(assist.retrieval_service, "build_context",
                           return_value=(context, [CITATION] if context else [])), \
         mock.patch.object(assist.session_service, "get_messages", return_value=[]), \
         mock.patch.object(assist.session_service, "append_message",
                           side_effect=lambda *a, **kw: appends.append((a, kw))):
        out = "".join(assist._sse_stream("s_test", body))
    return out, chat_calls, stream_msgs, appends


def check(name: str, cond: bool, detail: str = ""):
    if not cond:
        print(f"FAIL: {name}\n  detail: {detail}")
        sys.exit(1)
    print(f"PASS: {name}")


def main():
    # 前置自检：场景标注依赖正则语义，若以后改正则需同步
    check("正则命中「多少…法律」", assist._DB_QUERY_PATTERN.search("民间借贷的利息超过多少不受法律保护") is not None)
    check("正则不命中问候", assist._DB_QUERY_PATTERN.search("你好") is None)

    # ① 无命中+问候：零 LLM、确定性文案
    out, chat_calls, stream_msgs, _ = run("你好")
    check("①问候-零LLM", not chat_calls and not stream_msgs, f"chat={len(chat_calls)} stream={len(stream_msgs)}")
    check("①问候-确定性文案", "明镜 AI 助手" in out and "知识库中没有找到相关依据" not in out, out[:120])

    # ② 无命中+时间：确定性时间
    out, _, stream_msgs, _ = run("现在几点了")
    check("②时间-确定性文案且零流式", "现在是" in out and "（星期" in out and not stream_msgs, out[:120])

    # ③ 无命中+正则+不调工具：NO_HIT_REPLY、零流式、no_evidence=1
    out, chat_calls, stream_msgs, appends = run("帮我查一下案件信息", tool_calls=None)
    check("③FC尝试一次且零流式", len(chat_calls) == 1 and not stream_msgs, f"chat={len(chat_calls)}")
    check("③兜底文案+no_evidence=1",
          "知识库中没有找到相关依据" in out and appends[-1][1]["context"]["no_evidence"] == 1)

    # ④ 无命中+正则+调工具：FC 流式（bug A 回归点：修复前 handled 结果被丢弃）
    out, chat_calls, stream_msgs, _ = run("查一下张三的案子",
                                          tool_calls=[{"name": "search_laws", "args": {"keyword": "张三"}}])
    check("④FC流式-走了fc_messages",
          len(stream_msgs) == 1 and "数据库查询结果" in stream_msgs[0][-1]["content"], out[:120])
    check("④FC流式-带工具命中引用卡片且非兜底",
          "case_1" in out and "知识库中没有找到相关依据" not in out)
    check("④FC探测输入-提问只出现一次（无完全重复）",
          sum(1 for m in chat_calls[0] if m.get("role") == "user"
              and m.get("content") == "查一下张三的案子") == 1)

    # ⑤ 有材料+正则+不调工具：材料正常回答（bug B 回归点：修复前输出 NO_HIT_REPLY）
    out, chat_calls, stream_msgs, _ = run("民间借贷的利息超过多少不受法律保护",
                                          context=MATERIAL, tool_calls=None)
    check("⑤材料回答-未被兜底吞", "回答片段" in out and "知识库中没有找到相关依据" not in out, out[:200])
    check("⑤材料注入prompt且引用卡片正常", MATERIAL in stream_msgs[0][-1]["content"] and CITATION["ref_id"] in out)
    check("⑤有材料时仍尝试一次FC(放宽后的预期)", len(chat_calls) == 1)
    # 有材料场景探测输入 = 包裹消息 + 裸问题（内容不同，有意保留的追问语义）
    check("⑤有材料探测输入=包裹+追问（保留行为）",
          sum(1 for m in chat_calls[0] if m.get("role") == "user") == 2)

    # ⑥ 有材料+无正则：不尝试 FC，直接材料流式
    out, chat_calls, stream_msgs, _ = run("劳务报酬纠纷可以主张利息吗", context=MATERIAL)
    check("⑥无正则-零FC调用", not chat_calls and len(stream_msgs) == 1)
    check("⑥材料回答-引用卡片正常", "回答片段" in out and CITATION["ref_id"] in out)

    print("\n全部 PASS（6 场景，FC 分支修复回归防线）")


if __name__ == "__main__":
    main()