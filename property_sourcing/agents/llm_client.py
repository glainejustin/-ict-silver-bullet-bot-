"""A tiny, swappable LLM wrapper.

With LLM_PROVIDER=none (the default, zero cost, no signup) everything still
works: every "agent" in this package has a rule-based fallback for when no
LLM is configured, so you get a fully functional automated pipeline on day
one. Add a free-tier key (e.g. Groq, which has a generous free tier) any
time to make the written analysis and outreach noticeably more human and
persuasive — no code changes required, just set LLM_PROVIDER + LLM_API_KEY.
"""
import logging

import config

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    pass


def available() -> bool:
    return config.LLM_PROVIDER != "none" and bool(config.LLM_API_KEY)


def complete(system_prompt: str, user_prompt: str, max_tokens: int = 500) -> str:
    """Return a text completion, or raise LLMUnavailable so callers can use
    their rule-based fallback instead of crashing the pipeline."""
    if not available():
        raise LLMUnavailable("No LLM configured (LLM_PROVIDER=none)")

    try:
        if config.LLM_PROVIDER == "groq":
            return _groq(system_prompt, user_prompt, max_tokens)
        if config.LLM_PROVIDER == "openai":
            return _openai(system_prompt, user_prompt, max_tokens)
        if config.LLM_PROVIDER == "anthropic":
            return _anthropic(system_prompt, user_prompt, max_tokens)
    except Exception as exc:  # noqa: BLE001 - we always want to fall back gracefully
        logger.warning("LLM call failed (%s), falling back to rule-based output: %s",
                        config.LLM_PROVIDER, exc)
        raise LLMUnavailable(str(exc)) from exc

    raise LLMUnavailable(f"Unknown LLM_PROVIDER={config.LLM_PROVIDER!r}")


def _groq(system_prompt, user_prompt, max_tokens):
    import requests

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
        json={
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _openai(system_prompt, user_prompt, max_tokens):
    import requests

    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
        json={
            "model": config.LLM_MODEL or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _anthropic(system_prompt, user_prompt, max_tokens):
    import requests

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": config.LLM_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": config.LLM_MODEL or "claude-3-5-haiku-20241022",
            "max_tokens": max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"].strip()
