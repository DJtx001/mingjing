"""LLM Provider 网关：云 API → Ollama 降级链"""
import json, urllib.request
from langchain_openai import ChatOpenAI
from app.core.config import config

class ProviderChain:
    def __init__(self):
        self._cloud_ok = None
        self._cloud_llm = None

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
        )
        return self._cloud_llm

    def _cloud_available(self):
        if self._cloud_ok is not None: return self._cloud_ok
        try:
            self._init_cloud()
            self._cloud_ok = True
        except Exception:
            self._cloud_ok = False
        return self._cloud_ok

    def _ollama_chat(self, messages, temperature=0.3):
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

    def chat(self, messages, temperature=0.3):
        cloud_err = None
        if self._cloud_available():
            try:
                llm = self._init_cloud()
                result = llm.invoke(messages)
                return result.content if hasattr(result, "content") else str(result)
            except Exception as e:
                self._cloud_ok = False
                cloud_err = f"{type(e).__name__}: {e}"
        text = self._ollama_chat(messages, temperature)
        if text is None:
            detail = f"；云端错误：{cloud_err}" if cloud_err else "（云端 Key 未配置或初始化失败）"
            raise RuntimeError("所有 LLM Provider 均不可用，Ollama 未运行" + detail)
        return text

    def stream(self, messages, temperature=0.3):
        """真流式：逐 token yield 文本片段。

        云端用 LangChain ChatOpenAI 的 .stream()（同步生成器，每个 chunk 是 AIMessageChunk）；
        Ollama 用 stream=True 逐行解析 NDJSON。
        调用方（assist.py 的同步生成器 + StreamingResponse）会在线程池里迭代，
        不阻塞事件循环。
        """
        if self._cloud_available():
            try:
                llm = self._init_cloud()
                for chunk in llm.stream(messages):
                    content = chunk.content if hasattr(chunk, "content") else ""
                    if content:
                        yield content
                return
            except Exception as e:
                self._cloud_ok = False

        # Ollama 流式：stream=True 时响应为 NDJSON，每行一个 {"response": "增量片段"}
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

provider = ProviderChain()
