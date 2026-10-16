"""Provider-agnostic LLM gateway. The pipeline depends only on `LLM.complete`."""
from __future__ import annotations

import os
from typing import Protocol


class LLM(Protocol):
    def complete(self, system: str, prompt: str) -> str: ...


class NoLLMConfigured(RuntimeError):
    pass


class AnthropicLLM:
    """Thin adapter. Needs ANTHROPIC_API_KEY and ANTHROPIC_MODEL (no model id is hard-coded)."""

    def __init__(self, model: str | None = None, max_tokens: int = 2000):
        import anthropic  # lazy: only required when this provider is selected
        self.client = anthropic.Anthropic()
        self.model = model or os.environ["ANTHROPIC_MODEL"]
        self.max_tokens = max_tokens

    def complete(self, system: str, prompt: str) -> str:
        r = self.client.messages.create(model=self.model, max_tokens=self.max_tokens, system=system,
                                        messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")


def get_llm() -> LLM:
    provider = os.environ.get("LLM_PROVIDER", "none")
    if provider == "anthropic":
        return AnthropicLLM()
    raise NoLLMConfigured("set LLM_PROVIDER (supported: anthropic) and its credentials")
