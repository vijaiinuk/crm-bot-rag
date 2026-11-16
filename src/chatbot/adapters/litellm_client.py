"""LLMClient over LiteLLM. OpenRouter in development, Bedrock later (ADR-0002)."""

import time
from collections.abc import Sequence
from typing import Any

import litellm
from pydantic import SecretStr

from chatbot.adapters.rate_limit import RateLimiter
from chatbot.models_config import ModelsConfig
from chatbot.ports.llm import Completion, LLMError, Message, Usage

NUM_RETRIES = 3  # LiteLLM retries rate limits and 5xx with backoff

# LiteLLM prints a "Give Feedback / Get Help" banner on every error, which
# buries the actual message. Errors reach callers as LLMError instead.
litellm.suppress_debug_info = True


class LiteLLMClient:
    def __init__(self, config: ModelsConfig, *, openrouter_api_key: SecretStr | None) -> None:
        uses_openrouter = any(m.provider == "openrouter" for m in config.models.values())
        if uses_openrouter and not openrouter_api_key:
            raise LLMError("OPENROUTER_API_KEY is not set (put it in .env)")
        self._config = config
        self._keys = {"openrouter": openrouter_api_key}
        self._limiters = {
            role: RateLimiter(m.rpm) for role, m in config.models.items() if m.rpm is not None
        }

    async def complete(self, messages: Sequence[Message], *, role: str) -> Completion:
        try:
            m = self._config.models[role]
        except KeyError:
            raise LLMError(f"no model configured for role {role!r}") from None
        key = self._keys.get(m.provider)
        expected = m.route.order[0]

        if limiter := self._limiters.get(role):
            await limiter.acquire()
        started = time.monotonic()
        try:
            response: Any = await litellm.acompletion(
                model=f"{m.provider}/{m.model_id}",
                messages=[{"role": msg.role, "content": msg.content} for msg in messages],
                api_base=self._config.providers[m.provider].api_base,
                api_key=key.get_secret_value() if key else None,
                temperature=m.params.temperature,
                max_tokens=m.params.max_tokens,
                extra_body={"provider": m.route.model_dump()},
                num_retries=NUM_RETRIES,
            )
        except Exception as e:  # LiteLLM raises many types; callers need one
            raise LLMError(f"{role} ({m.model_id}) failed: {e}") from e
        latency_ms = int((time.monotonic() - started) * 1000)

        served = served_provider(response)
        if served is not None and served.lower() != expected.lower():
            raise LLMError(f"{role} was served by {served!r}, not the pinned {expected!r}")

        text = (response.choices[0].message.content or "") if response.choices else ""
        if not text.strip():
            raise LLMError(f"{role} ({m.model_id}) returned no text")
        return Completion(
            text=text,
            model_id=m.model_id,
            provider=served or expected,
            usage=usage_of(response),
            latency_ms=latency_ms,
        )


def served_provider(response: Any) -> str | None:
    """OpenRouter names the backend that served the call in a `provider` field."""
    value = getattr(response, "provider", None)
    if value is None and isinstance(getattr(response, "model_extra", None), dict):
        value = response.model_extra.get("provider")
    return value if isinstance(value, str) else None


def usage_of(response: Any) -> Usage:
    u = getattr(response, "usage", None)
    details = getattr(u, "prompt_tokens_details", None)
    return Usage(
        input_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
        output_tokens=int(getattr(u, "completion_tokens", 0) or 0),
        cached_input_tokens=int(getattr(details, "cached_tokens", 0) or 0),
    )
