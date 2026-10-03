"""OpenAI-compatible chat client (OpenAI, Azure-compatible gateways, or a local Ollama/vLLM server
via OPENAI_BASE_URL). Returns None when no LLM is configured so callers can degrade gracefully."""

from __future__ import annotations

import json
import logging
from typing import Optional, Protocol

from app.core.config import get_settings

log = logging.getLogger(__name__)


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, temperature: float = 0.1) -> str: ...

    def complete_json(self, system: str, user: str, schema: dict, schema_name: str) -> Optional[dict]: ...


class OpenAICompatibleLLM:
    def __init__(self):
        from openai import OpenAI

        s = get_settings()
        # bounded so a stuck local server degrades to the extractive path instead of hanging requests
        self.client = OpenAI(api_key=s.openai_api_key or "not-needed", base_url=s.openai_base_url or None,
                             timeout=s.llm_timeout_seconds, max_retries=1)
        self.model = s.llm_model
        self.name = f"openai-compatible:{self.model}"

    def complete(self, system: str, user: str, temperature: float = 0.1) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=900,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return resp.choices[0].message.content or ""

    def complete_json(self, system: str, user: str, schema: dict, schema_name: str) -> Optional[dict]:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=0,
                # grammar-constrained decoding can loop on whitespace; a cap guarantees termination
                max_tokens=1500,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema, "strict": True},
                },
            )
            return json.loads(resp.choices[0].message.content or "{}")
        except json.JSONDecodeError:
            log.warning("LLM returned malformed JSON; discarding")
            return None
        except Exception as e:  # network/provider errors must not break ingestion
            log.warning("LLM structured call failed: %s", type(e).__name__)
            return None


_override: Optional[LLM] = None
_instance: Optional[LLM] = None


def get_llm() -> Optional[LLM]:
    global _instance
    if _override is not None:
        return _override
    if not get_settings().llm_enabled:
        return None
    if _instance is None:
        _instance = OpenAICompatibleLLM()
    return _instance


def set_llm(llm: Optional[LLM]) -> None:
    global _override
    _override = llm
