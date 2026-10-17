"""Provider-agnostic LLM gateway. The pipeline depends only on `LLM.complete`."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.redact import redact


class LLMCapExceeded(RuntimeError):
    """The tenant has used its daily allowance (LLM_DAILY_CHAR_CAP characters, prompts and answers together)."""


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
        self.id = f"anthropic:{self.model}"
        self.max_tokens = max_tokens

    def complete(self, system: str, prompt: str) -> str:
        r = self.client.messages.create(model=self.model, max_tokens=self.max_tokens, system=system,
                                        messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")


class LlamaCppLLM:
    """Local open model through llama-cpp-python (GGUF). Needs LLAMA_MODEL_PATH; no network, no key."""

    def __init__(self, path: str | None = None, max_tokens: int = 600, n_ctx: int = 8192):
        from llama_cpp import (
            Llama,  # lazy: only required when this provider is selected
        )
        model_path = path or os.environ["LLAMA_MODEL_PATH"]
        self.llm = Llama(model_path=model_path, n_ctx=n_ctx, verbose=False,
                         n_threads=int(os.environ.get("LLAMA_THREADS", "0")) or None)
        self.id = f"llamacpp:{os.path.basename(model_path)}"
        self.max_tokens = max_tokens

    def complete(self, system: str, prompt: str) -> str:
        r = self.llm.create_chat_completion(
            # Some chat templates (Gemma) reject a system role, so the instructions go in the user turn.
            messages=[{"role": "user", "content": f"{system}\n\n{prompt}"}],
            max_tokens=self.max_tokens, temperature=0.0, response_format={"type": "json_object"})
        return r["choices"][0]["message"]["content"] or ""


class RedactingLLM:
    """Wraps an external provider so personal identifiers in document text never leave the host.
    Local models never leave the host, so they are not wrapped."""

    def __init__(self, inner: LLM):
        self.inner = inner

    def complete(self, system: str, prompt: str) -> str:
        return self.inner.complete(system, redact(prompt))


class CappedLLM:
    """Counts each tenant's characters sent and received per UTC day, and refuses calls past the cap.
    Characters are the unit because providers bill tokens, and a token count is not known before the call.
    LLM_DAILY_CHAR_CAP=0 (the default) means no cap; usage is still recorded."""

    def __init__(self, inner: LLM, db: Session, tenant_id: str):
        self.inner, self.db, self.tenant_id = inner, db, tenant_id

    def _row(self):
        from app.models import LlmUsage

        day = datetime.now(UTC).date().isoformat()
        row = self.db.query(LlmUsage).filter_by(tenant_id=self.tenant_id, day=day).first()
        if row is None:
            row = LlmUsage(tenant_id=self.tenant_id, day=day, calls=0, chars=0)
            self.db.add(row)
        return row

    def complete(self, system: str, prompt: str) -> str:
        cap = int(os.environ.get("LLM_DAILY_CHAR_CAP", "0") or 0)
        row = self._row()
        sent = len(system) + len(prompt)
        if cap and row.chars + sent > cap:
            raise LLMCapExceeded(f"daily LLM allowance used up for this tenant ({cap} characters)")
        out = self.inner.complete(system, prompt)
        row.calls += 1
        row.chars += sent + len(out)
        self.db.commit()
        return out


class FallbackLLM:
    """Uses the primary provider; if it raises (outage, timeout, bad credentials), asks the secondary instead.
    The secondary is built on first use, so a fallback that is never needed is never set up."""

    def __init__(self, primary: LLM, secondary_factory, secondary_id: str = "secondary"):
        self.primary, self.secondary_factory, self.secondary_id = primary, secondary_factory, secondary_id
        self.last_served = ""  # the id of the provider that answered the last call

    def complete(self, system: str, prompt: str) -> str:
        try:
            out = self.primary.complete(system, prompt)
            self.last_served = llm_id(self.primary)
            return out
        except LLMCapExceeded:
            raise  # the tenant is over its allowance; a second provider would only spend it again
        except Exception:  # noqa: BLE001 - any provider failure is a reason to try the secondary
            secondary = self.secondary_factory()
            out = secondary.complete(system, prompt)
            self.last_served = llm_id(secondary)
            return out


def llm_id(llm: LLM) -> str:
    """Provider and model behind an LLM. A fallback shows both, so its answers are not filed under the primary."""
    if isinstance(llm, (CappedLLM, RedactingLLM)):
        return llm_id(llm.inner)
    if isinstance(llm, FallbackLLM):
        return f"{llm_id(llm.primary)}>{llm.secondary_id}"
    return getattr(llm, "id", type(llm).__name__)


def served_by(llm: LLM) -> str:
    """The provider and model that answered the last call. Differs from llm_id only when a fallback answered."""
    while isinstance(llm, (CappedLLM, RedactingLLM)):
        llm = llm.inner
    if isinstance(llm, FallbackLLM):
        return llm.last_served or llm_id(llm)
    return llm_id(llm)


def _provider(name: str) -> LLM:
    if name == "anthropic":
        return RedactingLLM(AnthropicLLM())
    if name == "llamacpp":
        return LlamaCppLLM()
    raise NoLLMConfigured("set LLM_PROVIDER (supported: anthropic, llamacpp) and its credentials")


def get_llm(db: Session | None = None, tenant_id: str | None = None) -> LLM:
    provider = os.environ.get("LLM_PROVIDER", "none")
    fallback = os.environ.get("LLM_FALLBACK_PROVIDER", "")
    llm: LLM = _provider(provider)
    if fallback and fallback != provider:
        llm = FallbackLLM(llm, lambda: _provider(fallback), secondary_id=fallback)
    # Local models are metered too, so the cap counts every call the tenant makes.
    return CappedLLM(llm, db, tenant_id) if db is not None and tenant_id is not None else llm
