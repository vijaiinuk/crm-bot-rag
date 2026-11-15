"""One tiny live call per model role: `make llm-smoke` or `make llm-smoke ROLE=docgen`.

Checks the key, the pinned model ID and the pinned provider. Costs a fraction of a cent.
"""

import argparse
import asyncio
import sys

from chatbot.adapters.litellm_client import LiteLLMClient
from chatbot.config import Settings
from chatbot.models_config import load_models_config
from chatbot.ports.llm import LLMError, Message

PROMPT = [Message("user", "Reply with exactly the word: ok")]


async def smoke(roles: list[str] | None) -> int:
    settings = Settings()
    config = load_models_config(settings.models_path)
    try:
        client = LiteLLMClient(config, openrouter_api_key=settings.openrouter_api_key)
    except LLMError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    failed = 0
    for role in roles or list(config.models):
        try:
            c = await client.complete(PROMPT, role=role)
        except LLMError as e:
            print(f"FAIL {role}: {e}", file=sys.stderr)
            failed += 1
            continue
        print(
            f"ok {role}: {c.model_id} via {c.provider}, {c.latency_ms} ms, "
            f"{c.usage.input_tokens} in / {c.usage.output_tokens} out tokens, "
            f"reply {c.text.strip()[:40]!r}"
        )
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", action="append", help="model role; default: all roles")
    return asyncio.run(smoke(parser.parse_args().role))


if __name__ == "__main__":
    sys.exit(main())
