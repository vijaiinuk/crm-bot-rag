"""The LiteLLM adapter, with LiteLLM mocked: no network, no key needed."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from pydantic import SecretStr

from chatbot.adapters.litellm_client import LiteLLMClient
from chatbot.config import Settings
from chatbot.models_config import ModelsConfig, ModelsConfigError, load_models_config
from chatbot.ports.llm import LLMError, Message

REPO_CONFIG = Path(__file__).parents[2] / "config" / "models.yaml"
KEY = SecretStr("sk-or-test")
PROMPT = [Message("system", "be brief"), Message("user", "hi")]


def config(**route: Any) -> ModelsConfig:
    return ModelsConfig.model_validate(
        {
            "providers": {"openrouter": {"api_base": "https://openrouter.test/v1"}},
            "models": {
                "docgen": {
                    "provider": "openrouter",
                    "model_id": "anthropic/claude-x-1",
                    "route": {"order": ["anthropic"], "allow_fallbacks": False, **route},
                    "params": {"temperature": 0.5, "max_tokens": 100},
                }
            },
        }
    )


def fake_response(text: str = "hello", provider: str | None = "Anthropic") -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=3,
            prompt_tokens_details=SimpleNamespace(cached_tokens=8),
        ),
        provider=provider,
    )


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    response = fake_response()

    async def acompletion(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return response

    monkeypatch.setattr(litellm, "acompletion", acompletion)
    return seen


def patch_response(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    async def acompletion(**_: Any) -> Any:
        return response

    monkeypatch.setattr(litellm, "acompletion", acompletion)


# --- the request ----------------------------------------------------------------------


async def test_request_uses_pinned_model_route_and_explicit_key(
    calls: list[dict[str, Any]],
) -> None:
    await LiteLLMClient(config(), openrouter_api_key=KEY).complete(PROMPT, role="docgen")
    (call,) = calls
    assert call["model"] == "openrouter/anthropic/claude-x-1"
    assert call["api_key"] == "sk-or-test", "passed explicitly, not via os.environ"
    assert call["api_base"] == "https://openrouter.test/v1"
    assert call["extra_body"] == {"provider": {"order": ["anthropic"], "allow_fallbacks": False}}
    assert call["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]
    assert (call["temperature"], call["max_tokens"]) == (0.5, 100)


async def test_completion_carries_trace_fields(calls: list[dict[str, Any]]) -> None:
    c = await LiteLLMClient(config(), openrouter_api_key=KEY).complete(PROMPT, role="docgen")
    assert c.text == "hello"
    assert c.model_id == "anthropic/claude-x-1"
    assert c.provider == "Anthropic"
    assert (c.usage.input_tokens, c.usage.output_tokens, c.usage.cached_input_tokens) == (12, 3, 8)
    assert c.latency_ms >= 0


# --- fail closed ------------------------------------------------------------------------


def test_missing_key_fails_at_construction() -> None:
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        LiteLLMClient(config(), openrouter_api_key=None)


async def test_unknown_role_is_an_error(calls: list[dict[str, Any]]) -> None:
    with pytest.raises(LLMError, match="no model configured for role 'judge'"):
        await LiteLLMClient(config(), openrouter_api_key=KEY).complete(PROMPT, role="judge")
    assert not calls


async def test_wrong_served_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_response(monkeypatch, fake_response(provider="SomeReseller"))
    with pytest.raises(LLMError, match="served by 'SomeReseller', not the pinned 'anthropic'"):
        await LiteLLMClient(config(), openrouter_api_key=KEY).complete(PROMPT, role="docgen")


async def test_empty_reply_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_response(monkeypatch, fake_response(text="  "))
    with pytest.raises(LLMError, match="returned no text"):
        await LiteLLMClient(config(), openrouter_api_key=KEY).complete(PROMPT, role="docgen")


async def test_litellm_errors_become_llm_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**_: Any) -> Any:
        raise RuntimeError("rate limited")

    monkeypatch.setattr(litellm, "acompletion", boom)
    with pytest.raises(LLMError, match="rate limited"):
        await LiteLLMClient(config(), openrouter_api_key=KEY).complete(PROMPT, role="docgen")


# --- config ---------------------------------------------------------------------------


def test_repo_config_loads_and_pins_every_role() -> None:
    cfg = load_models_config(REPO_CONFIG)
    assert "docgen" in cfg.models
    for m in cfg.models.values():
        assert not m.route.allow_fallbacks and len(m.route.order) == 1


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"model_id": "anthropic/claude-latest"}, "not a pinned model version"),
        ({"model_id": "openrouter/auto"}, "not a pinned model version"),
        ({"route": {"order": ["anthropic"], "allow_fallbacks": True}}, "fallbacks must be off"),
        ({"route": {"order": ["a", "b"], "allow_fallbacks": False}}, "at most 1 item"),
        ({"provider": "bedrock"}, "unknown provider 'bedrock'"),
    ],
)
def test_bad_model_config_is_rejected(tmp_path: Path, change: dict[str, Any], reason: str) -> None:
    import yaml

    raw = yaml.safe_load(REPO_CONFIG.read_text())
    raw["models"]["docgen"].update(change)
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump(raw))
    with pytest.raises(ModelsConfigError, match=reason):
        load_models_config(p)


# --- settings -------------------------------------------------------------------------


def test_key_is_read_from_openrouter_api_key_and_kept_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-from-env")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.openrouter_api_key is not None
    assert s.openrouter_api_key.get_secret_value() == "sk-or-from-env"
    assert "sk-or-from-env" not in repr(s)
