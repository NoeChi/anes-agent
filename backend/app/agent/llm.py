"""Claude API 連線。沒有設定 API 金鑰時，系統自動改用離線模式（規則式回覆）。"""
from __future__ import annotations

import anthropic

from ..config import Settings

# 支援伺服器端 refusal fallback（fallbacks="default"）的模型
FALLBACK_MODELS = {"claude-opus-5"}
NO_EFFORT_MODELS = {"claude-haiku-4-5"}


class LLMUnavailable(RuntimeError):
    pass


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, LLMUnavailable):
        return str(exc)
    if isinstance(exc, anthropic.AuthenticationError):
        return "API 金鑰無效，請到「設定」重新輸入。"
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "此 API 金鑰沒有使用該模型的權限。"
    if isinstance(exc, anthropic.NotFoundError):
        return "找不到指定的模型，請到「設定」更換模型。"
    if isinstance(exc, anthropic.RateLimitError):
        return "AI 服務請求過於頻繁，請稍後再試。"
    if isinstance(exc, anthropic.BadRequestError):
        return f"AI 請求格式錯誤：{exc.message}"
    if isinstance(exc, anthropic.APIStatusError):
        return f"AI 服務暫時異常（{exc.status_code}），請稍後再試。"
    if isinstance(exc, anthropic.APIConnectionError):
        return "無法連線到 AI 服務，請檢查網路連線。"
    return f"AI 呼叫失敗：{type(exc).__name__}: {exc}"


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: anthropic.AsyncAnthropic | None = None
        self._key = ""
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return bool(self.settings.api_key()[0])

    def status(self) -> dict:
        key, source = self.settings.api_key()
        cfg = self.settings.section("llm")
        return {"available": bool(key), "source": source, "model": cfg["model"], "effort": cfg["effort"],
                "last_error": self.last_error}

    def client(self) -> anthropic.AsyncAnthropic:
        key, _ = self.settings.api_key()
        if not key:
            raise LLMUnavailable("尚未設定 Claude API 金鑰（目前為離線模式）。")
        if self._client is None or key != self._key:
            self._client = anthropic.AsyncAnthropic(api_key=key, max_retries=2, timeout=180.0)
            self._key = key
        return self._client

    async def create(self, *, system, messages, tools=None, max_tokens: int = 16000, effort: str | None = None):
        cfg = self.settings.section("llm")
        model = cfg["model"]
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
            kwargs["output_config"] = {"effort": effort or cfg["effort"]}
        betas = []
        if model in FALLBACK_MODELS:
            betas.append("server-side-fallback-2026-07-01")
            kwargs["fallbacks"] = "default"
        try:
            response = await self.client().beta.messages.create(betas=betas, **kwargs)
        except Exception as exc:
            self.last_error = friendly_error(exc)
            raise
        self.last_error = None
        return response

    async def test(self) -> dict:
        response = await self.create(
            system="你是連線測試助手。",
            messages=[{"role": "user", "content": "請只回覆「連線成功」四個字。"}],
            max_tokens=1024,
            effort="low",
        )
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return {"ok": True, "model": response.model, "reply": text}
