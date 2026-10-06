"""Candidate multi-provider agent construction seam for Model Routing R001.

This module is intentionally narrow:
- provider/model selection remains owned by ModelPolicy + ModelCatalog;
- no catalog mutation or promotion occurs here;
- secrets are read only from environment variables at execution time;
- DeepSeek, Qwen, and Gemini are supported behind the same Runtime-owned seam;
- unsupported providers fail closed;
- no fallback is implemented.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from universal_runtime.core.model_catalog import ResolvedModelExecution
from universal_runtime.models.deepseek import DeepSeekAgentFactory
from universal_runtime.models.profiles import materialize_resolved_model_profile


class MultiProviderAdapterError(RuntimeError):
    """Raised when an execution cannot be safely materialized for a provider."""


def _logical_profile_settings(profile_id: str, path: Path) -> tuple[dict[str, object], str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("profiles"), dict):
        raise MultiProviderAdapterError("model profile configuration is invalid")
    profiles = data["profiles"]
    if profile_id not in profiles:
        raise MultiProviderAdapterError(f"Unknown model profile: {profile_id}")
    raw = profiles[profile_id]
    if not isinstance(raw, dict):
        raise MultiProviderAdapterError("logical model profile must be an object")

    try:
        thinking = raw["thinking"]
        reasoning_effort = raw["reasoning_effort"]
        max_tokens = raw["max_tokens"]
    except KeyError as exc:
        raise MultiProviderAdapterError(
            f"logical model profile is missing required field: {exc.args[0]}"
        ) from exc

    if thinking not in ("enabled", "disabled"):
        raise MultiProviderAdapterError("thinking must be enabled or disabled")
    if reasoning_effort not in ("low", "high", "max"):
        raise MultiProviderAdapterError("reasoning_effort is invalid")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise MultiProviderAdapterError("max_tokens must be a positive integer")

    settings: dict[str, object] = {
        "profile_id": profile_id,
        "thinking": thinking,
        "reasoning_effort": reasoning_effort,
        "max_tokens": max_tokens,
    }
    config_sha256 = hashlib.sha256(
        json.dumps(
            settings,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return settings, config_sha256


_GEMINI_NETWORK_MODE_DIRECT = "DIRECT"
_GEMINI_NETWORK_MODE_PROXY_REQUIRED = "PROXY_REQUIRED"


def _gemini_network_route() -> tuple[str, str | None]:
    """Resolve one explicit Gemini transport route without ambient proxy fallback."""

    mode = os.getenv("GEMINI_NETWORK_MODE", _GEMINI_NETWORK_MODE_DIRECT)
    proxy = os.getenv("GEMINI_HTTPS_PROXY")

    if mode not in (
        _GEMINI_NETWORK_MODE_DIRECT,
        _GEMINI_NETWORK_MODE_PROXY_REQUIRED,
    ):
        raise MultiProviderAdapterError(
            "GEMINI_NETWORK_MODE must be DIRECT or PROXY_REQUIRED"
        )

    if mode == _GEMINI_NETWORK_MODE_DIRECT:
        if proxy:
            raise MultiProviderAdapterError(
                "GEMINI_HTTPS_PROXY must be unset when GEMINI_NETWORK_MODE=DIRECT"
            )
        return mode, None

    if not proxy:
        raise MultiProviderAdapterError(
            "GEMINI_HTTPS_PROXY is required when GEMINI_NETWORK_MODE=PROXY_REQUIRED"
        )

    parsed = urlsplit(proxy)
    if parsed.scheme != "http":
        raise MultiProviderAdapterError(
            "GEMINI_HTTPS_PROXY must use an http:// local proxy URL"
        )
    if parsed.username is not None or parsed.password is not None:
        raise MultiProviderAdapterError(
            "GEMINI_HTTPS_PROXY must not contain credentials"
        )
    if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise MultiProviderAdapterError(
            "GEMINI_HTTPS_PROXY must resolve to a local loopback proxy"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise MultiProviderAdapterError(
            "GEMINI_HTTPS_PROXY contains an invalid port"
        ) from exc
    if port is None or port < 1 or port > 65535:
        raise MultiProviderAdapterError(
            "GEMINI_HTTPS_PROXY must include a valid local proxy port"
        )
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise MultiProviderAdapterError(
            "GEMINI_HTTPS_PROXY must not contain path, query, or fragment components"
        )

    return mode, proxy


class QwenAgentFactory:
    """Qwen adapter over the existing OpenAI-compatible MAF client."""

    def __init__(self, *, model: str, thinking: str, max_tokens: int):
        if not isinstance(model, str) or not model:
            raise MultiProviderAdapterError("Qwen model must be a non-empty string")
        if thinking not in ("enabled", "disabled"):
            raise MultiProviderAdapterError("Qwen thinking must be enabled or disabled")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise MultiProviderAdapterError("Qwen max_tokens must be a positive integer")
        self.model = model
        self.thinking = thinking
        self.max_tokens = max_tokens

    def create_agent(self, *, agent_id: str, name: str, instructions: str):
        api_key = os.getenv("QWEN_API_KEY")
        base_url = os.getenv("QWEN_BASE_URL")
        if not api_key:
            raise MultiProviderAdapterError("QWEN_API_KEY is not set")
        if not base_url:
            raise MultiProviderAdapterError(
                "QWEN_BASE_URL is not set; choose an explicit Model Studio region/workspace endpoint"
            )

        try:
            from agent_framework import Agent
            from agent_framework.openai import OpenAIChatCompletionClient
        except ImportError as exc:
            raise MultiProviderAdapterError(
                "agent-framework is not installed; use the existing Windows bootstrap"
            ) from exc

        options: dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "extra_body": {"enable_thinking": self.thinking == "enabled"},
        }
        return Agent(
            id=agent_id,
            name=name,
            client=OpenAIChatCompletionClient(
                base_url=base_url,
                api_key=api_key,
                model=self.model,
            ),
            instructions=instructions,
            default_options=options,
        )



class GeminiAgentFactory:
    """Gemini adapter over Google's OpenAI-compatible endpoint.

    This first candidate is intentionally limited to logical profiles with
    thinking enabled. Profiles that require thinking to be disabled fail
    closed instead of silently weakening the profile contract.
    """

    def __init__(
        self,
        *,
        model: str,
        thinking: str,
        reasoning_effort: str,
        max_tokens: int,
    ):
        if not isinstance(model, str) or not model:
            raise MultiProviderAdapterError("Gemini model must be a non-empty string")
        if thinking != "enabled":
            raise MultiProviderAdapterError(
                "Gemini candidate supports only thinking-enabled logical profiles"
            )
        if reasoning_effort not in ("low", "high"):
            raise MultiProviderAdapterError(
                "Gemini reasoning_effort must be low or high in this candidate"
            )
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
            raise MultiProviderAdapterError("Gemini max_tokens must be a positive integer")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_tokens = max_tokens

    def create_agent(self, *, agent_id: str, name: str, instructions: str):
        api_key = os.getenv("GEMINI_API_KEY")
        base_url = os.getenv("GEMINI_BASE_URL")
        if not api_key:
            raise MultiProviderAdapterError("GEMINI_API_KEY is not set")
        if not base_url:
            raise MultiProviderAdapterError("GEMINI_BASE_URL is not set")

        network_mode, proxy = _gemini_network_route()

        try:
            from agent_framework import Agent
            from agent_framework.openai import OpenAIChatCompletionClient
            from openai import AsyncOpenAI, DefaultAsyncHttpxClient
        except ImportError as exc:
            raise MultiProviderAdapterError(
                "agent-framework/openai is not installed; use the existing Windows bootstrap"
            ) from exc

        http_client_kwargs: dict[str, Any] = {"trust_env": False}
        if network_mode == _GEMINI_NETWORK_MODE_PROXY_REQUIRED:
            http_client_kwargs["proxy"] = proxy

        raw_client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=DefaultAsyncHttpxClient(**http_client_kwargs),
            max_retries=0,
        )

        options: dict[str, Any] = {
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "reasoning_effort": self.reasoning_effort,
        }
        return Agent(
            id=agent_id,
            name=name,
            client=OpenAIChatCompletionClient(
                model=self.model,
                async_client=raw_client,
            ),
            instructions=instructions,
            default_options=options,
        )


def create_agent_for_resolution(
    *,
    profile_id: str,
    resolution: ResolvedModelExecution,
    model_profiles_path: Path,
    agent_id: str,
    name: str,
    instructions: str,
):
    """Create an agent from one immutable Runtime resolution; never fallback silently.

    Returns ``(agent, logical_profile_config_sha256)``.
    """

    if not isinstance(resolution, ResolvedModelExecution):
        raise MultiProviderAdapterError("resolution must be a ResolvedModelExecution")
    if resolution.selected_profile != profile_id:
        raise MultiProviderAdapterError(
            "resolution selected_profile does not match requested profile_id"
        )

    if resolution.provider == "deepseek":
        profile, config_sha256 = materialize_resolved_model_profile(
            profile_id, resolution, model_profiles_path
        )
        return (
            DeepSeekAgentFactory(profile).create_agent(
                agent_id=agent_id,
                name=name,
                instructions=instructions,
            ),
            config_sha256,
        )

    if resolution.provider == "qwen":
        settings, config_sha256 = _logical_profile_settings(
            profile_id, model_profiles_path
        )
        return (
            QwenAgentFactory(
                model=resolution.model,
                thinking=str(settings["thinking"]),
                max_tokens=int(settings["max_tokens"]),
            ).create_agent(
                agent_id=agent_id,
                name=name,
                instructions=instructions,
            ),
            config_sha256,
        )

    if resolution.provider == "gemini":
        settings, config_sha256 = _logical_profile_settings(
            profile_id, model_profiles_path
        )
        return (
            GeminiAgentFactory(
                model=resolution.model,
                thinking=str(settings["thinking"]),
                reasoning_effort=str(settings["reasoning_effort"]),
                max_tokens=int(settings["max_tokens"]),
            ).create_agent(
                agent_id=agent_id,
                name=name,
                instructions=instructions,
            ),
            config_sha256,
        )

    raise MultiProviderAdapterError(
        f"No accepted model adapter exists for provider: {resolution.provider}"
    )
