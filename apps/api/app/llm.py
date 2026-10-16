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


class LlamaCppLLM:
    """Local open model through llama-cpp-python (GGUF). Needs LLAMA_MODEL_PATH; no network, no key."""

    def __init__(self, path: str | None = None, max_tokens: int = 400, n_ctx: int = 8192):
        from llama_cpp import (
            Llama,  # lazy: only required when this provider is selected
        )
        self.llm = Llama(model_path=path or os.environ["LLAMA_MODEL_PATH"], n_ctx=n_ctx, verbose=False,
                         n_threads=int(os.environ.get("LLAMA_THREADS", "0")) or None)
        self.max_tokens = max_tokens

    def complete(self, system: str, prompt: str) -> str:
        r = self.llm.create_chat_completion(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens=self.max_tokens, temperature=0.0)
        return r["choices"][0]["message"]["content"] or ""


def get_llm() -> LLM:
    provider = os.environ.get("LLM_PROVIDER", "none")
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "llamacpp":
        return LlamaCppLLM()
    raise NoLLMConfigured("set LLM_PROVIDER (supported: anthropic, llamacpp) and its credentials")
