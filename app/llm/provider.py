"""LLM Provider 网关：云 API → Ollama 降级链"""
import json, time, urllib.request
from datetime import datetime
from langchain_openai import ChatOpenAI
from app.core.config import config

_WEEKDAYS = "一二三四五六日"

class ProviderChain:
    _CLOUD_RETRY_AFTER = 60   # 云端失败后的冷却秒数:一次抖动不该导致进程内永久降级

    def __init__(self):
        self._cloud_ok = None
        self._cloud_llm = None
        self._cloud_fail_at = 0.0

    def _init_cloud(self):
        if self._cloud_llm: return self._cloud_llm
        if not config.CLOUD_API_KEY:
            raise RuntimeError("云端 API Key 未配置")
        self._cloud_llm = ChatOpenAI(
            base_url=config.CLOUD_BASE_URL,
            api_key=config.CLOUD_API_KEY,
            model=config.CLOUD_MODEL,
            temperature=0.3,
            max_retries=2,
            timeout=30,   # 单次请求 30s 上限（流式为 chunk 间隔）：防网络卡住时预热/对话无限挂起
        )
        return self._cloud_llm

    def _cloud_available(self):
        """云端可用性。失败后只冷却 _CLOUD_RETRY_AFTER 秒,到期自动重试,不永久熔断。"""
        if self._cloud_ok is True:
            return True
        if self._cloud_ok is False and time.time() - self._cloud_fail_at < self._CLOUD_RETRY_AFTER:
            return False
        try:
            self._init_cloud()
            self._cloud_ok = True
        except Exception:
            self._mark_cloud_down()
        return self._cloud_ok

    def _mark_cloud_down(self):
        """标记云端失败(进入冷却期),供调用失败时统一调用。"""
        self._cloud_ok = False
        self._cloud_fail_at = time.time()

    def _with_context(self, messages):
        """统一注入全局上下文（当前时间），所有 LLM 调用共享——新增调用点无需关心。

        模型没有内置时钟，不注入就会凭训练语料猜日期；星期几替它算好，
        LLM 自己推星期几常出错。返回新列表，不改调用方传入的 messages。
        """
        d = datetime.now()
        prefix = f"当前时间：{d:%Y年%m月%d日} 星期{_WEEKDAYS[d.weekday()]} {d:%H:%M}（北京时间）。"
        if messages and messages[0].get("role") == "system":
            return [{**messages[0], "content": prefix + "\n" + messages[0]["content"]}, *messages[1:]]
        return [{"role": "system", "content": prefix}, *messages]

    def _ollama_chat(self, messages, temperature=0.3):
        """本地降级兜底（Ollama）。注意：当前降级链已按需求关闭，保留以备恢复。"""
        prompt = "\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in messages)
        payload = {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            req = urllib.request.Request(
                config.OLLAMA_URL + "/api/generate",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8")).get("response", "")
        except Exception:
            return None

    def _ollama_stream(self, messages, temperature=0.3):
        """本地降级兜底的流式版（Ollama NDJSON 逐行解析）。

        当前降级链已按需求关闭（直连云端 API），本方法保留以备恢复：
        恢复方式见 stream() 的 except 分支注释。
        """
        prompt = "\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in messages)
        payload = {
            "model": config.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": temperature},
        }
        req = urllib.request.Request(
            config.OLLAMA_URL + "/api/generate",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            for line in resp:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line.decode("utf-8"))
                frag = data.get("response", "")
                if frag:
                    yield frag

    def chat(self, messages, temperature=0.3, tools=None):
        """非流式对话。若提供 tools（OpenAI tool schema 列表），返回含 tool_calls 的完整响应。"""
        messages = self._with_context(messages)
        if not self._cloud_available():
            raise RuntimeError("云端模型不可用：API Key 未配置或处于失败冷却中，请稍后重试")
        try:
            llm = self._init_cloud()
            if tools:
                llm = llm.bind_tools(tools)
                result = llm.invoke(messages)
                return result  # AIMessage，可能含 .tool_calls
            result = llm.invoke(messages)
            return result.content if hasattr(result, "content") else str(result)
        except Exception as e:
            self._mark_cloud_down()
            # 如需恢复本地兜底：改为 return self._ollama_chat(messages, temperature)
            raise RuntimeError(f"云端模型调用失败：{type(e).__name__}: {e}")

    def stream(self, messages, temperature=0.3):
        """真流式：逐 token yield 文本片段。

        云端用 LangChain ChatOpenAI 的 .stream()（同步生成器，每个 chunk 是 AIMessageChunk）；
        调用方（assist.py 的同步生成器 + StreamingResponse）会在线程池里迭代，不阻塞事件循环。
        降级兜底（Ollama）已按需求关闭：云端失败直接报错，原因随错误信息返回。
        """
        messages = self._with_context(messages)
        if not self._cloud_available():
            raise RuntimeError("云端模型不可用：API Key 未配置或处于失败冷却中，请稍后重试")
        try:
            llm = self._init_cloud()
            for chunk in llm.stream(messages):
                content = chunk.content if hasattr(chunk, "content") else ""
                if content:
                    yield content
        except Exception as e:
            self._mark_cloud_down()
            # 如需恢复本地兜底：此处加 yield from self._ollama_stream(messages, temperature) 后 return
            raise RuntimeError(f"云端模型调用失败：{type(e).__name__}: {e}")

provider = ProviderChain()
