"""Shared LLM client wrapper.

Every LLM/vision call in every phase MUST go through `llm_call()` so the
token ledger captures the whole run. When no API key is configured, the
wrapper returns None and callers fall back to deterministic heuristics,
recording a zero-cost row with the heuristic model name.
"""

from __future__ import annotations

import json
import os
from typing import Any

from code.evaluation import token_ledger

# Cost per 1M tokens (input, output) in USD — kept in sync with config.
# Imported lazily to avoid circulars; simple values here are fine.
_COSTS_1M = {
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openai", "gpt-4o"): (2.50, 10.00),
    ("anthropic", "claude-3-5-haiku"): (0.80, 4.00),
    ("anthropic", "claude-sonnet-4"): (3.00, 15.00),
}


def llm_call(
    prompt: str,
    *,
    system: str = "",
    model: str = "gpt-4o-mini",
    provider: str = "openai",
    max_tokens: int = 500,
    json_mode: bool = True,
    request_id: str = "",
    notes: str = "",
) -> dict[str, Any] | None:
    """Make a provider LLM call. Returns parsed JSON dict, or None.

    Returning None means "no LLM available / call failed" — callers must
    fall back to deterministic heuristics and must never guess silently.
    """
    api_key = _resolve_key(provider)
    if not api_key:
        # Deterministic fallback: log a zero-cost row so the ledger still
        # reflects that this call site executed.
        token_ledger.record(
            provider="deterministic",
            model="heuristic-v0",
            input_tokens=0,
            output_tokens=0,
            call_kind="fallback",
            request_id=request_id,
            notes=notes or "no api key configured; deterministic fallback",
        )
        return None

    try:
        raw = _dispatch(provider, model, api_key, system, prompt, max_tokens, json_mode)
    except Exception as exc:  # noqa: BLE001 — log and fall back
        token_ledger.record(
            provider=provider, model=model, call_kind="error",
            request_id=request_id, notes=f"call failed: {type(exc).__name__}",
        )
        return None

    # Rough token accounting: ~4 chars/token (documented approximation).
    in_tokens = max(1, (len(system) + len(prompt)) // 4)
    try:
        out_tokens = max(1, len(raw) // 4)
    except Exception:  # noqa: BLE001
        out_tokens = 1
    token_ledger.record(
        provider=provider, model=model,
        input_tokens=in_tokens, output_tokens=out_tokens,
        call_kind="llm", request_id=request_id, notes=notes,
    )

    if not json_mode:
        return {"text": raw}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to salvage a JSON object embedded in the response.
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _resolve_key(provider: str) -> str:
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY", "")
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_API_KEY", "")
    return ""


def _dispatch(
    provider: str,
    model: str,
    api_key: str,
    system: str,
    prompt: str,
    max_tokens: int,
    json_mode: bool,
) -> str:
    """Minimal REST calls using only stdlib — no SDK dependency required."""
    import urllib.request

    if provider == "openai":
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                *([{"role": "system", "content": system}] if system else []),
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

    if provider == "anthropic":
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["content"][0]["text"]

    raise ValueError(f"unknown provider: {provider}")
