from __future__ import annotations

from collections.abc import Callable

from universal_runtime.models.deepseek import (
    _formal_canonical_sha256,
    _formal_loopback_proxy_url,
    formal_loopback_proxy_config_sha256,
)


def issue_formal_deepseek_chat_completion_streaming(
    provider_execution_config,
    model_resolution,
    credential_value: str,
    *,
    messages: list[dict[str, str]],
    max_tokens: int,
    reasoning_effort: str,
    thinking: str,
    emit_visible_delta: Callable[[str], None],
    explicit_loopback_proxy_url: str | None = None,
    timeout_seconds: float = 180.0,
    stop_control=None,
    execution_instance_id: str | None = None,
):
    """Issue one exact DeepSeek streaming request and return the existing final result type.

    Visible ``delta.content`` is delivered to ``emit_visible_delta`` as ephemeral presentation
    data only. ``reasoning_content`` is never emitted or persisted here. Failure of the
    presentation sink does not retry the provider request and does not prevent final accumulation.
    """

    from universal_runtime.core.formal_model_live_composition import (
        P1S3CancellationSignal,
        P1S3StopControl,
        ProviderAttemptResult,
    )
    from universal_runtime.core.model_catalog import ResolvedModelExecution
    from universal_runtime.core.provider_execution_config import (
        ProviderExecutionConfig,
        direct_proxy_config_sha256,
    )

    if not isinstance(provider_execution_config, ProviderExecutionConfig):
        raise RuntimeError("formal DeepSeek streaming transport requires ProviderExecutionConfig")
    if not isinstance(model_resolution, ResolvedModelExecution):
        raise RuntimeError("formal DeepSeek streaming transport requires ResolvedModelExecution")
    if not callable(emit_visible_delta):
        raise RuntimeError("formal DeepSeek streaming transport requires a visible-delta sink")
    if stop_control is not None:
        if not isinstance(stop_control, P1S3StopControl):
            raise RuntimeError("formal DeepSeek STOP control type mismatch")
        if execution_instance_id != stop_control.execution_instance_id:
            raise RuntimeError("formal DeepSeek STOP execution instance mismatch")

    config = provider_execution_config
    resolution = model_resolution
    try:
        config.assert_matches_resolution(
            provider=resolution.provider,
            resolved_model_entry_id=resolution.model_entry_id,
            model_resolution_sha256=resolution.resolution_sha256,
        )
    except BaseException as exc:
        raise RuntimeError("formal DeepSeek streaming model resolution/config mismatch") from exc

    if resolution.provider != "deepseek" or config.provider != "deepseek":
        raise RuntimeError("formal DeepSeek streaming provider mismatch")
    if config.revision != 2 or config.stream is not True:
        raise RuntimeError("formal DeepSeek streaming requires ProviderExecutionConfig revision 2 stream=true")
    if config.endpoint_origin.rstrip("/") != "https://api.deepseek.com":
        raise RuntimeError("formal DeepSeek streaming requires exact official endpoint origin")
    if config.api_route != "/chat/completions":
        raise RuntimeError("formal DeepSeek streaming requires /chat/completions")
    if config.http_method != "POST":
        raise RuntimeError("formal DeepSeek streaming requires POST")
    if config.transport_retries_max != 0 or config.trust_env is not False:
        raise RuntimeError("formal DeepSeek streaming requires retry=0 and trust_env=false")
    if not isinstance(resolution.model, str) or not resolution.model:
        raise RuntimeError("formal DeepSeek streaming resolved model must be non-empty")
    if not isinstance(credential_value, str) or not credential_value:
        raise RuntimeError("formal DeepSeek streaming credential value is missing")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("formal DeepSeek streaming messages must be a non-empty list")

    normalized_messages: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise RuntimeError("formal DeepSeek streaming message must contain exact role/content fields")
        role = item.get("role")
        content = item.get("content")
        if role not in ("system", "user", "assistant"):
            raise RuntimeError("formal DeepSeek streaming message role is invalid")
        if not isinstance(content, str) or not content:
            raise RuntimeError("formal DeepSeek streaming message content must be non-empty")
        normalized_messages.append({"role": role, "content": content})

    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise RuntimeError("formal DeepSeek streaming max_tokens must be positive integer")
    if reasoning_effort not in ("low", "high", "max"):
        raise RuntimeError("formal DeepSeek streaming reasoning_effort invalid")
    if thinking not in ("enabled", "disabled"):
        raise RuntimeError("formal DeepSeek streaming thinking invalid")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise RuntimeError("formal DeepSeek streaming timeout must be positive")

    proxy_url: str | None
    if config.proxy_mode == "DIRECT":
        if explicit_loopback_proxy_url is not None:
            raise RuntimeError("DIRECT formal streaming transport forbids explicit proxy URL")
        if config.proxy_config_sha256 != direct_proxy_config_sha256():
            raise RuntimeError("DIRECT streaming proxy config SHA mismatch")
        proxy_url = None
    elif config.proxy_mode == "EXPLICIT_LOOPBACK_ONLY":
        if explicit_loopback_proxy_url is None:
            raise RuntimeError("explicit loopback streaming proxy URL is required")
        proxy_url = _formal_loopback_proxy_url(explicit_loopback_proxy_url)
        if formal_loopback_proxy_config_sha256(proxy_url) != config.proxy_config_sha256:
            raise RuntimeError("formal streaming loopback proxy config SHA mismatch")
    else:
        raise RuntimeError("unsupported formal DeepSeek streaming proxy mode")

    request_payload = {
        "model": resolution.model,
        "messages": normalized_messages,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
        "stream": True,
        "extra_body": {"thinking": {"type": thinking}},
    }
    request_payload_sha256 = _formal_canonical_sha256(request_payload)

    try:
        import httpx
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("formal DeepSeek streaming transport dependencies are not installed") from exc

    visible_parts: list[str] = []
    chunk_count = 0
    visible_delta_count = 0
    reasoning_delta_count = 0
    finish_reason: str | None = None
    stream_choice_index: int | None = None
    terminal_choice_seen = False
    sink_available = True
    sink_failure_observed = False

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
            try:
                stream = client.chat.completions.create(**request_payload)
            except BaseException:
                if stop_control is not None:
                    if not stop_control.mark_provider_failure():
                        winner = stop_control.cancellation_winner()
                        if winner is not None:
                            raise P1S3CancellationSignal(winner)
                raise

            if stop_control is not None:
                stop_control.register_stream_handle(
                    execution_instance_id=execution_instance_id,
                    stream_handle=stream,
                    close_hook=stream.close,
                )

            try:
                for chunk in stream:
                    if stop_control is not None:
                        winner = stop_control.cancellation_winner()
                        if winner is not None:
                            raise P1S3CancellationSignal(winner)
                    chunk_count += 1
                    choices = getattr(chunk, "choices", None)
                    if not isinstance(choices, list) or len(choices) not in (0, 1):
                        raise RuntimeError("formal DeepSeek streaming requires zero-or-one choice per chunk")
                    if not choices:
                        continue
                    choice = choices[0]
                    choice_index = getattr(choice, "index", None)
                    if (
                        isinstance(choice_index, bool)
                        or not isinstance(choice_index, int)
                        or choice_index < 0
                    ):
                        raise RuntimeError("formal DeepSeek streaming choice index invalid")
                    if stream_choice_index is None:
                        stream_choice_index = choice_index
                    elif choice_index != stream_choice_index:
                        raise RuntimeError("formal DeepSeek streaming choice index changed across chunks")
                    if terminal_choice_seen:
                        raise RuntimeError("formal DeepSeek streaming received a choice after terminal completion")

                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        raise RuntimeError("formal DeepSeek streaming chunk delta missing")

                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning is not None:
                        if not isinstance(reasoning, str):
                            raise RuntimeError("formal DeepSeek streaming reasoning_content must be text or null")
                        if reasoning:
                            reasoning_delta_count += 1

                    content = getattr(delta, "content", None)
                    if content is not None and not isinstance(content, str):
                        raise RuntimeError("formal DeepSeek streaming content must be text or null")
                    if isinstance(content, str) and content:
                        visible_parts.append(content)
                        visible_delta_count += 1
                        if sink_available:
                            try:
                                emit_visible_delta(content)
                            except Exception:
                                sink_available = False
                                sink_failure_observed = True

                    chunk_finish_reason = getattr(choice, "finish_reason", None)
                    if chunk_finish_reason is not None:
                        if not isinstance(chunk_finish_reason, str) or not chunk_finish_reason:
                            raise RuntimeError("formal DeepSeek streaming finish_reason invalid")
                        if finish_reason is not None:
                            raise RuntimeError("formal DeepSeek streaming observed multiple terminal finish reasons")
                        if stop_control is not None and not stop_control.mark_provider_success():
                            winner = stop_control.cancellation_winner()
                            if winner is not None:
                                raise P1S3CancellationSignal(winner)
                        finish_reason = chunk_finish_reason
                        terminal_choice_seen = True
            except P1S3CancellationSignal:
                raise
            except BaseException:
                if stop_control is not None:
                    if not stop_control.mark_provider_failure():
                        winner = stop_control.cancellation_winner()
                        if winner is not None:
                            raise P1S3CancellationSignal(winner)
                raise

            if stop_control is not None:
                winner = stop_control.cancellation_winner()
                if winner is not None:
                    raise P1S3CancellationSignal(winner)

    assistant_text = "".join(visible_parts)
    if not assistant_text:
        raise RuntimeError("formal DeepSeek streaming returned empty visible assistant content")
    if finish_reason is None or not terminal_choice_seen:
        if stop_control is not None:
            winner = stop_control.cancellation_winner()
            if winner is not None:
                raise P1S3CancellationSignal(winner)
            stop_control.mark_provider_failure()
        raise RuntimeError("formal DeepSeek streaming ended without terminal finish_reason")
    if stream_choice_index is None:
        raise RuntimeError("formal DeepSeek streaming never observed a legal choice identity")

    import hashlib as _hashlib

    assistant_sha256 = _hashlib.sha256(assistant_text.encode("utf-8")).hexdigest()
    raw_response_sha256 = _formal_canonical_sha256(
        {
            "chunk_count": chunk_count,
            "visible_delta_count": visible_delta_count,
            "reasoning_delta_count": reasoning_delta_count,
            "finish_reason": finish_reason,
            "stream_choice_index": stream_choice_index,
            "assistant_content_sha256": assistant_sha256,
            "sink_failure_observed": sink_failure_observed,
        }
    )
    transport_evidence = {
        "schema": "RUNTIME_DEEPSEEK_FORMAL_STREAMING_TRANSPORT_EVIDENCE_V1",
        "provider": "deepseek",
        "resolved_model_entry_id": resolution.model_entry_id,
        "resolved_model": resolution.model,
        "model_resolution_sha256": resolution.resolution_sha256,
        "endpoint_origin": config.endpoint_origin,
        "api_route": config.api_route,
        "http_method": "POST",
        "stream": True,
        "sdk_max_retries": 0,
        "http_transport_retries": 0,
        "trust_env": False,
        "follow_redirects": False,
        "proxy_mode": config.proxy_mode,
        "proxy_config_sha256": config.proxy_config_sha256,
        "chunk_count": chunk_count,
        "visible_delta_count": visible_delta_count,
        "reasoning_delta_count": reasoning_delta_count,
        "finish_reason": finish_reason,
        "stream_choice_index": stream_choice_index,
        "sink_failure_observed": sink_failure_observed,
        "raw_response_sha256": raw_response_sha256,
    }
    return ProviderAttemptResult(
        assistant_text=assistant_text,
        request_payload_sha256=request_payload_sha256,
        response_payload_sha256=assistant_sha256,
        transport_status="LIVE_SUCCESS",
        transport_evidence_sha256=_formal_canonical_sha256(transport_evidence),
        transport_retries_observed=0,
        fallback_observed=False,
    )
