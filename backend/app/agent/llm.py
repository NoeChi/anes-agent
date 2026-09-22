"""LLM 連線：支援 Anthropic Claude 與 OpenAI；沒有設定金鑰時，系統自動改用離線模式。

對外只暴露一種回應形狀（沿用 Anthropic 的 content 區塊格式），OpenAI 的請求與回應都在這裡轉換：

    response.content      區塊清單；區塊有 .type（text / tool_use）
                          text 區塊有 .text；tool_use 區塊有 .id / .name / .input（dict）
    response.stop_reason  tool_use / end_turn / max_tokens / refusal / pause_turn
    response.model        實際回應的模型代號

所以代理迴圈（chat.py）、查房摘要（rounds.py）與工具定義（toolbox.py）都不需要知道背後是哪一家。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import openai

from ..config import PROVIDERS, Settings

# 支援伺服器端 refusal fallback（fallbacks="default"）的 Anthropic 模型
FALLBACK_MODELS = {"claude-opus-5"}
NO_EFFORT_MODELS = {"claude-haiku-4-5"}

# OpenAI 的 finish_reason → 內部的 stop_reason
_FINISH_REASON = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}
# 列出模型時略過的非對話模型
_SKIP_MODELS = ("embedding", "tts", "whisper", "dall-e", "image", "audio", "moderation", "realtime", "transcribe",
                "search", "sora", "codex", "computer-use")


class LLMUnavailable(RuntimeError):
    pass


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, LLMUnavailable):
        return str(exc)
    if isinstance(exc, (anthropic.AuthenticationError, openai.AuthenticationError)):
        return "API 金鑰無效，請到「設定」重新輸入。"
    if isinstance(exc, (anthropic.PermissionDeniedError, openai.PermissionDeniedError)):
        return "此 API 金鑰沒有使用該模型的權限。"
    if isinstance(exc, (anthropic.NotFoundError, openai.NotFoundError)):
        return "找不到指定的模型，請到「設定」更換模型。"
    if isinstance(exc, (anthropic.RateLimitError, openai.RateLimitError)):
        return "AI 服務請求過於頻繁，請稍後再試。"
    if isinstance(exc, (anthropic.BadRequestError, openai.BadRequestError)):
        return f"AI 請求格式錯誤：{getattr(exc, 'message', exc)}"
    if isinstance(exc, (anthropic.APIStatusError, openai.APIStatusError)):
        return f"AI 服務暫時異常（{exc.status_code}），請稍後再試。"
    if isinstance(exc, (anthropic.APIConnectionError, openai.APIConnectionError)):
        return "無法連線到 AI 服務，請檢查網路連線。"
    return f"AI 呼叫失敗：{type(exc).__name__}: {exc}"


def _attr(block, name: str, default=None):
    """區塊可能是 SDK 物件、SimpleNamespace 或 dict。"""
    return block.get(name, default) if isinstance(block, dict) else getattr(block, name, default)


def _to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    """把 Anthropic 形狀的對話歷史轉成 OpenAI 的 messages。"""
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "".join(_attr(b, "text", "") or "" for b in content if _attr(b, "type") == "text")
            calls = [{"id": _attr(b, "id"), "type": "function",
                      "function": {"name": _attr(b, "name"),
                                   "arguments": json.dumps(_attr(b, "input") or {}, ensure_ascii=False)}}
                     for b in content if _attr(b, "type") == "tool_use"]
            entry: dict = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        # 工具結果：Anthropic 包在一則 user 訊息裡，OpenAI 則是每個結果各一則 tool 訊息
        for block in content:
            kind = _attr(block, "type")
            if kind == "tool_result":
                out.append({"role": "tool", "tool_call_id": _attr(block, "tool_use_id"),
                            "content": str(_attr(block, "content", ""))})
            elif kind == "text":
                out.append({"role": "user", "content": _attr(block, "text", "")})
    return out


def _from_openai(response) -> SimpleNamespace:
    """把 OpenAI 的回應轉成內部統一的形狀。"""
    choice = response.choices[0]
    message = choice.message
    blocks: list[SimpleNamespace] = []
    if getattr(message, "content", None):
        blocks.append(SimpleNamespace(type="text", text=message.content))
    for call in getattr(message, "tool_calls", None) or []:
        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        blocks.append(SimpleNamespace(type="tool_use", id=call.id, name=call.function.name, input=args))
    stop_reason = _FINISH_REASON.get(choice.finish_reason, "end_turn")
    if getattr(message, "refusal", None):
        blocks.append(SimpleNamespace(type="text", text=message.refusal))
        stop_reason = "refusal"
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, model=response.model)


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._clients: dict[str, object] = {}
        self._keys: dict[str, str] = {}
        self._no_effort: set[str] = set()  # 實測不支援 reasoning_effort 的 OpenAI 模型
        self.last_error: str | None = None

    @property
    def provider(self) -> str:
        return self.settings.provider()

    @property
    def available(self) -> bool:
        return bool(self.settings.api_key()[0])

    def status(self) -> dict:
        provider = self.provider
        key, source = self.settings.api_key(provider)
        cfg = self.settings.section("llm")
        return {"available": bool(key), "source": source, "provider": provider,
                "provider_label": PROVIDERS[provider]["label"], "model": self.settings.model(provider),
                "effort": cfg["effort"], "last_error": self.last_error}

    def client(self, provider: str | None = None):
        provider = provider or self.provider
        key, _ = self.settings.api_key(provider)
        if not key:
            raise LLMUnavailable(f"尚未設定 {PROVIDERS[provider]['label']} 的 API 金鑰（目前為離線模式）。")
        if self._clients.get(provider) is None or self._keys.get(provider) != key:
            if provider == "openai":
                self._clients[provider] = openai.AsyncOpenAI(api_key=key, max_retries=2, timeout=180.0)
            else:
                self._clients[provider] = anthropic.AsyncAnthropic(api_key=key, max_retries=2, timeout=180.0)
            self._keys[provider] = key
        return self._clients[provider]

    async def create(self, *, system, messages, tools=None, max_tokens: int = 16000, effort: str | None = None):
        provider = self.provider
        cfg = self.settings.section("llm")
        model = self.settings.model(provider)
        effort = effort or cfg["effort"]
        client = self.client(provider)
        try:
            if provider == "openai":
                if not model:
                    raise LLMUnavailable("尚未選擇 OpenAI 模型，請到「設定」選擇。")
                response = await self._create_openai(client, model, system, messages, tools, max_tokens, effort)
            else:
                response = await self._create_anthropic(client, model, system, messages, tools, max_tokens, effort)
        except Exception as exc:
            self.last_error = friendly_error(exc)
            raise
        self.last_error = None
        return response

    async def _create_anthropic(self, client, model, system, messages, tools, max_tokens, effort):
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            kwargs["tools"] = tools
        if model not in NO_EFFORT_MODELS:
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {"effort": effort}
        betas = []
        if model in FALLBACK_MODELS:
            betas.append("server-side-fallback-2026-07-01")
            kwargs["fallbacks"] = "default"
        return await client.beta.messages.create(betas=betas, **kwargs)

    async def _create_openai(self, client, model, system, messages, tools, max_tokens, effort):
        kwargs: dict = {
            "model": model,
            "messages": _to_openai_messages(system, messages),
            "max_completion_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = [{"type": "function",
                                "function": {"name": t["name"], "description": t.get("description", ""),
                                             "parameters": t["input_schema"]}}
                               for t in tools]
        if effort and model not in self._no_effort:
            kwargs["reasoning_effort"] = effort
        try:
            response = await client.chat.completions.create(**kwargs)
        except openai.BadRequestError as exc:
            # 一般（非推理）模型不吃 reasoning_effort：拿掉重試一次，並記住這個模型
            if "reasoning_effort" in kwargs and "reasoning_effort" in str(exc):
                self._no_effort.add(model)
                kwargs.pop("reasoning_effort")
                response = await client.chat.completions.create(**kwargs)
            else:
                raise
        return _from_openai(response)

    async def list_models(self, provider: str | None = None) -> list[dict]:
        """向供應商查詢帳號實際可用的模型；查不到時退回內建清單。"""
        provider = provider or self.provider
        static = PROVIDERS[provider]["models"]
        try:
            page = await self.client(provider).models.list()
            ids = [m.id for m in page.data]
        except LLMUnavailable:
            raise
        except Exception as exc:
            self.last_error = friendly_error(exc)
            if static:
                return list(static)
            raise
        if provider == "openai":
            ids = [i for i in ids if not any(skip in i for skip in _SKIP_MODELS)]
        labels = {m["id"]: m["label"] for m in static}
        return [{"id": i, "label": labels.get(i, i)} for i in sorted(ids)]

    async def test(self) -> dict:
        response = await self.create(
            system="你是連線測試助手。",
            messages=[{"role": "user", "content": "請只回覆「連線成功」四個字。"}],
            max_tokens=1024,
            effort="low",
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return {"ok": True, "model": response.model, "reply": text}
