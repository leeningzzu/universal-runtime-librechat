from __future__ import annotations

import os
from typing import Any

from universal_runtime.core.models import ModelProfile


class DeepSeekAgentFactory:
    """Lazily imports Microsoft Agent Framework so deterministic commands can run without it."""

    def __init__(self, profile: ModelProfile):
        self.profile = profile

    def create_agent(self, *, agent_id: str, name: str, instructions: str):
        api_key = os.getenv('DEEPSEEK_API_KEY')
        if not api_key:
            raise RuntimeError('DEEPSEEK_API_KEY is not set.')
        base_url = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
        try:
            from agent_framework import Agent
            from agent_framework.openai import OpenAIChatCompletionClient
        except ImportError as exc:
            raise RuntimeError('agent-framework is not installed. Run bootstrap_windows.ps1.') from exc

        options: dict[str, Any] = {
            'max_tokens': self.profile.max_tokens,
            'response_format': {'type': 'json_object'},
            'reasoning_effort': self.profile.reasoning_effort,
            # DeepSeek's ``thinking`` field is provider-specific.  The
            # OpenAI-compatible SDK accepts it via ``extra_body`` rather
            # than as a top-level Chat Completions argument.
            'extra_body': {'thinking': {'type': self.profile.thinking}},
        }
        return Agent(
            id=agent_id,
            name=name,
            client=OpenAIChatCompletionClient(
                base_url=base_url,
                api_key=api_key,
                model=self.profile.model,
            ),
            instructions=instructions,
            default_options=options,
        )

# --- Formal Job transport boundary (S1 R001) ---

def _formal_canonical_sha256(value: object) -> str:
    import hashlib as _hashlib
    import json as _json
    return _hashlib.sha256(
        _json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _formal_loopback_proxy_url(proxy_url: str) -> str:
    from urllib.parse import urlsplit as _urlsplit

    if not isinstance(proxy_url, str) or not proxy_url:
        raise RuntimeError("formal proxy URL must be non-empty text")
    parsed = _urlsplit(proxy_url)
    if parsed.scheme != "http":
        raise RuntimeError("formal loopback proxy must use http://")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError("formal loopback proxy must not contain credentials")
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError("formal proxy must be loopback-only")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("formal loopback proxy has invalid port") from exc
    if port is None or port < 1 or port > 65535:
        raise RuntimeError("formal loopback proxy requires a valid port")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise RuntimeError("formal loopback proxy must not contain path/query/fragment")
    return proxy_url.rstrip("/")


def formal_loopback_proxy_config_sha256(proxy_url: str) -> str:
    normalized = _formal_loopback_proxy_url(proxy_url)
    return _formal_canonical_sha256(
        {"proxy_mode": "EXPLICIT_LOOPBACK_ONLY", "proxy_url": normalized}
    )


def issue_formal_deepseek_chat_completion(
    provider_execution_config,
    model_resolution,
    credential_value: str,
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    reasoning_effort: str,
    thinking: str,
    explicit_loopback_proxy_url: str | None = None,
    timeout_seconds: float = 180.0,
):
    """Issue exactly one first-slice DeepSeek request from an exact Runtime config.

    This is the formal Job path only. It never reads endpoint/model/credential facts from
    ambient environment. The ordinary DeepSeekAgentFactory above remains unchanged.
    """

    from universal_runtime.core.formal_model_live_composition import ProviderAttemptResult
    from universal_runtime.core.model_catalog import ResolvedModelExecution
    from universal_runtime.core.provider_execution_config import (
        ProviderExecutionConfig,
        direct_proxy_config_sha256,
    )

    if not isinstance(provider_execution_config, ProviderExecutionConfig):
        raise RuntimeError("formal DeepSeek transport requires ProviderExecutionConfig")
    if not isinstance(model_resolution, ResolvedModelExecution):
        raise RuntimeError("formal DeepSeek transport requires ResolvedModelExecution")
    config = provider_execution_config
    resolution = model_resolution
    try:
        config.assert_matches_resolution(
            provider=resolution.provider,
            resolved_model_entry_id=resolution.model_entry_id,
            model_resolution_sha256=resolution.resolution_sha256,
        )
    except BaseException as exc:
        raise RuntimeError(
            "formal DeepSeek transport model resolution/config mismatch"
        ) from exc
    if resolution.provider != "deepseek" or config.provider != "deepseek":
        raise RuntimeError("formal DeepSeek transport provider mismatch")
    if config.endpoint_origin.rstrip("/") != "https://api.deepseek.com":
        raise RuntimeError("formal DeepSeek first slice requires exact official endpoint origin")
    if config.api_route != "/chat/completions":
        raise RuntimeError("formal DeepSeek first slice requires /chat/completions")
    if config.http_method != "POST" or config.stream is not False:
        raise RuntimeError("formal DeepSeek first slice requires POST and stream=false")
    if config.transport_retries_max != 0 or config.trust_env is not False:
        raise RuntimeError("formal DeepSeek transport requires retry=0 and trust_env=false")
    if not isinstance(resolution.model, str) or not resolution.model:
        raise RuntimeError("formal DeepSeek resolved model must be non-empty")
    if not isinstance(credential_value, str) or not credential_value:
        raise RuntimeError("formal DeepSeek credential value is missing")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("formal DeepSeek messages must be a non-empty list")
    normalized_messages: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise RuntimeError("formal DeepSeek message must contain exact role/content fields")
        role = item.get("role")
        content = item.get("content")
        if role not in ("system", "user", "assistant"):
            raise RuntimeError("formal DeepSeek message role is invalid")
        if not isinstance(content, str) or not content:
            raise RuntimeError("formal DeepSeek message content must be non-empty")
        normalized_messages.append({"role": role, "content": content})
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise RuntimeError("formal DeepSeek max_tokens must be positive integer")
    if reasoning_effort not in ("low", "high", "max"):
        raise RuntimeError("formal DeepSeek reasoning_effort invalid")
    if thinking not in ("enabled", "disabled"):
        raise RuntimeError("formal DeepSeek thinking invalid")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise RuntimeError("formal DeepSeek timeout must be positive")

    proxy_url: str | None
    if config.proxy_mode == "DIRECT":
        if explicit_loopback_proxy_url is not None:
            raise RuntimeError("DIRECT formal transport forbids explicit proxy URL")
        if config.proxy_config_sha256 != direct_proxy_config_sha256():
            raise RuntimeError("DIRECT proxy config SHA mismatch")
        proxy_url = None
    elif config.proxy_mode == "EXPLICIT_LOOPBACK_ONLY":
        if explicit_loopback_proxy_url is None:
            raise RuntimeError("explicit loopback proxy URL is required")
        proxy_url = _formal_loopback_proxy_url(explicit_loopback_proxy_url)
        if formal_loopback_proxy_config_sha256(proxy_url) != config.proxy_config_sha256:
            raise RuntimeError("formal loopback proxy config SHA mismatch")
    else:
        raise RuntimeError("unsupported formal DeepSeek proxy mode")

    request_payload = {
        "model": resolution.model,
        "messages": normalized_messages,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
        "stream": False,
        "extra_body": {"thinking": {"type": thinking}},
    }
    request_payload_sha256 = _formal_canonical_sha256(request_payload)

    try:
        import httpx
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("formal DeepSeek transport dependencies are not installed") from exc

    transport = httpx.HTTPTransport(retries=0)
    with httpx.Client(
        transport=transport,
        proxy=proxy_url,
        trust_env=False,
        follow_redirects=False,
        timeout=float(timeout_seconds),
    ) as http_client:
        with OpenAI(
            api_key=credential_value,
            base_url=config.endpoint_origin,
            max_retries=0,
            timeout=float(timeout_seconds),
            http_client=http_client,
        ) as client:
            response = client.chat.completions.create(**request_payload)

    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or len(choices) != 1:
        raise RuntimeError("formal DeepSeek first slice requires exactly one response choice")
    message = getattr(choices[0], "message", None)
    assistant_text = getattr(message, "content", None)
    if not isinstance(assistant_text, str) or not assistant_text:
        raise RuntimeError("formal DeepSeek returned empty/non-string assistant content")

    if hasattr(response, "model_dump"):
        raw_response = response.model_dump(mode="json")
    else:
        raw_response = {
            "id": getattr(response, "id", None),
            "model": getattr(response, "model", None),
            "assistant_text_sha256": _formal_canonical_sha256(assistant_text),
        }
    raw_response_sha256 = _formal_canonical_sha256(raw_response)
    transport_evidence = {
        "schema": "RUNTIME_DEEPSEEK_FORMAL_TRANSPORT_EVIDENCE_V1",
        "provider": "deepseek",
        "resolved_model_entry_id": resolution.model_entry_id,
        "resolved_model": resolution.model,
        "model_resolution_sha256": resolution.resolution_sha256,
        "endpoint_origin": config.endpoint_origin,
        "api_route": config.api_route,
        "http_method": "POST",
        "stream": False,
        "sdk_max_retries": 0,
        "http_transport_retries": 0,
        "trust_env": False,
        "follow_redirects": False,
        "proxy_mode": config.proxy_mode,
        "proxy_config_sha256": config.proxy_config_sha256,
        "raw_response_sha256": raw_response_sha256,
    }
    return ProviderAttemptResult(
        assistant_text=assistant_text,
        request_payload_sha256=request_payload_sha256,
        response_payload_sha256=__import__("hashlib").sha256(assistant_text.encode("utf-8")).hexdigest(),
        transport_status="LIVE_SUCCESS",
        transport_evidence_sha256=_formal_canonical_sha256(transport_evidence),
        transport_retries_observed=0,
        fallback_observed=False,
    )

