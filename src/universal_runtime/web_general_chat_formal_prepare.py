"""Web-owned General Chat formal-prepare adapter for one source-grounded first slice.

This reuses the independently reviewed R004 General Chat formal-prepare semantics at the
Web composition boundary. It performs no credential resolution, provider/network/model call,
Grant creation, attempt claim, formal result commit, or Web result projection. Runtime-owned
Authority/Artifact/Job/ModelPolicy owners remain unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import re
from typing import Any, Callable

from universal_runtime.core.artifact_store import ArtifactCurrentnessError, ArtifactStore, R009OpaqueArtifactBinding, R009OpaqueArtifactError
from universal_runtime.core.formal_model_job import (
    FormalModelJobError,
    FormalModelJobLedger,
    legacy_artifact_identity_sha256,
)
from universal_runtime.core.human_decision_authority import HumanDecisionAuthority, HumanDecisionAuthorityError
from universal_runtime.core.job_authority import JobAuthorityRegistry, JobAuthorityError
from universal_runtime.core.job_permissions import JobFilesystemPermissionPlan
from universal_runtime.core.job_pins import JobPackPin
from universal_runtime.core.load_plan import LoadInput, LoadPlan
from universal_runtime.core.model_catalog import (
    ModelCatalog,
    ModelCatalogEntry,
    ModelCatalogStatus,
    ModelResolutionRequest,
    ModelUpdateMode,
    ResolvedModelExecution,
    resolve_model_execution,
)
from universal_runtime.core.model_policy import (
    ModelDecisionRequest,
    ModelSelectionMode,
    ReasoningLevel,
    RiskLevel,
    TaskKind,
    TaskRequirement,
    select_model_profile,
)
from universal_runtime.core.provider_execution_config import ProviderExecutionConfig, direct_proxy_config_sha256
from universal_runtime.core.enums import PersistenceClass
from universal_runtime.packs.registry import PackRegistry
from universal_runtime.web_conversation_graph import (
    WebConversationGraphError,
    build_provider_messages_from_active_context,
    validate_active_context_snapshot,
    validate_current_context_guard,
)
from universal_runtime.web_continuity import WebContinuityError, WebContinuityService
from universal_runtime.web_project_memory import (
    ProjectMemoryError,
    ProjectMemoryService,
    build_plain_memory_user_payload,
)


class GeneralChatFormalPrepareError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PERSONAL_CONTEXT_SCHEMA = "RUNTIME_NON_AUTHORITY_USER_PERSONAL_CONTEXT_V1"
PERSONAL_CONTEXT_AUTHORITY_CLASS = "NON_AUTHORITY_USER_PERSONAL_CONTEXT"
PERSONAL_CONTEXT_SOURCE_CLASS = "PRODUCT_SHELL_SAVED_MEMORY"
PERSONAL_CONTEXT_CURRENTNESS_CLASS = "REQUEST_SNAPSHOT_ONLY"
PERSONAL_CONTEXT_PERSISTENCE_CLASS = "JOB_BOUND_WORKING_INPUT"
PERSONAL_CONTEXT_MAX_BYTES = 64 * 1024
PROJECT_HISTORY_CONTEXT_MAX_BYTES = 64 * 1024
PACK_ID = "general_chat_system"
PACK_VERSION = "0.1.0"
ACTION_ID = "general_text_reply"
LOGICAL_PROFILE = "reason_high"
MODEL_ENTRY_ID = "deepseek-v4-pro@DeepSeek-V4-Pro-0813"
CATALOG_REL = Path("config/model_catalogs/LOCAL_MODEL_CATALOG_V0_R002.json")
ADOPTION_RECORD_REL = Path(
    "artifacts/model_catalog_job_adoption_"
    "MCA_5cbb8420eab1ed7295747204d272172aca506216943aac032c8f5ba75f90adeb_R002.json"
)
ADOPTION_RECORD_SHA256 = "ca988c52fb014d7bfcb1d2ac481652b73828cc6ca1653491fa419506a2722f65"
DEEPSEEK_ENDPOINT = "https://api.deepseek.com"
DEEPSEEK_ROUTE = "/chat/completions"
DEEPSEEK_CREDENTIAL_REF_ID = "DEEPSEEK_API_KEY"
DEEPSEEK_CREDENTIAL_REF_CLASS = "ENVIRONMENT_VARIABLE"
P1_S2_PROVIDER_EXECUTION_CONFIG_MODULE_SHA256 = "3a9189dc12816ca0e982c47cf1106e4f6a5be847f3a82deafc4d76aec496475d"
R004_DEEPSEEK_ADAPTER_SHA256 = "c906117d3845121afc2f948178cb515865292fedea9795c6be85f3697aa90c9e"
P1_S2_DEEPSEEK_FINAL_ONLY_DEPENDENCY_SHA256 = R004_DEEPSEEK_ADAPTER_SHA256
R004_DEEPSEEK_PROVIDER_EXECUTION_CONFIG_SHA256 = "90d7fcf99422623b99f21e50f6b1be8422795f17afb0119900f4f541f48bfa3e"
P1_S2_DEEPSEEK_STREAMING_ADAPTER_RELATIVE_PATH = "src/universal_runtime/models/deepseek_streaming.py"
P1_S2_DEEPSEEK_STREAMING_ADAPTER_MODULE = "universal_runtime.models.deepseek_streaming"
P1_S3_DEEPSEEK_STREAMING_ADAPTER_SHA256 = "322e87f714740350ff8720f4d703b50fe7d57df8aefdc6f0e1bd608e43a971c1"
P1_S3_HTTPX_VERSION = "0.28.1"
P1_S3_OPENAI_VERSION = "2.54.0"
FIRST_SLICE_BUDGET = {
    "live_attempts_max": 1,
    "model_calls_max": 1,
    "network_calls_max": 1,
    "retries_max": 0,
    "fallback_allowed": False,
}



@dataclass(frozen=True)
class GeneralChatModelTarget:
    """Runtime/job-scoped concrete-model target. Pack semantics remain logical-profile only."""

    catalog_rel: Path
    catalog_revision: str
    catalog_file_sha256: str
    catalog_semantic_sha256: str
    adoption_record_rel: Path
    adoption_record_sha256: str
    model_entry_id: str
    provider: str
    model: str
    endpoint_origin: str
    api_route: str
    proxy_mode: str
    proxy_config_sha256: str
    credential_ref_id: str
    credential_ref_class: str
    adapter_relative_path: str
    adapter_module_name: str
    transport_client_class: str = "openai.OpenAI"

    def __post_init__(self) -> None:
        for name in (
            "catalog_revision",
            "catalog_file_sha256",
            "catalog_semantic_sha256",
            "adoption_record_sha256",
            "model_entry_id",
            "provider",
            "model",
            "endpoint_origin",
            "api_route",
            "proxy_mode",
            "proxy_config_sha256",
            "credential_ref_id",
            "credential_ref_class",
            "adapter_relative_path",
            "adapter_module_name",
            "transport_client_class",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty text")
        for name in (
            "catalog_file_sha256",
            "catalog_semantic_sha256",
            "adoption_record_sha256",
            "proxy_config_sha256",
        ):
            if _SHA_RE.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} must be lowercase 64-hex")
        if not isinstance(self.catalog_rel, Path) or self.catalog_rel.is_absolute() or ".." in self.catalog_rel.parts:
            raise ValueError("catalog_rel must be a safe relative Path")
        if not isinstance(self.adoption_record_rel, Path) or self.adoption_record_rel.is_absolute() or ".." in self.adoption_record_rel.parts:
            raise ValueError("adoption_record_rel must be a safe relative Path")


DEFAULT_DEEPSEEK_TARGET = GeneralChatModelTarget(
    catalog_rel=CATALOG_REL,
    catalog_revision="LOCAL_MODEL_CATALOG_V0_R002",
    catalog_file_sha256="58800336c5eaf514ddba594f8755b06c53d66c24de8d9ab09c4d424fd55a80e7",
    catalog_semantic_sha256="ae9706f0710cffb63abc3dfbc460fe0725dfd099a7f7dce11f0f3cac0766597c",
    adoption_record_rel=ADOPTION_RECORD_REL,
    adoption_record_sha256=ADOPTION_RECORD_SHA256,
    model_entry_id=MODEL_ENTRY_ID,
    provider="deepseek",
    model="deepseek-v4-pro",
    endpoint_origin=DEEPSEEK_ENDPOINT,
    api_route=DEEPSEEK_ROUTE,
    proxy_mode="DIRECT",
    proxy_config_sha256=direct_proxy_config_sha256(),
    credential_ref_id=DEEPSEEK_CREDENTIAL_REF_ID,
    credential_ref_class=DEEPSEEK_CREDENTIAL_REF_CLASS,
    adapter_relative_path="src/universal_runtime/models/deepseek.py",
    adapter_module_name="universal_runtime.models.deepseek",
)


@dataclass(frozen=True)
class GeneralChatPhaseAPreparedJob:

    job_id: str
    job_bundle_record: dict[str, Any]
    job_bundle_binding: dict[str, Any]
    runtime_contract_manifest: dict[str, Any]
    runtime_contract_manifest_sha256: str
    pack_pin: dict[str, Any]
    permission_plan: dict[str, Any]
    load_plan: dict[str, Any]
    model_decision: dict[str, Any]
    model_resolution: dict[str, Any]
    provider_execution_config: dict[str, Any]
    provider_execution_config_sha256: str
    input_set: dict[str, Any]
    workflow_pin_sha256: str
    rule_pin_sha256: str
    adapter_executor_pin_set_sha256: str
    network_permission_plan: dict[str, Any]
    authorized_request_plan: dict[str, Any]
    secret_access_plan: dict[str, Any]
    model_profile_binding: dict[str, Any]
    output_contract_sha256: str
    persistence_plan: dict[str, Any]
    runtime_execution_identity_sha256: str
    source_context: dict[str, Any] | None = None
    source_context_sha256: str | None = None
    source_context_binding: dict[str, Any] | None = None
    personal_context: dict[str, Any] | None = None
    personal_context_sha256: str | None = None
    personal_context_binding: dict[str, Any] | None = None
    project_memory_context: dict[str, Any] | None = None
    project_memory_context_sha256: str | None = None
    project_memory_context_binding: dict[str, Any] | None = None
    project_memory_state_guard: dict[str, Any] | None = None
    project_memory_state_guard_sha256: str | None = None
    project_memory_state_guard_binding: dict[str, Any] | None = None


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return _sha_bytes(_canonical(value))


def _binding_dict(binding: Any) -> dict[str, Any]:
    return {
        "artifact_identity_sha256": binding.artifact_identity_sha256,
        "artifact_revision": binding.artifact_revision,
        "artifact_sha256": binding.artifact_sha256,
    }


def validate_non_authority_personal_context_snapshot(
    *,
    personal_context: dict[str, Any] | None,
    personal_context_sha256: str | None,
) -> dict[str, Any] | None:
    """Validate one product-shell personal-memory snapshot without granting it authority."""
    if personal_context is None and personal_context_sha256 is None:
        return None
    if not isinstance(personal_context, dict):
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_INVALID",
            "personal context must be an exact object when present",
            status_code=400,
        )
    if not isinstance(personal_context_sha256, str) or _SHA_RE.fullmatch(personal_context_sha256) is None:
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_SHA_REQUIRED",
            "personal context requires an exact canonical SHA",
            status_code=400,
        )
    required_keys = {
        "schema",
        "authority_class",
        "source_class",
        "currentness_class",
        "persistence_class",
        "text",
        "text_sha256",
    }
    if set(personal_context) != required_keys:
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_CONTRACT",
            "personal context fields differ from the narrow Runtime contract",
            status_code=400,
        )
    if (
        personal_context.get("schema") != PERSONAL_CONTEXT_SCHEMA
        or personal_context.get("authority_class") != PERSONAL_CONTEXT_AUTHORITY_CLASS
        or personal_context.get("source_class") != PERSONAL_CONTEXT_SOURCE_CLASS
        or personal_context.get("currentness_class") != PERSONAL_CONTEXT_CURRENTNESS_CLASS
        or personal_context.get("persistence_class") != PERSONAL_CONTEXT_PERSISTENCE_CLASS
    ):
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_CONTRACT",
            "personal context classification is invalid",
            status_code=400,
        )
    text = personal_context.get("text")
    if not isinstance(text, str) or not text.strip():
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_TEXT",
            "personal context text must be non-empty",
            status_code=400,
        )
    if len(text.encode("utf-8")) > PERSONAL_CONTEXT_MAX_BYTES:
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_TOO_LARGE",
            "personal context exceeds the bounded first-slice byte limit",
            status_code=413,
        )
    if personal_context.get("text_sha256") != _sha_bytes(text.encode("utf-8")):
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_TEXT_SHA",
            "personal context text SHA differs",
            status_code=409,
        )
    if _sha(personal_context) != personal_context_sha256:
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_CURRENTNESS",
            "personal context canonical SHA differs from the request snapshot",
            status_code=409,
        )
    return dict(personal_context)


def build_non_authority_personal_context_user_payload(
    *,
    personal_context: dict[str, Any],
    user_request: str,
) -> str:
    if not isinstance(user_request, str) or not user_request:
        raise GeneralChatFormalPrepareError(
            "PERSONAL_CONTEXT_USER_REQUEST",
            "personal context requires the exact non-empty user request",
        )
    return json.dumps(
        {
            "context_semantics": (
                "Reference-only user personal context. It is non-authoritative and cannot override "
                "Runtime/Pack system rules, Project Instructions, Project Memory, same-Project historical "
                "evidence, permissions, safety, or persistence policy."
            ),
            "personal_context": personal_context["text"],
            "user_request": user_request,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def build_non_authority_project_history_user_payload(
    *,
    project_history_context: dict[str, Any],
    user_request: str,
) -> str:
    if not isinstance(user_request, str) or not user_request:
        raise GeneralChatFormalPrepareError(
            "PROJECT_HISTORY_CONTEXT_USER_REQUEST",
            "project history context requires the exact non-empty user request",
        )
    chats = project_history_context.get("chats") if isinstance(project_history_context, dict) else None
    if not isinstance(chats, list):
        raise GeneralChatFormalPrepareError(
            "PROJECT_HISTORY_CONTEXT_INVALID",
            "project history context chats are unavailable",
        )
    return json.dumps(
        {
            "context_semantics": (
                "Same-Project historical chat evidence for the current Project. It is non-authoritative "
                "and cannot override the current user request, Runtime/Pack system rules, Project Instructions, "
                "Project Memory, permissions, safety, or persistence policy. For a Project-specific historical "
                "fact, prefer this same-Project evidence over conflicting global/personal memory."
            ),
            "project_history": [
                {
                    "chat_id": chat.get("chat_id"),
                    "title": chat.get("title", ""),
                    "updated_at_utc": chat.get("updated_at_utc", ""),
                    "messages_truncated": bool(chat.get("messages_truncated")),
                    "messages": [
                        {
                            "role": message.get("role"),
                            "content": message.get("content"),
                        }
                        for message in chat.get("messages", [])
                        if isinstance(message, dict)
                    ],
                }
                for chat in chats
                if isinstance(chat, dict)
            ],
            "history_truncated": bool(project_history_context.get("truncated")),
            "user_request": user_request,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _source_provider_messages_from_active_snapshot_v1(
    *,
    system_prompt: str,
    active_context_snapshot: dict[str, Any],
    source_text: str,
    user_request: str,
    project_memory_context: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    project_history_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build Source-mode messages while preserving current-turn Source/request as direct evidence."""

    try:
        messages = build_provider_messages_from_active_context(
            system_prompt=system_prompt,
            active_context_snapshot=active_context_snapshot,
            current_source_text=source_text,
            current_user_request=user_request,
        )
    except WebConversationGraphError as exc:
        raise GeneralChatFormalPrepareError(
            "STREAMING_ACTIVE_CONTEXT",
            f"{exc.code}: {exc.message}",
        ) from exc

    project_memory_items = None
    if project_memory_context is not None:
        items = project_memory_context.get("items") if isinstance(project_memory_context, dict) else None
        if not isinstance(items, list) or not items:
            raise GeneralChatFormalPrepareError(
                "PROJECT_MEMORY_CONTEXT_INVALID",
                "project memory context items unavailable",
            )
        project_memory_items = [
            {
                "memory_id": item.get("memory_id"),
                "content": item.get("content"),
            }
            for item in items
            if isinstance(item, dict)
        ]

    history_payload = None
    history_truncated = False
    if project_history_context is not None:
        chats = project_history_context.get("chats") if isinstance(project_history_context, dict) else None
        if not isinstance(chats, list):
            raise GeneralChatFormalPrepareError(
                "PROJECT_HISTORY_CONTEXT_INVALID",
                "project history context chats are unavailable",
            )
        history_payload = [
            {
                "chat_id": chat.get("chat_id"),
                "title": chat.get("title", ""),
                "updated_at_utc": chat.get("updated_at_utc", ""),
                "messages_truncated": bool(chat.get("messages_truncated")),
                "messages": [
                    {
                        "role": message.get("role"),
                        "content": message.get("content"),
                    }
                    for message in chat.get("messages", [])
                    if isinstance(message, dict)
                ],
            }
            for chat in chats
            if isinstance(chat, dict)
        ]
        history_truncated = bool(project_history_context.get("truncated"))

    payload = {
        "context_semantics": (
            "Current source_text and current user_request are direct current-turn evidence. "
            "Project Instructions/system rules remain authoritative. Project Memory and same-Project "
            "history are Project-scoped background context; global/personal memory is lower-priority "
            "reference-only context. No background context may override the explicit current Source "
            "or current user request."
        ),
        "source_text": source_text,
        "user_request": user_request,
        "personal_context": (
            personal_context.get("text")
            if isinstance(personal_context, dict)
            else None
        ),
        "project_history": history_payload,
        "history_truncated": history_truncated,
        "project_memory": project_memory_items,
    }
    messages[-1] = {
        "role": "user",
        "content": json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }
    return messages


def _plain_provider_messages_from_active_snapshot_v1(
    *,
    system_prompt: str,
    active_context_snapshot: dict[str, Any],
    project_memory_context: dict[str, Any] | None = None,
    personal_context: dict[str, Any] | None = None,
    project_history_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Build no-Source provider messages from one already-validated active snapshot."""
    if not isinstance(system_prompt, str) or not system_prompt:
        raise GeneralChatFormalPrepareError(
            "STREAMING_PROMPT_CURRENTNESS",
            "no-Source General Chat requires non-empty exact system prompt",
        )
    ordered = active_context_snapshot.get("ordered_messages")
    if not isinstance(ordered, list) or not ordered:
        raise GeneralChatFormalPrepareError(
            "STREAMING_ACTIVE_CONTEXT",
            "no-Source General Chat requires exact active conversation messages",
        )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in ordered:
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        if role not in ("user", "assistant") or not isinstance(content, str) or not content:
            raise GeneralChatFormalPrepareError(
                "STREAMING_ACTIVE_CONTEXT",
                "no-Source active conversation message is invalid",
            )
        messages.append({"role": role, "content": content})
    if messages[-1]["role"] != "user":
        raise GeneralChatFormalPrepareError(
            "STREAMING_ACTIVE_CONTEXT",
            "no-Source active conversation head must be USER",
        )
    if personal_context is not None:
        messages[-1] = {
            "role": "user",
            "content": build_non_authority_personal_context_user_payload(
                personal_context=personal_context,
                user_request=messages[-1]["content"],
            ),
        }
    if project_history_context is not None:
        messages[-1] = {
            "role": "user",
            "content": build_non_authority_project_history_user_payload(
                project_history_context=project_history_context,
                user_request=messages[-1]["content"],
            ),
        }
    if project_memory_context is not None:
        try:
            messages[-1] = {
                "role": "user",
                "content": build_plain_memory_user_payload(
                    project_memory_context=project_memory_context,
                    user_request=messages[-1]["content"],
                ),
            }
        except ProjectMemoryError as exc:
            raise GeneralChatFormalPrepareError(
                "PROJECT_MEMORY_CONTEXT_CURRENTNESS",
                f"{exc.code}: {exc.message}",
                status_code=exc.status_code,
            ) from exc
    return messages


def _compose_system_prompt_with_project_instructions(
    *,
    system_prompt: str,
    project_instructions: str,
) -> str:
    if not isinstance(system_prompt, str) or not system_prompt:
        raise GeneralChatFormalPrepareError(
            "PROJECT_INSTRUCTIONS_PROMPT_CURRENTNESS",
            "Project Instructions composition requires non-empty Pack system prompt",
        )
    if not isinstance(project_instructions, str):
        raise GeneralChatFormalPrepareError(
            "PROJECT_INSTRUCTIONS_CURRENTNESS",
            "Project Instructions must be exact text",
        )
    if project_instructions == "":
        return system_prompt
    return (
        system_prompt
        + "\n\n[PROJECT INSTRUCTIONS — RUNTIME CANONICAL USER SCOPE]\n"
        + "These Project Instructions are subordinate to Runtime/Pack authority, permissions, safety, and system rules.\n"
        + project_instructions
        + "\n[END PROJECT INSTRUCTIONS]"
    )


def _artifact_identity(kind: str, job_id: str) -> str:
    return _sha({"namespace": "UR_S1_PHASE_A_ARTIFACT_ID_V1", "kind": kind, "job_id": job_id})


def _persist_exact_json(
    store: ArtifactStore,
    *,
    kind: str,
    job_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    raw = _canonical(record)
    identity = _artifact_identity(kind, job_id)
    binding, _manifest = store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
        artifact_identity_sha256=identity,
        artifact_bytes=raw,
        job_id=job_id,
        persistence_class=PersistenceClass.WORKING,
        expected_artifact_sha256=_sha_bytes(raw),
    )
    return _binding_dict(binding)


def _file_sha(path: Path) -> str:
    if not path.is_file():
        raise GeneralChatFormalPrepareError("CURRENTNESS_MISSING", f"required file missing: {path}")
    return _sha_bytes(path.read_bytes())


def _module_file_sha(module_file: str | None, label: str) -> str:
    if not isinstance(module_file, str) or not module_file:
        raise GeneralChatFormalPrepareError("CURRENTNESS_MISSING", f"{label} module path unavailable")
    return _file_sha(Path(module_file))


def _catalog_from_json(data: dict[str, Any]) -> ModelCatalog:
    entries: list[ModelCatalogEntry] = []
    raw_entries = data.get("entries")
    if not isinstance(raw_entries, list):
        raise GeneralChatFormalPrepareError("CATALOG_INVALID", "catalog entries missing")
    for item in raw_entries:
        if not isinstance(item, dict):
            raise GeneralChatFormalPrepareError("CATALOG_INVALID", "catalog entry invalid")
        try:
            entries.append(
                ModelCatalogEntry(
                    entry_id=item["entry_id"],
                    provider=item["provider"],
                    model=item["model"],
                    eligible_profiles=tuple(item["eligible_profiles"]),
                    status=ModelCatalogStatus(item["status"]),
                    promotion_order=item["promotion_order"],
                    cost_rank=item["cost_rank"],
                    quality_rank=item["quality_rank"],
                    latency_rank=item["latency_rank"],
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GeneralChatFormalPrepareError("CATALOG_INVALID", "catalog entry invalid") from exc
    try:
        return ModelCatalog(
            catalog_revision=data["catalog_revision"],
            entries=tuple(entries),
            catalog_sha256=data["catalog_sha256"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GeneralChatFormalPrepareError("CATALOG_INVALID", "catalog identity invalid") from exc


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_INVALID", f"{label} must be lowercase 64-hex")
    return value


def _require_positive_revision(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_INVALID", f"{label} must be a positive integer")
    return value


_RETRY_LINEAGE_SCHEMA = "WEB_GENERAL_CHAT_RETRY_AFTER_CONFIRMED_CANCEL_LINEAGE_V1"
_RETRY_LINEAGE_KIND = "RETRY_AFTER_CONFIRMED_CANCEL"
_RETRY_LINEAGE_FIELDS = frozenset({
    "schema",
    "retry_kind",
    "predecessor_job_id",
    "predecessor_job_bundle_sha256",
    "predecessor_job_bundle_binding",
    "predecessor_web_formal_job_intake_binding",
    "predecessor_cancellation_outcome_receipt_id",
    "predecessor_cancellation_outcome_binding",
    "predecessor_cancellation_winner",
})


def _require_retry_binding(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "artifact_identity_sha256", "artifact_revision", "artifact_sha256"
    }:
        raise GeneralChatFormalPrepareError(
            "RETRY_LINEAGE_INVALID",
            f"{label} must be an exact R009 binding",
            status_code=409,
        )
    return {
        "artifact_identity_sha256": _require_sha(value.get("artifact_identity_sha256"), f"{label}.artifact_identity_sha256"),
        "artifact_revision": _require_positive_revision(value.get("artifact_revision"), f"{label}.artifact_revision"),
        "artifact_sha256": _require_sha(value.get("artifact_sha256"), f"{label}.artifact_sha256"),
    }


def _normalize_retry_lineage(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _RETRY_LINEAGE_FIELDS:
        raise GeneralChatFormalPrepareError(
            "RETRY_LINEAGE_INVALID",
            "retry lineage exact field-set mismatch",
            status_code=409,
        )
    if value.get("schema") != _RETRY_LINEAGE_SCHEMA or value.get("retry_kind") != _RETRY_LINEAGE_KIND:
        raise GeneralChatFormalPrepareError(
            "RETRY_LINEAGE_INVALID",
            "retry lineage schema/kind mismatch",
            status_code=409,
        )
    predecessor_job_id = value.get("predecessor_job_id")
    receipt_id = value.get("predecessor_cancellation_outcome_receipt_id")
    winner = value.get("predecessor_cancellation_winner")
    if not isinstance(predecessor_job_id, str) or not predecessor_job_id:
        raise GeneralChatFormalPrepareError("RETRY_LINEAGE_INVALID", "predecessor_job_id required", status_code=409)
    if not isinstance(receipt_id, str) or not receipt_id.startswith("ATTEMPTCANCEL_"):
        raise GeneralChatFormalPrepareError("RETRY_LINEAGE_INVALID", "cancellation receipt id invalid", status_code=409)
    if winner not in {"CANCEL_BEFORE_REQUEST", "CANCEL_ACTIVE_STREAM"}:
        raise GeneralChatFormalPrepareError("RETRY_LINEAGE_INVALID", "cancellation winner invalid", status_code=409)
    return {
        "schema": _RETRY_LINEAGE_SCHEMA,
        "retry_kind": _RETRY_LINEAGE_KIND,
        "predecessor_job_id": predecessor_job_id,
        "predecessor_job_bundle_sha256": _require_sha(
            value.get("predecessor_job_bundle_sha256"), "predecessor_job_bundle_sha256"
        ),
        "predecessor_job_bundle_binding": _require_retry_binding(
            value.get("predecessor_job_bundle_binding"), "predecessor_job_bundle_binding"
        ),
        "predecessor_web_formal_job_intake_binding": _require_retry_binding(
            value.get("predecessor_web_formal_job_intake_binding"),
            "predecessor_web_formal_job_intake_binding",
        ),
        "predecessor_cancellation_outcome_receipt_id": receipt_id,
        "predecessor_cancellation_outcome_binding": _require_retry_binding(
            value.get("predecessor_cancellation_outcome_binding"),
            "predecessor_cancellation_outcome_binding",
        ),
        "predecessor_cancellation_winner": winner,
    }


class GeneralChatFormalPrepareService:
    def __init__(
        self,
        *,
        runtime_home: Path,
        artifact_store: ArtifactStore,
        pack_registry: PackRegistry | None = None,
        formal_ledger: FormalModelJobLedger | None = None,
        job_authority: JobAuthorityRegistry | None = None,
        human_decision_authority: HumanDecisionAuthority | None = None,
        model_target: GeneralChatModelTarget | None = None,
    ):
        self.runtime_home = Path(runtime_home).resolve()
        self.store = artifact_store
        self.model_target = model_target or DEFAULT_DEEPSEEK_TARGET
        self.pack_registry = pack_registry or PackRegistry(self.runtime_home / "packs")
        self.job_authority = job_authority or JobAuthorityRegistry(self.runtime_home, artifact_store)
        self.ledger = formal_ledger or FormalModelJobLedger(
            artifact_store,
            job_authority=self.job_authority,
        )
        self.human_decision = human_decision_authority or HumanDecisionAuthority(
            self.runtime_home, artifact_store, self.job_authority
        )

    def _validate_adoption(self) -> dict[str, Any]:
        path = self.runtime_home / self.model_target.adoption_record_rel
        if _file_sha(path) != self.model_target.adoption_record_sha256:
            raise GeneralChatFormalPrepareError(
                "MODELCATALOG_ADOPTION_STALE",
                "exact General Chat ModelCatalog adoption record is missing or stale",
            )
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GeneralChatFormalPrepareError("MODELCATALOG_ADOPTION_STALE", "adoption record invalid") from exc
        expected = {
            "authority_owner": "RUNTIME_MODEL_CATALOG_LIFECYCLE",
            "catalog_revision": self.model_target.catalog_revision,
            "catalog_semantic_sha256": self.model_target.catalog_semantic_sha256,
            "catalog_file_sha256": self.model_target.catalog_file_sha256,
            "model_entry_id": self.model_target.model_entry_id,
            "provider": self.model_target.provider,
            "model": self.model_target.model,
            "logical_profile": LOGICAL_PROFILE,
            "target_pack_id": PACK_ID,
            "target_pack_version": PACK_VERSION,
            "target_action_id": ACTION_ID,
            "adoption_scope": "EXACT_PACK_VERSION_ACTION_PROFILE_ENTRY_ONLY",
            "global_default_changed": False,
            "other_pack_auto_adoption": False,
            "running_jobs_rebound": False,
            "network_authorized": False,
            "model_call_authorized": False,
            "credential_read_authorized": False,
        }
        for key, value in expected.items():
            if record.get(key) != value:
                raise GeneralChatFormalPrepareError(
                    "MODELCATALOG_ADOPTION_STALE",
                    f"adoption record mismatch at {key}",
                )
        return record

    def _validate_library_source_context(
        self,
        *,
        source_context: dict[str, Any] | None,
        source_context_sha256: str | None,
        project_id: str,
        chat_id: str,
        event_id: str,
        content_sha256: str,
        initiating_user_event_binding: dict[str, Any],
    ) -> dict[str, Any] | None:
        if source_context is None and source_context_sha256 is None:
            return None
        if not isinstance(source_context, dict) or not isinstance(source_context_sha256, str):
            raise GeneralChatFormalPrepareError(
                "SOURCE_CONTEXT_INCOMPLETE",
                "source_context and source_context_sha256 must be supplied together",
                status_code=400,
            )
        _require_sha(source_context_sha256, "source_context_sha256")
        if _sha(source_context) != source_context_sha256:
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_STALE", "source context canonical SHA mismatch")
        if (
            source_context.get("schema") != "UR_LIBRARY_NATIVE_SOURCE_CONTEXT_R001"
            or source_context.get("authority_class") != "NON_AUTHORITY_FORMAL_INPUT_PROPOSAL"
            or source_context.get("project_id") != project_id
            or source_context.get("chat_id") != chat_id
        ):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_SCOPE_MISMATCH", "source context scope/schema mismatch")

        source_event = source_context.get("initiating_user_event")
        if not isinstance(source_event, dict):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_EVENT_MISMATCH", "source context event binding missing")
        if source_event.get("event_id") != event_id or source_event.get("content_sha256") != content_sha256:
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_EVENT_MISMATCH", "source context event differs from exact USER_MESSAGE")
        source_event_binding = source_event.get("binding")
        if not isinstance(source_event_binding, dict):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_EVENT_MISMATCH", "source context event artifact binding missing")
        for key in ("artifact_id", "revision", "sha256"):
            if source_event_binding.get(key) != initiating_user_event_binding.get(key):
                raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_EVENT_MISMATCH", f"source context event binding differs at {key}")

        question = source_context.get("question")
        if not isinstance(question, str) or _sha_bytes(question.encode("utf-8")) != content_sha256:
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_QUESTION_MISMATCH", "source question differs from USER_MESSAGE content SHA")
        source_ref_id = source_context.get("source_ref_id")
        if not isinstance(source_ref_id, str) or not source_ref_id:
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_INVALID", "source_ref_id required")

        source_artifact = source_context.get("source_artifact")
        if not isinstance(source_artifact, dict):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_INVALID", "source_artifact binding required")
        artifact_id = source_artifact.get("artifact_id")
        artifact_identity_sha256 = _require_sha(source_artifact.get("artifact_identity_sha256"), "source artifact identity SHA")
        artifact_revision = _require_positive_revision(source_artifact.get("revision"), "source artifact revision")
        artifact_sha256 = _require_sha(source_artifact.get("sha256"), "source artifact SHA")
        byte_size = source_artifact.get("byte_size")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_INVALID", "source artifact_id required")
        if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_INVALID", "source artifact byte_size invalid")

        decoded_text = source_context.get("decoded_text")
        derivation_sha256 = _require_sha(source_context.get("derivation_sha256"), "derivation_sha256")
        if not isinstance(decoded_text, str) or _sha_bytes(decoded_text.encode("utf-8")) != derivation_sha256:
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_DERIVATION_MISMATCH", "decoded text differs from derivation SHA")
        try:
            source_manifest, source_bytes = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=artifact_identity_sha256,
                artifact_revision=artifact_revision,
                artifact_sha256=artifact_sha256,
            )
        except Exception as exc:
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_ARTIFACT_STALE", "exact source artifact binding failed") from exc
        if (
            source_manifest.artifact_id != artifact_id
            or source_manifest.revision != artifact_revision
            or source_manifest.sha256 != artifact_sha256
            or len(source_bytes) != byte_size
            or _sha_bytes(source_bytes) != artifact_sha256
            or source_bytes != decoded_text.encode("utf-8")
        ):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_ARTIFACT_STALE", "source artifact bytes differ from source context")

        selected_role = source_context.get("selected_source_role")
        selected_binding = source_context.get("selected_source_binding")
        if selected_role != "PROJECT_SOURCE_PRIMARY" or not isinstance(selected_binding, dict):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_SELECTED_BINDING_MISMATCH", "selected source role/binding invalid")
        if (
            selected_binding.get("artifact_id") != artifact_id
            or selected_binding.get("revision") != artifact_revision
            or selected_binding.get("sha256") != artifact_sha256
        ):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_SELECTED_BINDING_MISMATCH", "selected source differs from exact artifact")

        load_plan_sha256 = _require_sha(source_context.get("load_plan_sha256"), "source load_plan_sha256")
        permission_plan_sha256 = _require_sha(source_context.get("permission_plan_sha256"), "source permission_plan_sha256")
        binding_plan_sha256 = _require_sha(
            source_context.get("job_artifact_binding_plan_sha256"),
            "source job_artifact_binding_plan_sha256",
        )
        source_pack_pin = source_context.get("pack_pin")
        if not isinstance(source_pack_pin, dict):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_PACK_PIN_MISMATCH", "source context Pack pin missing")
        source_pack_job_id = source_pack_pin.get("job_id")
        source_pack_id = source_pack_pin.get("pack_id")
        source_pack_version = source_pack_pin.get("pack_version")
        source_pack_manifest_sha256 = _require_sha(source_pack_pin.get("pack_manifest_sha256"), "source Pack manifest SHA")
        if not all(isinstance(v, str) and v for v in (source_pack_job_id, source_pack_id, source_pack_version)):
            raise GeneralChatFormalPrepareError("SOURCE_CONTEXT_PACK_PIN_MISMATCH", "source context Pack pin identity invalid")

        return {
            "source_context": dict(source_context),
            "source_context_sha256": source_context_sha256,
            "source_ref_id": source_ref_id,
            "source_artifact_id": artifact_id,
            "source_artifact_identity_sha256": artifact_identity_sha256,
            "source_artifact_revision": artifact_revision,
            "source_artifact_sha256": artifact_sha256,
            "derivation_sha256": derivation_sha256,
            "selected_source_role": selected_role,
            "selected_source_binding_sha256": _sha(selected_binding),
            "source_load_plan_sha256": load_plan_sha256,
            "source_permission_plan_sha256": permission_plan_sha256,
            "source_job_artifact_binding_plan_sha256": binding_plan_sha256,
            "source_pack_pin": dict(source_pack_pin),
            "source_pack_pin_sha256": _sha(source_pack_pin),
            "question_sha256": content_sha256,
        }


    def validate_retry_after_confirmed_cancel_lineage_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        initiating_user_event_id: str,
        source_context_sha256: str | None,
        active_context_snapshot_sha256: str | None,
        predecessor_job_id: str,
        predecessor_job_bundle_binding: dict[str, Any],
        predecessor_web_formal_job_intake_binding: dict[str, Any],
        predecessor_cancellation_outcome_binding: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate one exact consumed-cancel predecessor for a fresh user Retry child.

        This never refunds, reopens, or replays the predecessor claim.  It only
        returns deterministic lineage provenance that may participate in a NEW
        initial Job identity.
        """
        if not isinstance(project_id, str) or not project_id:
            raise GeneralChatFormalPrepareError("RETRY_LINEAGE_INVALID", "project_id required", status_code=400)
        if not isinstance(chat_id, str) or not chat_id:
            raise GeneralChatFormalPrepareError("RETRY_LINEAGE_INVALID", "chat_id required", status_code=400)
        if not isinstance(initiating_user_event_id, str) or not initiating_user_event_id:
            raise GeneralChatFormalPrepareError(
                "RETRY_LINEAGE_INVALID", "initiating_user_event_id required", status_code=400
            )
        if not isinstance(predecessor_job_id, str) or not predecessor_job_id:
            raise GeneralChatFormalPrepareError("RETRY_LINEAGE_INVALID", "predecessor_job_id required", status_code=400)
        source_retry = isinstance(source_context_sha256, str)
        plain_retry = source_context_sha256 is None and isinstance(active_context_snapshot_sha256, str)
        if source_retry == plain_retry:
            raise GeneralChatFormalPrepareError(
                "RETRY_LINEAGE_INVALID",
                "Retry requires exactly one predecessor anchor: Source context or no-Source active context",
                status_code=409,
            )
        if source_retry:
            _require_sha(source_context_sha256, "source_context_sha256")
        else:
            _require_sha(active_context_snapshot_sha256, "active_context_snapshot_sha256")

        job_binding = _require_retry_binding(
            predecessor_job_bundle_binding, "predecessor_job_bundle_binding"
        )
        intake_binding = _require_retry_binding(
            predecessor_web_formal_job_intake_binding,
            "predecessor_web_formal_job_intake_binding",
        )
        cancellation_binding = _require_retry_binding(
            predecessor_cancellation_outcome_binding,
            "predecessor_cancellation_outcome_binding",
        )
        try:
            job_manifest, _job_raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=job_binding["artifact_identity_sha256"],
                artifact_revision=job_binding["artifact_revision"],
                artifact_sha256=job_binding["artifact_sha256"],
            )
            intake_manifest, _intake_raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=intake_binding["artifact_identity_sha256"],
                artifact_revision=intake_binding["artifact_revision"],
                artifact_sha256=intake_binding["artifact_sha256"],
            )
            cancellation_manifest, _cancel_raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=cancellation_binding["artifact_identity_sha256"],
                artifact_revision=cancellation_binding["artifact_revision"],
                artifact_sha256=cancellation_binding["artifact_sha256"],
            )
            predecessor_job_record = self.ledger.load_record(job_binding)
            predecessor_intake = self.ledger.load_record(intake_binding)
            cancellation = self.ledger.load_record(cancellation_binding)
        except (FormalModelJobError, R009OpaqueArtifactError) as exc:
            raise GeneralChatFormalPrepareError(
                "RETRY_LINEAGE_STALE_OR_TAMPERED", str(exc), status_code=409
            ) from exc
        if any(
            manifest.job_id != predecessor_job_id
            for manifest in (job_manifest, intake_manifest, cancellation_manifest)
        ):
            raise GeneralChatFormalPrepareError(
                "RETRY_LINEAGE_AUTHORITY_MISMATCH",
                "retry predecessor Artifact manifest belongs to another Job",
                status_code=409,
            )

        predecessor_job_bundle = predecessor_job_record.get("job_bundle")
        predecessor_job_bundle_sha = predecessor_job_record.get("job_bundle_sha256")
        if (
            predecessor_job_record.get("schema") != "RUNTIME_IMMUTABLE_JOB_BUNDLE_BINDING_V1"
            or predecessor_job_record.get("job_id") != predecessor_job_id
            or not isinstance(predecessor_job_bundle, dict)
            or predecessor_job_bundle.get("job_id") != predecessor_job_id
            or predecessor_job_bundle_sha != _sha(predecessor_job_bundle)
        ):
            raise GeneralChatFormalPrepareError(
                "RETRY_PREDECESSOR_JOB_MISMATCH",
                "predecessor JobBundle identity/currentness is invalid",
                status_code=409,
            )
        if source_retry:
            if predecessor_job_bundle.get("source_context_sha256") != source_context_sha256:
                raise GeneralChatFormalPrepareError(
                    "RETRY_PREDECESSOR_JOB_MISMATCH",
                    "predecessor JobBundle is not the exact same source-grounded Job",
                    status_code=409,
                )
        else:
            if (
                predecessor_job_bundle.get("source_context_sha256") is not None
                or predecessor_job_bundle.get("active_context_snapshot_sha256")
                    != active_context_snapshot_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "RETRY_PREDECESSOR_JOB_MISMATCH",
                    "predecessor JobBundle is not the exact same no-Source active-context Job",
                    status_code=409,
                )

        if (
            predecessor_intake.get("schema") != "WEB_FORMAL_JOB_INTAKE_BINDING_V1"
            or predecessor_intake.get("job_id") != predecessor_job_id
            or predecessor_intake.get("job_bundle_sha256") != predecessor_job_bundle_sha
            or predecessor_intake.get("project_id") != project_id
            or predecessor_intake.get("chat_id") != chat_id
            or predecessor_intake.get("initiating_user_event_id") != initiating_user_event_id
            or predecessor_intake.get("accepted_head_event_id") != initiating_user_event_id
        ):
            raise GeneralChatFormalPrepareError(
                "RETRY_PREDECESSOR_INTAKE_MISMATCH",
                "predecessor Web intake does not bind the exact current Project/Chat/USER_MESSAGE",
                status_code=409,
            )

        if (
            cancellation.get("schema") != "RUNTIME_MODEL_ATTEMPT_CANCELLATION_OUTCOME_RECEIPT_V1"
            or cancellation.get("job_id") != predecessor_job_id
            or cancellation.get("job_bundle_sha256") != predecessor_job_bundle_sha
            or cancellation.get("attempt_index") != 1
            or cancellation.get("claim_state") != "CLAIMED_CONSUMED"
            or cancellation.get("cancellation_code") != "ATTEMPT_CLAIMED_CANCELLED_BY_USER"
            or cancellation.get("cancellation_winner") not in {
                "CANCEL_BEFORE_REQUEST", "CANCEL_ACTIVE_STREAM"
            }
            or cancellation.get("partial_output_persisted") is not False
            or cancellation.get("retry_allowed") is not False
            or cancellation.get("automatic_replay_allowed") is not False
            or cancellation.get("claim_refund_allowed") is not False
        ):
            raise GeneralChatFormalPrepareError(
                "RETRY_PREDECESSOR_NOT_CONFIRMED_CANCEL",
                "Retry requires one exact consumed-claim confirmed-cancellation receipt",
                status_code=409,
            )

        intake_record_id = predecessor_intake.get("web_formal_job_intake_binding_id")
        cancellation_record_id = cancellation.get("model_attempt_cancellation_outcome_receipt_id")
        expected_identities = {
            "job": _sha_bytes(f"M002:JOB_BUNDLE:{predecessor_job_id}".encode("utf-8")),
            "intake": _sha_bytes(f"M002:WEB_INTAKE:{intake_record_id}".encode("utf-8")),
            "cancellation": _sha_bytes(
                f"M002:ATTEMPT_CANCELLATION_OUTCOME:{cancellation_record_id}".encode("utf-8")
            ),
        }
        if (
            job_binding["artifact_identity_sha256"] != expected_identities["job"]
            or intake_binding["artifact_identity_sha256"] != expected_identities["intake"]
            or cancellation_binding["artifact_identity_sha256"] != expected_identities["cancellation"]
        ):
            raise GeneralChatFormalPrepareError(
                "RETRY_LINEAGE_AUTHORITY_MISMATCH",
                "retry predecessor binding is not the producer-authoritative Artifact identity",
                status_code=409,
            )

        lineage = {
            "schema": _RETRY_LINEAGE_SCHEMA,
            "retry_kind": _RETRY_LINEAGE_KIND,
            "predecessor_job_id": predecessor_job_id,
            "predecessor_job_bundle_sha256": predecessor_job_bundle_sha,
            "predecessor_job_bundle_binding": job_binding,
            "predecessor_web_formal_job_intake_binding": intake_binding,
            "predecessor_cancellation_outcome_receipt_id": cancellation.get(
                "model_attempt_cancellation_outcome_receipt_id"
            ),
            "predecessor_cancellation_outcome_binding": cancellation_binding,
            "predecessor_cancellation_winner": cancellation.get("cancellation_winner"),
        }
        return _normalize_retry_lineage(lineage)


    def _runtime_contract_manifest(
        self,
        *,
        adoption_record_sha256: str,
        pack_action_sha256: str,
        streaming: bool = False,
    ) -> dict[str, Any]:
        import universal_runtime.core.artifact_store as artifact_store_module
        import universal_runtime.core.formal_model_job as formal_job_module
        import universal_runtime.core.formal_model_live_composition as live_module
        import universal_runtime.core.human_decision_authority as human_module
        import universal_runtime.core.job_authority as authority_module
        import universal_runtime.core.model_catalog as catalog_module
        import universal_runtime.core.model_policy as policy_module
        import universal_runtime.core.provider_execution_config as provider_module
        import universal_runtime.packs.registry as pack_registry_module
        final_only_deepseek_module = None
        if streaming and self.model_target == DEFAULT_DEEPSEEK_TARGET:
            import universal_runtime.models.deepseek as final_only_deepseek_module

        if not isinstance(streaming, bool):
            raise GeneralChatFormalPrepareError("INVALID_STREAMING_MODE", "streaming must be boolean", status_code=400)
        adapter_module_name = (
            P1_S2_DEEPSEEK_STREAMING_ADAPTER_MODULE
            if streaming and self.model_target == DEFAULT_DEEPSEEK_TARGET
            else self.model_target.adapter_module_name
        )
        adapter_relative_path = (
            P1_S2_DEEPSEEK_STREAMING_ADAPTER_RELATIVE_PATH
            if streaming and self.model_target == DEFAULT_DEEPSEEK_TARGET
            else self.model_target.adapter_relative_path
        )
        adapter_module = importlib.import_module(adapter_module_name)
        source_bindings = {
            "artifact_store.py": _module_file_sha(artifact_store_module.__file__, "artifact_store"),
            "formal_model_job.py": _module_file_sha(formal_job_module.__file__, "formal_model_job"),
            "formal_model_live_composition.py": _module_file_sha(live_module.__file__, "formal_model_live_composition"),
            "human_decision_authority.py": _module_file_sha(human_module.__file__, "human_decision_authority"),
            "job_authority.py": _module_file_sha(authority_module.__file__, "job_authority"),
            "model_catalog.py": _module_file_sha(catalog_module.__file__, "model_catalog"),
            "model_policy.py": _module_file_sha(policy_module.__file__, "model_policy"),
            "provider_execution_config.py": _module_file_sha(provider_module.__file__, "provider_execution_config"),
            "provider_adapter:" + adapter_relative_path: _module_file_sha(adapter_module.__file__, "provider adapter"),
            **(
                {
                    "streaming_dependency:src/universal_runtime/models/deepseek.py": _module_file_sha(
                        final_only_deepseek_module.__file__,
                        "streaming final-only DeepSeek dependency",
                    )
                }
                if final_only_deepseek_module is not None
                else {}
            ),
            "packs/registry.py": _module_file_sha(pack_registry_module.__file__, "pack registry"),
            "config/model_profiles.yaml": _file_sha(self.runtime_home / "config/model_profiles.yaml"),
            "web_general_chat_formal_prepare.py": _file_sha(Path(__file__)),
        }
        return {
            "schema": "RUNTIME_S1_GENERAL_CHAT_FORMAL_CONTRACT_MANIFEST_V1",
            "contract_revision": 3 if streaming else 1,
            "formal_contract_basis": (
                "P1_S3_NARROW_STOP_CANCELLATION"
                if streaming
                else "M002_R007_FIRST_LAWFUL_GENERAL_CHAT_SLICE"
            ),
            "source_bindings": source_bindings,
            "model_catalog_adoption_record_sha256": adoption_record_sha256,
            "pack_action_sha256": pack_action_sha256,
            "first_slice_budget": dict(FIRST_SLICE_BUDGET),
            "provider_rules": {
                "http_method": "POST",
                "stream": streaming,
                "transport_retries_max": 0,
                "trust_env": False,
                "fallback": False,
                "proxy_mode": self.model_target.proxy_mode,
            },
            "phase_a_ceiling": {
                "credential_read": False,
                "network": False,
                "model_call": False,
                "grant_creation": False,
                "attempt_claim": False,
            },
        }

    def _validate_web_active_context_snapshot_v1(
        self,
        *,
        active_context_snapshot: dict[str, Any],
        active_context_snapshot_sha256: str,
        chat_id: str,
        initiating_user_event_id: str,
        initiating_content_sha256: str,
        accepted_chat_revision: int,
        accepted_head_event_id: str,
    ) -> dict[str, Any]:
        if not isinstance(active_context_snapshot, dict):
            raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_REQUIRED", "active context snapshot object required")
        try:
            observed_sha = validate_active_context_snapshot(active_context_snapshot)
        except WebConversationGraphError as exc:
            raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_INVALID", f"{exc.code}: {exc.message}") from exc
        if observed_sha != active_context_snapshot_sha256:
            raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_SHA_MISMATCH", "active context snapshot SHA differs")
        if (
            active_context_snapshot.get("chat_id") != chat_id
            or active_context_snapshot.get("chat_revision") != accepted_chat_revision
            or active_context_snapshot.get("head_event_id") != accepted_head_event_id
        ):
            raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_CHAT_MISMATCH", "active context chat revision/head differs")
        ordered = active_context_snapshot.get("ordered_messages")
        if not isinstance(ordered, list) or not ordered:
            raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_EMPTY", "active context snapshot is empty")
        current = ordered[-1]
        if (
            current.get("event_id") != initiating_user_event_id
            or current.get("role") != "user"
            or current.get("content_sha256") != initiating_content_sha256
        ):
            raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_CURRENT_EVENT_MISMATCH", "active context head differs from initiating USER event")
        for item in ordered:
            artifact_id = item.get("artifact_id")
            artifact_revision = item.get("artifact_revision")
            artifact_sha = item.get("artifact_sha256")
            if (
                not isinstance(artifact_id, str)
                or isinstance(artifact_revision, bool)
                or not isinstance(artifact_revision, int)
                or artifact_revision < 1
                or not isinstance(artifact_sha, str)
                or _SHA_RE.fullmatch(artifact_sha) is None
            ):
                raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_EVENT_BINDING", "exact event Artifact binding required")
            try:
                manifest = self.store.assert_current(artifact_id, artifact_revision, artifact_sha)
                raw = Path(manifest.path).read_bytes()
                if _sha_bytes(raw) != artifact_sha:
                    raise ArtifactCurrentnessError("event Artifact bytes differ")
                event = json.loads(raw.decode("utf-8"))
            except (ArtifactCurrentnessError, UnicodeError, json.JSONDecodeError) as exc:
                raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_EVENT_STALE", "active context event Artifact is stale or invalid") from exc
            expected_type = "USER_MESSAGE" if item.get("role") == "user" else "ASSISTANT_MESSAGE"
            expected_actor = "USER" if item.get("role") == "user" else "ASSISTANT"
            if (
                event.get("event_id") != item.get("event_id")
                or event.get("chat_id") != chat_id
                or event.get("event_type") != expected_type
                or event.get("actor_class") != expected_actor
                or event.get("parent_event_id") != item.get("parent_event_id")
                or event.get("content") != item.get("content")
                or event.get("content_sha256") != item.get("content_sha256")
            ):
                raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_EVENT_MISMATCH", "active context event differs from exact Artifact")
        return {
            "snapshot": active_context_snapshot,
            "snapshot_sha256": observed_sha,
            "active_ancestry_sha256": active_context_snapshot.get("active_ancestry_sha256"),
        }

    def prepare_job_bundle(
        self,
        *,
        project_id: str,
        chat_id: str,
        initiating_user_event: dict[str, Any],
        initiating_user_event_binding: dict[str, Any],
        accepted_chat_revision: int,
        accepted_head_event_id: str,
        source_context: dict[str, Any] | None = None,
        source_context_sha256: str | None = None,
        active_context_snapshot: dict[str, Any] | None = None,
        active_context_snapshot_sha256: str | None = None,
        project_memory_context: dict[str, Any] | None = None,
        project_memory_context_sha256: str | None = None,
        project_memory_state_guard: dict[str, Any] | None = None,
        project_memory_state_guard_sha256: str | None = None,
        personal_context: dict[str, Any] | None = None,
        personal_context_sha256: str | None = None,
        streaming: bool = False,
        retry_lineage: dict[str, Any] | None = None,
    ) -> GeneralChatPhaseAPreparedJob:
        if not isinstance(streaming, bool):
            raise GeneralChatFormalPrepareError("INVALID_STREAMING_MODE", "streaming must be boolean", status_code=400)
        event_id = initiating_user_event.get("event_id")
        if not isinstance(project_id, str) or not project_id:
            raise GeneralChatFormalPrepareError("INVALID_INPUT", "project_id required", status_code=400)
        if not isinstance(chat_id, str) or not chat_id:
            raise GeneralChatFormalPrepareError("INVALID_INPUT", "chat_id required", status_code=400)
        if (
            not isinstance(event_id, str)
            or initiating_user_event.get("event_type") != "USER_MESSAGE"
            or initiating_user_event.get("actor_class") != "USER"
            or initiating_user_event.get("chat_id") != chat_id
            or accepted_head_event_id != event_id
        ):
            raise GeneralChatFormalPrepareError("INVALID_USER_EVENT", "exact current USER_MESSAGE head required")
        if isinstance(accepted_chat_revision, bool) or not isinstance(accepted_chat_revision, int) or accepted_chat_revision < 1:
            raise GeneralChatFormalPrepareError("INVALID_CHAT_REVISION", "positive accepted_chat_revision required")

        content_sha = initiating_user_event.get("content_sha256")
        if not isinstance(content_sha, str) or _SHA_RE.fullmatch(content_sha) is None:
            raise GeneralChatFormalPrepareError("INVALID_USER_EVENT", "USER_MESSAGE content SHA invalid")
        event_artifact_id = initiating_user_event_binding.get("artifact_id")
        event_revision = initiating_user_event_binding.get("revision")
        event_sha = initiating_user_event_binding.get("sha256")
        if (
            not isinstance(event_artifact_id, str)
            or isinstance(event_revision, bool)
            or not isinstance(event_revision, int)
            or event_revision < 1
            or not isinstance(event_sha, str)
            or _SHA_RE.fullmatch(event_sha) is None
        ):
            raise GeneralChatFormalPrepareError("INVALID_USER_EVENT_BINDING", "exact legacy event binding required")
        event_identity_sha = legacy_artifact_identity_sha256(event_artifact_id)
        try:
            project_instruction_facts = WebContinuityService(self.store).read_project_instructions_current(
                project_id=project_id,
            )
        except WebContinuityError as exc:
            raise GeneralChatFormalPrepareError(
                "PROJECT_INSTRUCTIONS_CURRENTNESS",
                f"{exc.code}: {exc.message}",
                status_code=exc.status_code,
            ) from exc
        project_instruction_binding = project_instruction_facts["project_instruction_binding"]
        project_instructions_sha256 = project_instruction_binding["sha256"]
        active_context_facts = None
        if active_context_snapshot is not None or active_context_snapshot_sha256 is not None:
            if not isinstance(active_context_snapshot_sha256, str) or _SHA_RE.fullmatch(active_context_snapshot_sha256) is None:
                raise GeneralChatFormalPrepareError("ACTIVE_CONTEXT_SHA_REQUIRED", "active context snapshot SHA required")
            active_context_facts = self._validate_web_active_context_snapshot_v1(
                active_context_snapshot=active_context_snapshot,
                active_context_snapshot_sha256=active_context_snapshot_sha256,
                chat_id=chat_id,
                initiating_user_event_id=event_id,
                initiating_content_sha256=content_sha,
                accepted_chat_revision=accepted_chat_revision,
                accepted_head_event_id=accepted_head_event_id,
            )
        source_facts = self._validate_library_source_context(
            source_context=source_context,
            source_context_sha256=source_context_sha256,
            project_id=project_id,
            chat_id=chat_id,
            event_id=event_id,
            content_sha256=content_sha,
            initiating_user_event_binding=initiating_user_event_binding,
        )
        memory_service = ProjectMemoryService(self.store)
        memory_guard_facts = None
        if project_memory_state_guard is not None or project_memory_state_guard_sha256 is not None:
            try:
                memory_guard_facts = memory_service.validate_state_guard_current(
                    project_id=project_id,
                    project_memory_state_guard=project_memory_state_guard,
                    project_memory_state_guard_sha256=project_memory_state_guard_sha256,
                )
            except ProjectMemoryError as exc:
                raise GeneralChatFormalPrepareError(
                    "PROJECT_MEMORY_STATE_CURRENTNESS",
                    f"{exc.code}: {exc.message}",
                    status_code=exc.status_code,
                ) from exc

        try:
            memory_facts = memory_service.validate_context_current(
                project_id=project_id,
                project_memory_context=project_memory_context,
                project_memory_context_sha256=project_memory_context_sha256,
            )
        except ProjectMemoryError as exc:
            raise GeneralChatFormalPrepareError(
                "PROJECT_MEMORY_CONTEXT_CURRENTNESS",
                f"{exc.code}: {exc.message}",
                status_code=exc.status_code,
            ) from exc

        if memory_facts is not None and memory_guard_facts is None:
            raise GeneralChatFormalPrepareError(
                "PROJECT_MEMORY_STATE_GUARD_REQUIRED",
                "Memory context requires an exact Project Memory state guard",
                status_code=409,
            )
        if memory_guard_facts is not None and project_memory_context is None:
            if memory_guard_facts.get("active_memory_count") != 0:
                raise GeneralChatFormalPrepareError(
                    "PROJECT_MEMORY_CONTEXT_REQUIRED",
                    "ACTIVE Project Memory requires an exact non-empty Memory context",
                    status_code=409,
                )
        personal_context_facts = validate_non_authority_personal_context_snapshot(
            personal_context=personal_context,
            personal_context_sha256=personal_context_sha256,
        )
        project_history_context = None
        project_history_context_sha256 = None
        if active_context_facts is not None:
            try:
                history_projection = WebContinuityService(self.store).build_project_history_context(
                    project_id=project_id,
                    exclude_chat_id=chat_id,
                    max_bytes=PROJECT_HISTORY_CONTEXT_MAX_BYTES,
                )
            except WebContinuityError as exc:
                raise GeneralChatFormalPrepareError(
                    "PROJECT_HISTORY_CONTEXT_CURRENTNESS",
                    f"{exc.code}: {exc.message}",
                    status_code=exc.status_code,
                ) from exc
            project_history_context = history_projection.get("project_history_context")
            project_history_context_sha256 = history_projection.get("project_history_context_sha256")

        normalized_retry_lineage = None
        if retry_lineage is not None:
            if source_facts is None and active_context_facts is None:
                raise GeneralChatFormalPrepareError(
                    "RETRY_LINEAGE_INVALID",
                    "Retry-after-cancel requires exact Source context or exact no-Source active context",
                    status_code=409,
                )
            normalized_retry_lineage = _normalize_retry_lineage(retry_lineage)
            validated_retry_lineage = self.validate_retry_after_confirmed_cancel_lineage_v1(
                project_id=project_id,
                chat_id=chat_id,
                initiating_user_event_id=event_id,
                source_context_sha256=(
                    source_facts["source_context_sha256"] if source_facts is not None else None
                ),
                active_context_snapshot_sha256=(
                    active_context_facts["snapshot_sha256"]
                    if source_facts is None and active_context_facts is not None
                    else None
                ),
                predecessor_job_id=normalized_retry_lineage["predecessor_job_id"],
                predecessor_job_bundle_binding=normalized_retry_lineage[
                    "predecessor_job_bundle_binding"
                ],
                predecessor_web_formal_job_intake_binding=normalized_retry_lineage[
                    "predecessor_web_formal_job_intake_binding"
                ],
                predecessor_cancellation_outcome_binding=normalized_retry_lineage[
                    "predecessor_cancellation_outcome_binding"
                ],
            )
            if validated_retry_lineage != normalized_retry_lineage:
                raise GeneralChatFormalPrepareError(
                    "RETRY_LINEAGE_STALE_OR_TAMPERED",
                    "retry lineage changed during exact validation",
                    status_code=409,
                )

        adoption = self._validate_adoption()
        promoted_pack = self.pack_registry.resolve_promoted_pack(PACK_ID, PACK_VERSION)
        if (
            promoted_pack.content_manifest_sha256 != adoption.get("target_pack_content_manifest_sha256")
            or promoted_pack.promotion_receipt_sha256 != adoption.get("target_pack_promotion_receipt_sha256")
        ):
            raise GeneralChatFormalPrepareError("PACK_ADOPTION_STALE", "promoted Pack differs from exact adoption")
        if source_facts is not None:
            source_pack_pin = source_facts["source_pack_pin"]
            if (
                source_pack_pin.get("pack_id") != PACK_ID
                or source_pack_pin.get("pack_version") != PACK_VERSION
                or source_pack_pin.get("pack_manifest_sha256") != promoted_pack.manifest_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "SOURCE_CONTEXT_PACK_PIN_MISMATCH",
                    "source context predecessor Pack pin differs from current promoted Pack",
                )

        content_root = Path(promoted_pack.content_root or "")
        action_path = content_root / "actions" / "general_text_reply.action.json"
        prompt_path = content_root / "prompts" / "general_text_reply.system.md"
        output_schema_path = content_root / "schemas" / "general_text_reply_output.schema.json"
        if not action_path.is_file() or not prompt_path.is_file() or not output_schema_path.is_file():
            raise GeneralChatFormalPrepareError("PACK_CONTENT_STALE", "promoted General Chat content incomplete")

        action_sha = _file_sha(action_path)
        if action_sha != adoption.get("target_action_sha256"):
            raise GeneralChatFormalPrepareError("PACK_ACTION_STALE", "General Chat action differs from adoption")
        try:
            action = json.loads(action_path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GeneralChatFormalPrepareError("PACK_ACTION_STALE", "General Chat action invalid") from exc
        if (
            action.get("pack_id") != PACK_ID
            or action.get("pack_version") != PACK_VERSION
            or action.get("action_id") != ACTION_ID
            or action.get("logical_model_profile_request", {}).get("allowed_profiles") != [LOGICAL_PROFILE]
            or action.get("logical_model_profile_request", {}).get("default_profile") != LOGICAL_PROFILE
        ):
            raise GeneralChatFormalPrepareError("PACK_ACTION_STALE", "General Chat action/profile mismatch")

        decision = select_model_profile(
            ModelDecisionRequest(
                task=TaskRequirement(
                    task_kind=TaskKind.GENERAL,
                    reasoning_level=ReasoningLevel.HIGH,
                    risk_level=RiskLevel.LOW,
                    structured_output=False,
                ),
                selection_mode=ModelSelectionMode.AUTO_RECOMMENDED,
                allowed_profiles=(LOGICAL_PROFILE,),
            )
        )
        if decision.selected_profile != LOGICAL_PROFILE:
            raise GeneralChatFormalPrepareError("MODEL_POLICY_MISMATCH", "logical profile differs from Pack action")

        catalog_path = self.runtime_home / self.model_target.catalog_rel
        if _file_sha(catalog_path) != adoption.get("catalog_file_sha256"):
            raise GeneralChatFormalPrepareError("MODELCATALOG_STALE", "catalog file differs from adoption")
        try:
            catalog_data = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GeneralChatFormalPrepareError("MODELCATALOG_STALE", "catalog invalid") from exc
        catalog = _catalog_from_json(catalog_data)
        if catalog.catalog_sha256 != adoption.get("catalog_semantic_sha256"):
            raise GeneralChatFormalPrepareError("MODELCATALOG_STALE", "catalog semantic SHA differs from adoption")
        resolution = resolve_model_execution(
            ModelResolutionRequest(
                decision=decision,
                update_mode=ModelUpdateMode.STRICT_PIN,
                pinned_entry_id=self.model_target.model_entry_id,
                allowed_providers=(self.model_target.provider,),
            ),
            catalog,
        )
        if (
            resolution.model_entry_id != self.model_target.model_entry_id
            or resolution.provider != self.model_target.provider
            or resolution.model != self.model_target.model
        ):
            raise GeneralChatFormalPrepareError("MODEL_RESOLUTION_MISMATCH", "exact adopted model did not resolve")

        try:
            versions = {
                "httpx": importlib.metadata.version("httpx"),
                "openai": importlib.metadata.version("openai"),
            }
        except importlib.metadata.PackageNotFoundError as exc:
            raise GeneralChatFormalPrepareError("TRANSPORT_DEPENDENCY_MISSING", str(exc)) from exc

        provider_module = importlib.import_module("universal_runtime.core.provider_execution_config")
        provider_module_sha = _file_sha(Path(provider_module.__file__ or ""))
        if self.model_target == DEFAULT_DEEPSEEK_TARGET and provider_module_sha != P1_S2_PROVIDER_EXECUTION_CONFIG_MODULE_SHA256:
            raise GeneralChatFormalPrepareError(
                "PROVIDER_CONFIG_CURRENTNESS",
                "provider_execution_config.py differs from the exact P1-S2 candidate source",
            )

        if streaming and self.model_target == DEFAULT_DEEPSEEK_TARGET:
            final_only_dependency_module = importlib.import_module(DEFAULT_DEEPSEEK_TARGET.adapter_module_name)
            final_only_dependency_sha = _file_sha(Path(final_only_dependency_module.__file__ or ""))
            if final_only_dependency_sha != P1_S2_DEEPSEEK_FINAL_ONLY_DEPENDENCY_SHA256:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_DEPENDENCY_CURRENTNESS",
                    "final-only DeepSeek helper dependency differs from the exact streaming contract",
                )
            adapter_relative_path = P1_S2_DEEPSEEK_STREAMING_ADAPTER_RELATIVE_PATH
            adapter_module_name = P1_S2_DEEPSEEK_STREAMING_ADAPTER_MODULE
            expected_adapter_sha = P1_S3_DEEPSEEK_STREAMING_ADAPTER_SHA256
            if versions != {"httpx": P1_S3_HTTPX_VERSION, "openai": P1_S3_OPENAI_VERSION}:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_SDK_CURRENTNESS",
                    "installed openai/httpx versions differ from the exact P1-S3 candidate",
                )
            provider_revision = 2
            provider_stream = True
            expected_provider_config_sha = None
        else:
            adapter_relative_path = self.model_target.adapter_relative_path
            adapter_module_name = self.model_target.adapter_module_name
            expected_adapter_sha = R004_DEEPSEEK_ADAPTER_SHA256 if self.model_target == DEFAULT_DEEPSEEK_TARGET else None
            provider_revision = 1
            provider_stream = False
            expected_provider_config_sha = R004_DEEPSEEK_PROVIDER_EXECUTION_CONFIG_SHA256 if self.model_target == DEFAULT_DEEPSEEK_TARGET else None

        adapter_module = importlib.import_module(adapter_module_name)
        adapter_sha = _file_sha(Path(adapter_module.__file__ or ""))
        if expected_adapter_sha is not None and adapter_sha != expected_adapter_sha:
            raise GeneralChatFormalPrepareError(
                "PROVIDER_ADAPTER_CURRENTNESS",
                "DeepSeek adapter differs from the exact bound source for this execution mode",
            )

        proxy_sha = self.model_target.proxy_config_sha256
        provider_config = ProviderExecutionConfig.create(
            revision=provider_revision,
            provider=self.model_target.provider,
            resolved_model_entry_id=resolution.model_entry_id,
            model_resolution_sha256=resolution.resolution_sha256,
            endpoint_origin=self.model_target.endpoint_origin,
            api_route=self.model_target.api_route,
            adapter_relative_path=adapter_relative_path,
            adapter_sha256=adapter_sha,
            transport_client_class=self.model_target.transport_client_class,
            transport_package_versions=versions,
            credential_ref_id=self.model_target.credential_ref_id,
            credential_ref_class=self.model_target.credential_ref_class,
            stream=provider_stream,
            proxy_mode=self.model_target.proxy_mode,
            proxy_config_sha256=proxy_sha,
        )
        if expected_provider_config_sha is not None and provider_config.semantic_sha256 != expected_provider_config_sha:
            raise GeneralChatFormalPrepareError(
                "PROVIDER_CONFIG_CURRENTNESS",
                "DeepSeek ProviderExecutionConfig differs from the exact bound configuration",
            )

        runtime_contract = self._runtime_contract_manifest(
            adoption_record_sha256=self.model_target.adoption_record_sha256,
            pack_action_sha256=action_sha,
            streaming=streaming,
        )
        runtime_contract_sha = _sha(runtime_contract)
        runtime_execution_identity_sha = _sha(runtime_contract["source_bindings"])

        job_identity = {
            "namespace": "UR_S1_GENERAL_CHAT_JOB_ID_V1",
            "project_id": project_id,
            "project_instruction_artifact_id": project_instruction_binding["artifact_id"],
            "project_instruction_revision": project_instruction_binding["revision"],
            "project_instructions_sha256": project_instructions_sha256,
            "chat_id": chat_id,
            "initiating_user_event_id": event_id,
            "initiating_user_event_artifact_identity_sha256": event_identity_sha,
            "initiating_user_event_artifact_revision": event_revision,
            "initiating_user_event_artifact_sha256": event_sha,
            "initiating_content_sha256": content_sha,
            "accepted_chat_revision": accepted_chat_revision,
            "accepted_head_event_id": accepted_head_event_id,
            "pack_content_manifest_sha256": promoted_pack.content_manifest_sha256,
            "pack_promotion_receipt_sha256": promoted_pack.promotion_receipt_sha256,
            "pack_action_sha256": action_sha,
            "runtime_contract_manifest_sha256": runtime_contract_sha,
            "model_resolution_sha256": resolution.resolution_sha256,
            "provider_execution_config_sha256": provider_config.semantic_sha256,
            "model_catalog_adoption_record_sha256": self.model_target.adoption_record_sha256,
        }
        if active_context_facts is not None:
            job_identity["active_context_snapshot_sha256"] = active_context_facts["snapshot_sha256"]
            job_identity["active_ancestry_sha256"] = active_context_facts["active_ancestry_sha256"]
        if memory_guard_facts is not None:
            job_identity["project_memory_state_guard_sha256"] = project_memory_state_guard_sha256
        if memory_facts is not None:
            job_identity["project_memory_context_sha256"] = project_memory_context_sha256
        if personal_context_facts is not None:
            job_identity["personal_context_sha256"] = personal_context_sha256
        if project_history_context is not None:
            job_identity["project_history_context_sha256"] = project_history_context_sha256
        if source_facts is not None:
            job_identity.update({
                "source_context_sha256": source_facts["source_context_sha256"],
                "source_ref_id": source_facts["source_ref_id"],
                "source_artifact_identity_sha256": source_facts["source_artifact_identity_sha256"],
                "source_artifact_revision": source_facts["source_artifact_revision"],
                "source_artifact_sha256": source_facts["source_artifact_sha256"],
                "source_derivation_sha256": source_facts["derivation_sha256"],
                "source_load_plan_sha256": source_facts["source_load_plan_sha256"],
                "source_permission_plan_sha256": source_facts["source_permission_plan_sha256"],
                "source_job_artifact_binding_plan_sha256": source_facts["source_job_artifact_binding_plan_sha256"],
                "source_predecessor_pack_pin_sha256": source_facts["source_pack_pin_sha256"],
            })
        if normalized_retry_lineage is not None:
            job_identity["retry_lineage_sha256"] = _sha(normalized_retry_lineage)
        job_id = "JOB_" + _sha(job_identity)

        active_context_binding = None
        if active_context_facts is not None:
            active_context_binding = _persist_exact_json(
                self.store,
                kind="WEB_ACTIVE_CONTEXT_INPUT",
                job_id=job_id,
                record=active_context_facts["snapshot"],
            )
            expected_active_context_artifact_sha = _sha(active_context_facts["snapshot"])
            if active_context_binding["artifact_sha256"] != expected_active_context_artifact_sha:
                raise GeneralChatFormalPrepareError(
                    "ACTIVE_CONTEXT_PERSISTENCE_MISMATCH",
                    "persisted active context Artifact bytes differ from the exact validated Web snapshot",
                )

        source_context_binding = None
        if source_facts is not None:
            source_context_binding = _persist_exact_json(
                self.store,
                kind="LIBRARY_SOURCE_CONTEXT_INPUT",
                job_id=job_id,
                record=source_facts["source_context"],
            )
            if source_context_binding["artifact_sha256"] != source_facts["source_context_sha256"]:
                raise GeneralChatFormalPrepareError(
                    "SOURCE_CONTEXT_PERSISTENCE_MISMATCH",
                    "persisted source context differs from exact predecessor context",
                )

        project_memory_state_guard_binding = None
        if memory_guard_facts is not None:
            project_memory_state_guard_binding = _persist_exact_json(
                self.store,
                kind="PROJECT_MEMORY_STATE_GUARD_INPUT",
                job_id=job_id,
                record=memory_guard_facts,
            )
            if project_memory_state_guard_binding["artifact_sha256"] != project_memory_state_guard_sha256:
                raise GeneralChatFormalPrepareError(
                    "PROJECT_MEMORY_STATE_GUARD_PERSISTENCE_MISMATCH",
                    "persisted Project Memory state guard differs from exact current state",
                )

        project_memory_context_binding = None
        if memory_facts is not None:
            project_memory_context_binding = _persist_exact_json(
                self.store,
                kind="PROJECT_MEMORY_CONTEXT_INPUT",
                job_id=job_id,
                record=memory_facts,
            )
            if project_memory_context_binding["artifact_sha256"] != project_memory_context_sha256:
                raise GeneralChatFormalPrepareError(
                    "PROJECT_MEMORY_CONTEXT_PERSISTENCE_MISMATCH",
                    "persisted Project Memory context differs from exact current context",
                )

        personal_context_binding = None
        if personal_context_facts is not None:
            personal_context_binding = _persist_exact_json(
                self.store,
                kind="NON_AUTHORITY_USER_PERSONAL_CONTEXT_INPUT",
                job_id=job_id,
                record=personal_context_facts,
            )
            if personal_context_binding["artifact_sha256"] != personal_context_sha256:
                raise GeneralChatFormalPrepareError(
                    "PERSONAL_CONTEXT_PERSISTENCE_MISMATCH",
                    "persisted Personal Context differs from exact request snapshot",
                )

        project_history_context_binding = None
        if project_history_context is not None:
            project_history_context_binding = _persist_exact_json(
                self.store,
                kind="PROJECT_HISTORY_CONTEXT_INPUT",
                job_id=job_id,
                record=project_history_context,
            )
            if project_history_context_binding["artifact_sha256"] != project_history_context_sha256:
                raise GeneralChatFormalPrepareError(
                    "PROJECT_HISTORY_CONTEXT_PERSISTENCE_MISMATCH",
                    "persisted Project History context differs from exact request snapshot",
                )

        pack_pin_obj = JobPackPin.from_resolved_pack(job_id, promoted_pack)
        pack_pin = pack_pin_obj.to_dict()
        permission_obj = JobFilesystemPermissionPlan.from_job_pin(
            pack_pin_obj,
            allowed_read_roots=(content_root,),
        )
        prompt_sha = _file_sha(prompt_path)
        prompt_bytes = prompt_path.stat().st_size
        load_plan_obj = LoadPlan.from_inputs(
            plan_id="S1_GENERAL_CHAT_SYSTEM_PROMPT_V1",
            project_root=str(content_root),
            allowed_roots=(str(content_root),),
            required_inputs=(
                LoadInput(
                    reference="prompts/general_text_reply.system.md",
                    role="system_prompt",
                    expected_sha256=prompt_sha,
                    parse_mode="bytes",
                    persistence_class=PersistenceClass.EPHEMERAL,
                    required=True,
                    byte_budget=prompt_bytes,
                ),
            ),
            execution_budget=1,
            load_budget=prompt_bytes,
        )
        authorized_load = permission_obj.authorize_load_plan(pack_pin_obj, load_plan_obj)
        permission_plan = permission_obj.to_dict()
        load_plan = {
            "plan_id": load_plan_obj.plan_id,
            "project_root": load_plan_obj.project_root,
            "allowed_roots": list(load_plan_obj.allowed_roots),
            "required_inputs": [
                {
                    "reference": item.reference,
                    "role": item.role,
                    "expected_sha256": item.expected_sha256,
                    "parse_mode": item.parse_mode,
                    "persistence_class": str(item.persistence_class),
                    "required": item.required,
                    "byte_budget": item.byte_budget,
                }
                for item in load_plan_obj.required_inputs
            ],
            "execution_budget": load_plan_obj.execution_budget,
            "load_budget": load_plan_obj.load_budget,
        }

        input_set = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_INPUT_SET_V1",
            "project_id": project_id,
            "project_instructions": {
                "project_instruction_binding": dict(project_instruction_binding),
                "project_instructions_sha256": project_instructions_sha256,
            },
            "chat_id": chat_id,
            "initiating_user_event_id": event_id,
            "initiating_user_event_artifact_id": event_artifact_id,
            "initiating_user_event_artifact_identity_sha256": event_identity_sha,
            "initiating_user_event_artifact_revision": event_revision,
            "initiating_user_event_artifact_sha256": event_sha,
            "initiating_content_sha256": content_sha,
            "accepted_chat_revision": accepted_chat_revision,
            "accepted_head_event_id": accepted_head_event_id,
        }
        if active_context_facts is not None and active_context_binding is not None:
            input_set["active_context_snapshot"] = {
                "active_context_snapshot_sha256": active_context_facts["snapshot_sha256"],
                "active_ancestry_sha256": active_context_facts["active_ancestry_sha256"],
                "chat_revision": accepted_chat_revision,
                "head_event_id": accepted_head_event_id,
                "active_context_artifact_binding": dict(active_context_binding),
            }
        if memory_guard_facts is not None and project_memory_state_guard_binding is not None:
            input_set["project_memory_state_guard"] = {
                "project_memory_state_guard_sha256": project_memory_state_guard_sha256,
                "project_memory_state_guard_artifact_binding": dict(project_memory_state_guard_binding),
                "state_artifact_id": memory_guard_facts["state_artifact_id"],
                "state_artifact_revision": memory_guard_facts["state_artifact_revision"],
                "state_artifact_sha256": memory_guard_facts["state_artifact_sha256"],
                "state_snapshot_sha256": memory_guard_facts["state_snapshot_sha256"],
                "active_memory_count": memory_guard_facts["active_memory_count"],
            }
        if memory_facts is not None and project_memory_context_binding is not None:
            input_set["project_memory_context"] = {
                "project_memory_context_sha256": project_memory_context_sha256,
                "project_memory_context_artifact_binding": dict(project_memory_context_binding),
                "active_memory_count": memory_facts["active_memory_count"],
                "memory_ids": [item["memory_id"] for item in memory_facts["items"]],
            }
        if personal_context_facts is not None and personal_context_binding is not None:
            input_set["personal_context"] = {
                "authority_class": PERSONAL_CONTEXT_AUTHORITY_CLASS,
                "personal_context_sha256": personal_context_sha256,
                "personal_context_artifact_binding": dict(personal_context_binding),
            }
        if project_history_context is not None and project_history_context_binding is not None:
            input_set["project_history_context"] = {
                "project_history_context_sha256": project_history_context_sha256,
                "project_history_context_artifact_binding": dict(project_history_context_binding),
                "selected_chat_count": project_history_context.get("selected_chat_count", 0),
                "truncated": bool(project_history_context.get("truncated")),
            }
        if normalized_retry_lineage is not None:
            input_set["retry_lineage"] = dict(normalized_retry_lineage)
            input_set["retry_lineage_sha256"] = _sha(normalized_retry_lineage)
        if source_facts is not None and source_context_binding is not None:
            input_set["library_source_context"] = {
                "source_context_sha256": source_facts["source_context_sha256"],
                "source_context_artifact_binding": dict(source_context_binding),
                "source_ref_id": source_facts["source_ref_id"],
                "source_artifact_id": source_facts["source_artifact_id"],
                "source_artifact_identity_sha256": source_facts["source_artifact_identity_sha256"],
                "source_artifact_revision": source_facts["source_artifact_revision"],
                "source_artifact_sha256": source_facts["source_artifact_sha256"],
                "derivation_sha256": source_facts["derivation_sha256"],
                "selected_source_role": source_facts["selected_source_role"],
                "selected_source_binding_sha256": source_facts["selected_source_binding_sha256"],
                "source_load_plan_sha256": source_facts["source_load_plan_sha256"],
                "source_permission_plan_sha256": source_facts["source_permission_plan_sha256"],
                "source_job_artifact_binding_plan_sha256": source_facts["source_job_artifact_binding_plan_sha256"],
                "source_predecessor_pack_pin_sha256": source_facts["source_pack_pin_sha256"],
                "question_sha256": source_facts["question_sha256"],
            }
        workflow_pin = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_WORKFLOW_PIN_V1",
            "workflow_id": "GENERAL_CHAT_SINGLE_REPLY_V1",
            "pack_id": PACK_ID,
            "pack_version": PACK_VERSION,
            "action_id": ACTION_ID,
            "action_sha256": action_sha,
        }
        rule_pin = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_RULE_PIN_V1",
            "no_tools": True,
            "no_streaming": not streaming,
            "provisional_streaming": streaming,
            "provisional_stream_authority": "NONE_PRESENTATION_ONLY" if streaming else None,
            "one_provider_request_max": 1,
            "transport_retries_max": 0,
            "fallback_allowed": False,
            "human_approval_required": True,
        }
        adapter_set = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_ADAPTER_EXECUTOR_PIN_SET_V1",
            "provider": self.model_target.provider,
            "adapter_relative_path": provider_config.adapter_relative_path,
            "adapter_sha256": provider_config.adapter_sha256,
            "provider_execution_config_sha256": provider_config.semantic_sha256,
        }
        network_plan = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_NETWORK_PERMISSION_PLAN_V1",
            "authorized_now": False,
            "requires_exact_human_approval": True,
            "provider": self.model_target.provider,
            "endpoint_origin": self.model_target.endpoint_origin,
            "api_route": self.model_target.api_route,
            "proxy_mode": self.model_target.proxy_mode,
            "proxy_config_sha256": proxy_sha,
            "live_network_calls_max_after_approval": 1,
            "stream": provider_config.stream,
        }
        request_plan = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_AUTHORIZED_REQUEST_PLAN_V1",
            "authorized_now": False,
            "requires_exact_human_approval": True,
            "action_sha256": action_sha,
            "system_prompt_sha256": prompt_sha,
            "project_instruction_revision": project_instruction_binding["revision"],
            "project_instructions_sha256": project_instructions_sha256,
            "project_instruction_artifact_sha256": project_instruction_binding["sha256"],
            "initiating_content_sha256": content_sha,
            "model_resolution_sha256": resolution.resolution_sha256,
            "provider_execution_config_sha256": provider_config.semantic_sha256,
            "max_provider_requests_after_approval": 1,
            "stream": provider_config.stream,
            "provisional_stream_persistence": "FORBIDDEN" if streaming else "NOT_APPLICABLE",
        }
        if active_context_facts is not None and active_context_binding is not None:
            request_plan.update({
                "active_context_snapshot_sha256": active_context_facts["snapshot_sha256"],
                "active_ancestry_sha256": active_context_facts["active_ancestry_sha256"],
                "active_context_artifact_sha256": active_context_binding["artifact_sha256"],
            })
        if memory_guard_facts is not None and project_memory_state_guard_binding is not None:
            request_plan.update({
                "project_memory_state_guard_sha256": project_memory_state_guard_sha256,
                "project_memory_state_guard_artifact_sha256": project_memory_state_guard_binding["artifact_sha256"],
                "project_memory_state_revision": memory_guard_facts["state_artifact_revision"],
            })
        if memory_facts is not None and project_memory_context_binding is not None:
            request_plan.update({
                "project_memory_context_sha256": project_memory_context_sha256,
                "project_memory_context_artifact_sha256": project_memory_context_binding["artifact_sha256"],
                "active_memory_count": memory_facts["active_memory_count"],
            })
        if personal_context_facts is not None and personal_context_binding is not None:
            request_plan.update({
                "personal_context_sha256": personal_context_sha256,
                "personal_context_artifact_sha256": personal_context_binding["artifact_sha256"],
                "personal_context_authority_class": PERSONAL_CONTEXT_AUTHORITY_CLASS,
            })
        if source_facts is not None and source_context_binding is not None:
            request_plan.update({
                "source_context_sha256": source_facts["source_context_sha256"],
                "source_context_artifact_sha256": source_context_binding["artifact_sha256"],
                "source_artifact_sha256": source_facts["source_artifact_sha256"],
                "source_derivation_sha256": source_facts["derivation_sha256"],
            })
        secret_plan = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_SECRET_ACCESS_PLAN_V1",
            "authorized_now": False,
            "requires_exact_human_approval": True,
            "credential_ref_id": self.model_target.credential_ref_id,
            "credential_ref_class": self.model_target.credential_ref_class,
            "secret_value_persistence": "FORBIDDEN",
        }
        profile_binding = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_MODEL_PROFILE_BINDING_V1",
            "selected_profile": decision.selected_profile,
            "model_policy_revision": decision.policy_revision,
            "model_decision_sha256": decision.decision_sha256,
            "pack_action_sha256": action_sha,
        }
        persistence_plan = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_PERSISTENCE_PLAN_V1",
            "working_artifacts": "RUNTIME_ARTIFACT_STORE",
            "job_authority": "RUNTIME_JOB_AUTHORITY_REGISTRY",
            "human_decision": "RUNTIME_HUMAN_DECISION_AUTHORITY",
            "web_projection": "AFTER_FORMAL_RESULT_COMMIT_ONLY",
            "provisional_stream": "EPHEMERAL_PRESENTATION_ONLY_NEVER_PERSIST" if streaming else "DISABLED",
            "secret_value": "NEVER_PERSIST",
        }

        runtime_contract_binding = _persist_exact_json(
            self.store,
            kind="RUNTIME_CONTRACT_MANIFEST",
            job_id=job_id,
            record=runtime_contract,
        )
        job_bundle = {
            "job_id": job_id,
            "project_instruction_artifact_id": project_instruction_binding["artifact_id"],
            "project_instruction_revision": project_instruction_binding["revision"],
            "project_instructions_sha256": project_instructions_sha256,
            "pack_pin": pack_pin,
            "runtime_contract_pin": {
                "job_id": job_id,
                "runtime_contract_manifest_sha256": runtime_contract_sha,
            },
            "model_decision_sha256": decision.decision_sha256,
            "model_catalog_revision": catalog.catalog_revision,
            "model_catalog_sha256": catalog.catalog_sha256,
            "model_resolution_sha256": resolution.resolution_sha256,
            "provider_execution_config_sha256": provider_config.semantic_sha256,
            "permission_plan_sha256": authorized_load.permission_plan_sha256,
            "load_plan_sha256": authorized_load.load_plan_sha256,
            "requested_model_profile": LOGICAL_PROFILE,
            "model_policy_revision": decision.policy_revision,
            "model_catalog_adoption_record_sha256": self.model_target.adoption_record_sha256,
            "runtime_contract_manifest_artifact_identity_sha256": runtime_contract_binding[
                "artifact_identity_sha256"
            ],
            "runtime_contract_manifest_artifact_revision": runtime_contract_binding["artifact_revision"],
            "runtime_contract_manifest_artifact_sha256": runtime_contract_binding["artifact_sha256"],
        }
        if active_context_facts is not None and active_context_binding is not None:
            job_bundle.update({
                "active_context_snapshot_sha256": active_context_facts["snapshot_sha256"],
                "active_ancestry_sha256": active_context_facts["active_ancestry_sha256"],
                "active_context_artifact_identity_sha256": active_context_binding["artifact_identity_sha256"],
                "active_context_artifact_revision": active_context_binding["artifact_revision"],
                "active_context_artifact_sha256": active_context_binding["artifact_sha256"],
            })
        if memory_guard_facts is not None and project_memory_state_guard_binding is not None:
            job_bundle.update({
                "project_memory_state_guard_sha256": project_memory_state_guard_sha256,
                "project_memory_state_guard_artifact_identity_sha256": project_memory_state_guard_binding["artifact_identity_sha256"],
                "project_memory_state_guard_artifact_revision": project_memory_state_guard_binding["artifact_revision"],
                "project_memory_state_guard_artifact_sha256": project_memory_state_guard_binding["artifact_sha256"],
                "project_memory_state_artifact_id": memory_guard_facts["state_artifact_id"],
                "project_memory_state_revision": memory_guard_facts["state_artifact_revision"],
                "project_memory_state_sha256": memory_guard_facts["state_artifact_sha256"],
            })
        if memory_facts is not None and project_memory_context_binding is not None:
            job_bundle.update({
                "project_memory_context_sha256": project_memory_context_sha256,
                "project_memory_context_artifact_identity_sha256": project_memory_context_binding["artifact_identity_sha256"],
                "project_memory_context_artifact_revision": project_memory_context_binding["artifact_revision"],
                "project_memory_context_artifact_sha256": project_memory_context_binding["artifact_sha256"],
            })
        if personal_context_facts is not None and personal_context_binding is not None:
            job_bundle.update({
                "personal_context_sha256": personal_context_sha256,
                "personal_context_artifact_identity_sha256": personal_context_binding["artifact_identity_sha256"],
                "personal_context_artifact_revision": personal_context_binding["artifact_revision"],
                "personal_context_artifact_sha256": personal_context_binding["artifact_sha256"],
                "personal_context_authority_class": PERSONAL_CONTEXT_AUTHORITY_CLASS,
            })
        if normalized_retry_lineage is not None:
            job_bundle["retry_lineage"] = dict(normalized_retry_lineage)
            job_bundle["retry_lineage_sha256"] = _sha(normalized_retry_lineage)
        if source_facts is not None and source_context_binding is not None:
            job_bundle.update({
                "source_context_sha256": source_facts["source_context_sha256"],
                "source_context_artifact_identity_sha256": source_context_binding["artifact_identity_sha256"],
                "source_context_artifact_revision": source_context_binding["artifact_revision"],
                "source_context_artifact_sha256": source_context_binding["artifact_sha256"],
                "source_ref_id": source_facts["source_ref_id"],
                "source_artifact_identity_sha256": source_facts["source_artifact_identity_sha256"],
                "source_artifact_revision": source_facts["source_artifact_revision"],
                "source_artifact_sha256": source_facts["source_artifact_sha256"],
                "source_derivation_sha256": source_facts["derivation_sha256"],
                "source_load_plan_sha256": source_facts["source_load_plan_sha256"],
                "source_permission_plan_sha256": source_facts["source_permission_plan_sha256"],
                "source_job_artifact_binding_plan_sha256": source_facts["source_job_artifact_binding_plan_sha256"],
                "source_predecessor_pack_pin_sha256": source_facts["source_pack_pin_sha256"],
            })
        job_bundle_record, job_bundle_binding = self.ledger.persist_job_bundle(
            job_id=job_id,
            job_bundle=job_bundle,
        )
        return GeneralChatPhaseAPreparedJob(
            job_id=job_id,
            job_bundle_record=job_bundle_record,
            job_bundle_binding=job_bundle_binding,
            runtime_contract_manifest=runtime_contract,
            runtime_contract_manifest_sha256=runtime_contract_sha,
            pack_pin=pack_pin,
            permission_plan=permission_plan,
            load_plan=load_plan,
            model_decision=decision.to_dict(),
            model_resolution=resolution.to_dict(),
            provider_execution_config=provider_config.payload(),
            provider_execution_config_sha256=provider_config.semantic_sha256,
            input_set=input_set,
            workflow_pin_sha256=_sha(workflow_pin),
            rule_pin_sha256=_sha(rule_pin),
            adapter_executor_pin_set_sha256=_sha(adapter_set),
            network_permission_plan=network_plan,
            authorized_request_plan=request_plan,
            secret_access_plan=secret_plan,
            model_profile_binding=profile_binding,
            output_contract_sha256=_file_sha(output_schema_path),
            persistence_plan=persistence_plan,
            runtime_execution_identity_sha256=runtime_execution_identity_sha,
            source_context=source_facts["source_context"] if source_facts is not None else None,
            source_context_sha256=source_facts["source_context_sha256"] if source_facts is not None else None,
            source_context_binding=dict(source_context_binding) if source_context_binding is not None else None,
            personal_context=personal_context_facts if personal_context_facts is not None else None,
            personal_context_sha256=personal_context_sha256 if personal_context_facts is not None else None,
            personal_context_binding=(
                dict(personal_context_binding) if personal_context_binding is not None else None
            ),
            project_memory_context=memory_facts if memory_facts is not None else None,
            project_memory_context_sha256=project_memory_context_sha256 if memory_facts is not None else None,
            project_memory_context_binding=(
                dict(project_memory_context_binding)
                if project_memory_context_binding is not None
                else None
            ),
            project_memory_state_guard=memory_guard_facts if memory_guard_facts is not None else None,
            project_memory_state_guard_sha256=(
                project_memory_state_guard_sha256 if memory_guard_facts is not None else None
            ),
            project_memory_state_guard_binding=(
                dict(project_memory_state_guard_binding)
                if project_memory_state_guard_binding is not None
                else None
            ),
        )

    def issue_or_replay_controlled_successor_job_authority_event_v1(
        self,
        *,
        predecessor_job_authority_event_id: str,
        transition_intent_schema: str,
        transition_stage: str,
        transition_code: str,
        approval_decision_event_binding: R009OpaqueArtifactBinding | None = None,
    ) -> dict[str, Any]:
        """Sequence owner-issued successor JAE before any successor snapshot/intent construction."""
        human_decision_authority = (
            None
            if transition_stage == "ACTIVE_PREDECESSOR_NO_DRE"
            else self.human_decision
        )
        return self.job_authority.issue_or_replay_one_controlled_successor_job_authority_event_v1(
            predecessor_job_authority_event_id=predecessor_job_authority_event_id,
            transition_intent_schema=transition_intent_schema,
            transition_stage=transition_stage,
            transition_code=transition_code,
            approval_decision_event_binding=approval_decision_event_binding,
            human_decision_authority=human_decision_authority,
        )

    def recover_approved_stale_execution_authority_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        decision_request_event_id: str,
        expected_job_id: str,
    ) -> dict[str, Any]:
        """Recover one APPROVED-but-stale execution authority without rewriting HumanDecision."""
        try:
            context = self._controlled_reopen_context_v1(
                project_id=project_id,
                chat_id=chat_id,
                decision_request_event_id=decision_request_event_id,
                expected_job_id=expected_job_id,
                require_jobbundle_runtime_pin_match=False,
            )
            terminal_source = self.human_decision.load_exact_terminal_source(
                decision_request_event_id
            )
            if (
                terminal_source.get("terminal_decision_code") != "APPROVED"
                or terminal_source.get("decision_request_event_id") != decision_request_event_id
                or terminal_source.get("decision_request_identity_sha256")
                != context["request_source"].get("decision_request_identity_sha256")
            ):
                raise GeneralChatFormalPrepareError(
                    "POST_APPROVED_RECOVERY_CURRENTNESS",
                    "exact HumanDecision terminal is not the approved predecessor",
                )

            approval_binding = R009OpaqueArtifactBinding(
                terminal_source["approval_decision_event_artifact_identity_sha256"],
                terminal_source["approval_decision_event_artifact_revision"],
                terminal_source["approval_decision_event_artifact_sha256"],
            )
            approval = self._load_exact_json_binding_v1(
                binding=approval_binding,
                label="post-approved recovery approval decision",
            )
            if (
                approval.get("schema") != "RUNTIME_APPROVAL_DECISION_EVENT_BINDING_V3"
                or approval.get("decision_code") != "APPROVED"
                or approval.get("approval_decision_event_id")
                != terminal_source.get("approval_decision_event_id")
                or approval.get("decision_request_event_id") != decision_request_event_id
                or approval.get("job_authority_event_id")
                != context["predecessor_job_authority_event_id"]
            ):
                raise GeneralChatFormalPrepareError(
                    "POST_APPROVED_RECOVERY_CURRENTNESS",
                    "approval Artifact does not exact-bind predecessor approval",
                )

            issuance = self.issue_or_replay_controlled_successor_job_authority_event_v1(
                predecessor_job_authority_event_id=
                    context["predecessor_job_authority_event_id"],
                transition_intent_schema="RUNTIME_JOB_CONTROLLED_REOPEN_INTENT_V2",
                transition_stage="APPROVED_SLOT_UNCLAIMED",
                transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
                approval_decision_event_binding=approval_binding,
            )
            successor_jae = issuance["successor_job_authority_event_id"]
            lineage_sha = issuance["job_lineage_identity_sha256"]
            predecessor_slot_key = issuance["predecessor_approval_slot_key_sha256"]
            authority_binding_sha = _sha({
                "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
                "job_authority_event_id": successor_jae,
                "job_lineage_identity_sha256": lineage_sha,
            })

            current_contract, current_contract_sha = self._current_runtime_migration_contract_v1(
                context=context
            )
            current_contract_binding_dict, _current_contract_binding = (
                self._persist_controlled_reopen_json_v1(
                    kind="POST_APPROVED_CURRENT_RUNTIME_CONTRACT_MANIFEST",
                    job_id=context["job_id"],
                    decision_request_event_id=decision_request_event_id,
                    record=current_contract,
                )
            )

            successor_frozen = dict(context["frozen_manifest"])
            successor_frozen["runtime_contract_manifest_sha256"] = current_contract_sha
            successor_frozen_binding_dict, _successor_frozen_binding = (
                self._persist_controlled_reopen_json_v1(
                    kind="POST_APPROVED_SUCCESSOR_FROZEN_BINDING_MANIFEST",
                    job_id=context["job_id"],
                    decision_request_event_id=decision_request_event_id,
                    record=successor_frozen,
                )
            )

            successor_snapshot = dict(context["predecessor_snapshot"])
            successor_snapshot.update({
                "job_authority_event_id": successor_jae,
                "job_lineage_identity_sha256": lineage_sha,
                "job_authority_binding_sha256": authority_binding_sha,
                "runtime_contract_pin_sha256": current_contract_sha,
                "runtime_execution_identity_sha256": _sha(current_contract["source_bindings"]),
                "frozen_binding_manifest_artifact_identity_sha256":
                    successor_frozen_binding_dict["artifact_identity_sha256"],
                "frozen_binding_manifest_artifact_revision":
                    successor_frozen_binding_dict["artifact_revision"],
                "frozen_binding_manifest_artifact_sha256":
                    successor_frozen_binding_dict["artifact_sha256"],
            })
            successor_snapshot_binding_dict, successor_snapshot_binding = (
                self._persist_controlled_reopen_json_v1(
                    kind="POST_APPROVED_SUCCESSOR_AUTHORITY_SNAPSHOT",
                    job_id=context["job_id"],
                    decision_request_event_id=decision_request_event_id,
                    record=successor_snapshot,
                )
            )
            successor_jxs = "JXS_" + _sha({
                "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
                "job_authority_event_id": successor_jae,
                "snapshot_content_sha256": successor_snapshot_binding.artifact_sha256,
            })

            transition = {
                "schema": "RUNTIME_JOB_CONTROLLED_REOPEN_INTENT_V2",
                "transition_code": "CONTROLLED_REOPEN_RUNTIME_MIGRATION",
                "predecessor_job_authority_event_id":
                    context["predecessor_job_authority_event_id"],
                "predecessor_job_execution_authority_snapshot_id":
                    context["predecessor_snapshot"].get(
                        "job_execution_authority_snapshot_id",
                        context["v3"]["job_execution_authority_snapshot_id"],
                    ),
                "predecessor_job_execution_authority_snapshot_sha256":
                    context["predecessor_snapshot_binding"].artifact_sha256,
                "predecessor_approval_decision_event_id":
                    terminal_source["approval_decision_event_id"],
                "predecessor_approval_slot_key_sha256": predecessor_slot_key,
                "successor_job_authority_event_id": successor_jae,
                "successor_job_authority_binding_sha256": authority_binding_sha,
                "successor_job_execution_authority_snapshot_id": successor_jxs,
                "successor_job_execution_authority_snapshot_sha256":
                    successor_snapshot_binding.artifact_sha256,
                "successor_job_execution_authority_snapshot_artifact_identity_sha256":
                    successor_snapshot_binding.artifact_identity_sha256,
                "successor_job_execution_authority_snapshot_artifact_revision":
                    successor_snapshot_binding.artifact_revision,
                "successor_job_execution_authority_snapshot_artifact_sha256":
                    successor_snapshot_binding.artifact_sha256,
                "successor_preparation_state": "PREPARED_NON_EXECUTION_ELIGIBLE",
                "successor_activation_required": True,
            }
            transition_binding_dict, transition_binding = (
                self._persist_controlled_reopen_json_v1(
                    kind="POST_APPROVED_CONTROLLED_TRANSITION_INTENT_V2",
                    job_id=context["job_id"],
                    decision_request_event_id=decision_request_event_id,
                    record=transition,
                )
            )

            claim = self.job_authority.claim_or_replay_one_transition_bound_successor_lineage_v1(
                transition_intent_binding=transition_binding,
                successor_snapshot_binding=successor_snapshot_binding,
            )
            if (
                claim.get("successor_job_authority_event_id") != successor_jae
                or claim.get("successor_job_execution_authority_snapshot_id") != successor_jxs
                or claim.get("transition_intent_sha256") != transition_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "POST_APPROVED_RECOVERY_CURRENTNESS",
                    "prepared successor lineage differs from exact recovery transition",
                )

            invalidation = (
                self.job_authority.invalidate_or_replay_approval_execution_slot_before_attempt_v1(
                    predecessor_job_authority_event_id=
                        context["predecessor_job_authority_event_id"],
                    predecessor_approval_decision_event_id=
                        terminal_source["approval_decision_event_id"],
                    expected_predecessor_approval_slot_key_sha256=
                        predecessor_slot_key,
                    successor_job_authority_event_id=successor_jae,
                    successor_job_execution_authority_snapshot_id=successor_jxs,
                    successor_job_execution_authority_snapshot_sha256=
                        successor_snapshot_binding.artifact_sha256,
                    job_transition_intent_binding=transition_binding,
                )
            )

            registration = {
                "schema": "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2",
                "registration_revision": 1,
                "job_authority_event_id": successor_jae,
                "job_authority_binding_sha256": authority_binding_sha,
                "job_execution_authority_snapshot_id": successor_jxs,
                "job_execution_authority_snapshot_sha256":
                    successor_snapshot_binding.artifact_sha256,
                "job_execution_authority_snapshot_artifact_identity_sha256":
                    successor_snapshot_binding.artifact_identity_sha256,
                "job_execution_authority_snapshot_artifact_revision":
                    successor_snapshot_binding.artifact_revision,
                "job_execution_authority_snapshot_artifact_sha256":
                    successor_snapshot_binding.artifact_sha256,
                "activation_basis":
                    "CONTROLLED_SUCCESSOR_AFTER_PREDECESSOR_INVALIDATION",
                "predecessor_approval_slot_key_sha256": predecessor_slot_key,
                "predecessor_invalidation_sha256":
                    invalidation["terminal_source_sha256"],
                "job_transition_intent_sha256": transition_binding.artifact_sha256,
                "state": "ACTIVE_EXECUTION_AUTHORITY_SNAPSHOT",
            }
            registration_binding_dict, registration_binding = (
                self._persist_controlled_reopen_json_v1(
                    kind="POST_APPROVED_SUCCESSOR_REGISTRATION_V2",
                    job_id=context["job_id"],
                    decision_request_event_id=decision_request_event_id,
                    record=registration,
                )
            )
            active_source = (
                self.job_authority.register_or_replay_one_active_snapshot_for_jae_v1(
                    registration_binding=registration_binding
                )
            )
            if (
                active_source.get("job_authority_event_id") != successor_jae
                or active_source.get("job_execution_authority_snapshot_id") != successor_jxs
                or active_source.get("registration_sha256")
                != registration_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "POST_APPROVED_RECOVERY_CURRENTNESS",
                    "active successor differs from exact recovery registration",
                )

            return {
                "status": "POST_APPROVED_STALE_EXECUTION_AUTHORITY_RECOVERED",
                "formal_job": True,
                "job_id": context["job_id"],
                "predecessor_job_authority_event_id":
                    context["predecessor_job_authority_event_id"],
                "predecessor_decision_request_event_id": decision_request_event_id,
                "predecessor_terminal_decision_code": "APPROVED",
                "predecessor_approval_decision_event_id":
                    terminal_source["approval_decision_event_id"],
                "predecessor_approval_slot_key_sha256": predecessor_slot_key,
                "predecessor_invalidation_sha256":
                    invalidation["terminal_source_sha256"],
                "successor_job_authority_event_id": successor_jae,
                "successor_job_execution_authority_snapshot_id": successor_jxs,
                "successor_job_execution_authority_snapshot_sha256":
                    successor_snapshot_binding.artifact_sha256,
                "successor_runtime_contract_manifest_sha256": current_contract_sha,
                "successor_runtime_contract_binding": current_contract_binding_dict,
                "successor_snapshot_binding": successor_snapshot_binding_dict,
                "job_transition_intent_binding": transition_binding_dict,
                "successor_registration_binding": registration_binding_dict,
                "old_human_decision_terminal_mutated": False,
                "new_dre_created": False,
                "human_approval_created": False,
                "execution_grant_created": False,
                "attempt_claim_created": False,
                "secret_read": False,
                "network_called": False,
                "model_called": False,
            }
        except GeneralChatFormalPrepareError:
            raise
        except (
            JobAuthorityError,
            HumanDecisionAuthorityError,
            R009OpaqueArtifactError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise GeneralChatFormalPrepareError(
                "POST_APPROVED_STALE_RECOVERY_REJECTED",
                str(exc),
            ) from exc

    def _load_exact_json_binding_v1(
        self,
        *,
        binding: R009OpaqueArtifactBinding,
        label: str,
    ) -> dict[str, Any]:
        try:
            _manifest, raw = self.store.load_exact_r009_opaque_artifact_r001_v1(
                artifact_identity_sha256=binding.artifact_identity_sha256,
                artifact_revision=binding.artifact_revision,
                artifact_sha256=binding.artifact_sha256,
            )
            value = json.loads(raw.decode("utf-8"))
        except (R009OpaqueArtifactError, UnicodeError, json.JSONDecodeError) as exc:
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                f"{label} exact Artifact is unavailable or invalid",
            ) from exc
        if not isinstance(value, dict):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                f"{label} must be a JSON object",
            )
        if _sha(value) != binding.artifact_sha256:
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                f"{label} canonical SHA does not match exact Artifact binding",
            )
        return value

    @staticmethod
    def _r009_binding_from_dict_v1(value: Any, label: str) -> R009OpaqueArtifactBinding:
        if not isinstance(value, dict):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                f"{label} binding object required",
            )
        try:
            return R009OpaqueArtifactBinding(
                value["artifact_identity_sha256"],
                int(value["artifact_revision"]),
                value["artifact_sha256"],
            )
        except (KeyError, TypeError, ValueError, R009OpaqueArtifactError) as exc:
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                f"{label} exact Artifact binding invalid",
            ) from exc

    def _controlled_reopen_context_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        decision_request_event_id: str,
        expected_job_id: str,
        require_jobbundle_runtime_pin_match: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(project_id, str) or not project_id:
            raise GeneralChatFormalPrepareError("CONTROLLED_REOPEN_INPUT", "project_id required", status_code=400)
        if not isinstance(chat_id, str) or not chat_id:
            raise GeneralChatFormalPrepareError("CONTROLLED_REOPEN_INPUT", "chat_id required", status_code=400)
        if not isinstance(expected_job_id, str) or not expected_job_id:
            raise GeneralChatFormalPrepareError("CONTROLLED_REOPEN_INPUT", "expected_job_id required", status_code=400)
        if (
            not isinstance(decision_request_event_id, str)
            or re.fullmatch(r"DRE_[0-9a-f]{64}", decision_request_event_id) is None
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_INPUT",
                "decision_request_event_id must be exact DRE_<64 lowercase hex>",
                status_code=400,
            )

        request_source = self.human_decision.load_exact_request_source(decision_request_event_id)
        v3 = request_source.get("decision_request_binding_v3")
        if not isinstance(v3, dict):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "exact HumanDecision request lacks complete V3 binding",
            )
        if (
            v3.get("decision_request_event_id") != decision_request_event_id
            or request_source.get("decision_request_identity_sha256") != _sha(v3)
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "HumanDecision request identity does not recompute",
            )

        predecessor_jae = v3.get("job_authority_event_id")
        if not isinstance(predecessor_jae, str) or re.fullmatch(r"JAE_[0-9a-f]{64}", predecessor_jae) is None:
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "predecessor JAE is invalid",
            )
        active_source, registration, registration_binding = (
            self.job_authority.load_exact_active_registration_source_by_jae_v1(
                job_authority_event_id=predecessor_jae
            )
        )
        if (
            active_source.get("job_execution_authority_snapshot_id") != v3.get("job_execution_authority_snapshot_id")
            or active_source.get("job_execution_authority_snapshot_sha256") != v3.get("job_execution_authority_snapshot_sha256")
            or active_source.get("registration_sha256") != v3.get("job_execution_snapshot_registration_sha256")
            or registration_binding.artifact_identity_sha256
            != v3.get("job_execution_snapshot_registration_artifact_identity_sha256")
            or registration_binding.artifact_revision
            != v3.get("job_execution_snapshot_registration_artifact_revision")
            or registration_binding.artifact_sha256
            != v3.get("job_execution_snapshot_registration_artifact_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "active predecessor registration differs from exact DRE request binding",
            )

        snapshot_binding = R009OpaqueArtifactBinding(
            v3["job_execution_authority_snapshot_artifact_identity_sha256"],
            v3["job_execution_authority_snapshot_artifact_revision"],
            v3["job_execution_authority_snapshot_artifact_sha256"],
        )
        predecessor_snapshot = self._load_exact_json_binding_v1(
            binding=snapshot_binding,
            label="predecessor snapshot",
        )
        if (
            predecessor_snapshot.get("schema") != "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1"
            or predecessor_snapshot.get("job_authority_event_id") != predecessor_jae
            or snapshot_binding.artifact_sha256 != v3.get("job_execution_authority_snapshot_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "predecessor snapshot differs from exact DRE request binding",
            )

        frozen_binding = R009OpaqueArtifactBinding(
            predecessor_snapshot["frozen_binding_manifest_artifact_identity_sha256"],
            predecessor_snapshot["frozen_binding_manifest_artifact_revision"],
            predecessor_snapshot["frozen_binding_manifest_artifact_sha256"],
        )
        frozen = self._load_exact_json_binding_v1(
            binding=frozen_binding,
            label="predecessor frozen binding manifest",
        )
        if frozen.get("schema") != "RUNTIME_S1_GENERAL_CHAT_FROZEN_BINDING_MANIFEST_V1":
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "predecessor frozen binding manifest schema mismatch",
            )
        job_id = frozen.get("job_id")
        if job_id != expected_job_id:
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_SCOPE_MISMATCH",
                "expected_job_id differs from exact frozen Job",
            )

        intake_binding = self._r009_binding_from_dict_v1(
            frozen.get("web_formal_job_intake_binding"),
            "Web formal intake",
        )
        intake = self._load_exact_json_binding_v1(
            binding=intake_binding,
            label="Web formal intake",
        )
        if (
            intake.get("schema") != "WEB_FORMAL_JOB_INTAKE_BINDING_V1"
            or intake.get("job_id") != job_id
            or intake.get("project_id") != project_id
            or intake.get("chat_id") != chat_id
            or intake_binding.artifact_sha256 != frozen.get("web_formal_job_intake_binding_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_SCOPE_MISMATCH",
                "exact Web intake does not bind the requested Project/Chat/Job",
            )

        job_bundle_binding = self._r009_binding_from_dict_v1(
            frozen.get("job_bundle_binding"),
            "JobBundle",
        )
        job_bundle_record = self._load_exact_json_binding_v1(
            binding=job_bundle_binding,
            label="JobBundle",
        )
        job_bundle = job_bundle_record.get("job_bundle")
        if (
            job_bundle_record.get("schema") != "RUNTIME_IMMUTABLE_JOB_BUNDLE_BINDING_V1"
            or job_bundle_record.get("job_id") != job_id
            or not isinstance(job_bundle, dict)
            or job_bundle.get("job_id") != job_id
            or job_bundle_record.get("job_bundle_sha256") != _sha(job_bundle)
            or frozen.get("job_bundle_sha256") != job_bundle_record.get("job_bundle_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "exact JobBundle/frozen binding mismatch",
            )

        runtime_contract_binding = R009OpaqueArtifactBinding(
            job_bundle["runtime_contract_manifest_artifact_identity_sha256"],
            job_bundle["runtime_contract_manifest_artifact_revision"],
            job_bundle["runtime_contract_manifest_artifact_sha256"],
        )
        predecessor_contract = self._load_exact_json_binding_v1(
            binding=runtime_contract_binding,
            label="predecessor Runtime contract",
        )
        predecessor_contract_sha = _sha(predecessor_contract)
        if require_jobbundle_runtime_pin_match and (
            predecessor_contract_sha != predecessor_snapshot.get("runtime_contract_pin_sha256")
            or predecessor_contract_sha != frozen.get("runtime_contract_manifest_sha256")
            or predecessor_contract_sha
            != job_bundle.get("runtime_contract_pin", {}).get("runtime_contract_manifest_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "predecessor Runtime contract pin does not cross-bind snapshot/frozen/JobBundle",
            )

        actor = self.human_decision.load_exact_local_single_user_opaque_actor_identity_v1()
        actor_identity = actor.get("actor_authority_identity_sha256")
        if not isinstance(actor_identity, str) or _SHA_RE.fullmatch(actor_identity) is None:
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "Runtime-local opaque actor identity is invalid",
            )
        if any(
            actor.get(key) is not False
            for key in (
                "represents_real_person_identity",
                "provides_authentication",
                "provides_authorization",
                "grants_permission",
            )
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "Runtime-local actor identity semantic ceiling changed",
            )

        branch_source, branch, branch_binding = self.job_authority.load_exact_preapproval_branch_by_key_v1(
            preapproval_branch_key_sha256=request_source["preapproval_branch_key_sha256"]
        )
        if (
            branch_source.get("branch_code") != "DRE_ISSUANCE_SELECTED"
            or branch.get("decision_request_event_id") != decision_request_event_id
            or branch.get("decision_request_identity_sha256") != request_source.get("decision_request_identity_sha256")
            or branch.get("decision_request_binding_v3") != v3
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "exact DRE branch/request binding mismatch",
            )

        return {
            "job_id": job_id,
            "request_source": request_source,
            "v3": v3,
            "predecessor_job_authority_event_id": predecessor_jae,
            "active_source": active_source,
            "predecessor_registration": registration,
            "predecessor_registration_binding": registration_binding,
            "predecessor_snapshot": predecessor_snapshot,
            "predecessor_snapshot_binding": snapshot_binding,
            "frozen_manifest": frozen,
            "frozen_manifest_binding": frozen_binding,
            "job_bundle_record": job_bundle_record,
            "job_bundle": job_bundle,
            "predecessor_runtime_contract": predecessor_contract,
            "predecessor_runtime_contract_binding": runtime_contract_binding,
            "actor_identity_source": actor,
            "actor_authority_identity_sha256": actor_identity,
            "branch_source": branch_source,
            "branch": branch,
            "branch_binding": branch_binding,
        }

    def _current_runtime_migration_contract_v1(
        self,
        *,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        predecessor_contract = context["predecessor_runtime_contract"]
        adoption_sha = predecessor_contract.get("model_catalog_adoption_record_sha256")
        pack_action_sha = predecessor_contract.get("pack_action_sha256")
        _require_sha(adoption_sha, "model_catalog_adoption_record_sha256")
        _require_sha(pack_action_sha, "pack_action_sha256")
        predecessor_streaming = predecessor_contract.get("provider_rules", {}).get("stream") is True
        current = self._runtime_contract_manifest(
            adoption_record_sha256=adoption_sha,
            pack_action_sha256=pack_action_sha,
            streaming=predecessor_streaming,
        )
        current_sha = _sha(current)
        if current_sha == context["predecessor_snapshot"].get("runtime_contract_pin_sha256"):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_NOT_REQUIRED",
                "current Runtime contract already matches predecessor snapshot pin",
            )
        return current, current_sha

    def _persist_controlled_reopen_json_v1(
        self,
        *,
        kind: str,
        job_id: str,
        decision_request_event_id: str,
        record: dict[str, Any],
    ) -> tuple[dict[str, Any], R009OpaqueArtifactBinding]:
        binding_dict = _persist_exact_json(
            self.store,
            kind=f"CONTROLLED_REOPEN:{decision_request_event_id}:{kind}",
            job_id=job_id,
            record=record,
        )
        binding = R009OpaqueArtifactBinding(
            binding_dict["artifact_identity_sha256"],
            binding_dict["artifact_revision"],
            binding_dict["artifact_sha256"],
        )
        return binding_dict, binding

    def _controlled_reopen_terminal_artifact_v1(
        self,
        *,
        terminal_source: dict[str, Any],
    ) -> tuple[dict[str, Any], R009OpaqueArtifactBinding]:
        if terminal_source.get("terminal_decision_code") != "SUPERSEDED_FOR_CONTROLLED_REOPEN":
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_TERMINAL_CONFLICT",
                "DRE terminal already belongs to another Human decision",
            )
        binding = R009OpaqueArtifactBinding(
            terminal_source["non_approval_terminal_artifact_identity_sha256"],
            terminal_source["non_approval_terminal_artifact_revision"],
            terminal_source["non_approval_terminal_artifact_sha256"],
        )
        terminal = self._load_exact_json_binding_v1(
            binding=binding,
            label="controlled-reopen non-approval terminal",
        )
        if (
            terminal.get("schema") != "RUNTIME_NON_APPROVAL_TERMINAL_HUMAN_DECISION_BINDING_V1"
            or terminal.get("terminal_decision_code") != "SUPERSEDED_FOR_CONTROLLED_REOPEN"
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_TERMINAL_CONFLICT",
                "existing Human terminal does not exact-bind controlled reopen",
            )
        return terminal, binding

    def _complete_dre_pending_runtime_migration_activation_v1(
        self,
        *,
        context: dict[str, Any],
        terminal: dict[str, Any],
        terminal_binding: R009OpaqueArtifactBinding,
    ) -> dict[str, Any]:
        v3 = context["v3"]
        request_source = context["request_source"]
        predecessor_jae = context["predecessor_job_authority_event_id"]
        successor_jae = terminal.get("successor_job_authority_event_id")
        if not isinstance(successor_jae, str) or re.fullmatch(r"JAE_[0-9a-f]{64}", successor_jae) is None:
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "terminal successor JAE invalid",
            )
        successor_snapshot_binding = R009OpaqueArtifactBinding(
            terminal["successor_job_execution_authority_snapshot_artifact_identity_sha256"],
            terminal["successor_job_execution_authority_snapshot_artifact_revision"],
            terminal["successor_job_execution_authority_snapshot_artifact_sha256"],
        )
        successor_snapshot = self._load_exact_json_binding_v1(
            binding=successor_snapshot_binding,
            label="controlled-reopen successor snapshot",
        )
        transition_binding = R009OpaqueArtifactBinding(
            terminal["preapproval_transition_intent_artifact_identity_sha256"],
            terminal["preapproval_transition_intent_artifact_revision"],
            terminal["preapproval_transition_intent_artifact_sha256"],
        )
        transition = self._load_exact_json_binding_v1(
            binding=transition_binding,
            label="controlled-reopen transition intent",
        )
        if (
            transition.get("schema") != "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1"
            or transition.get("predecessor_stage") != "DRE_PENDING_NO_TERMINAL_DECISION"
            or transition.get("transition_code") != "CONTROLLED_REOPEN_RUNTIME_MIGRATION"
            or transition.get("predecessor_job_authority_event_id") != predecessor_jae
            or transition.get("predecessor_decision_request_event_id") != v3.get("decision_request_event_id")
            or transition.get("predecessor_decision_request_identity_sha256")
            != request_source.get("decision_request_identity_sha256")
            or transition.get("successor_job_authority_event_id") != successor_jae
            or transition.get("successor_job_execution_authority_snapshot_sha256")
            != successor_snapshot_binding.artifact_sha256
            or terminal.get("preapproval_transition_intent_sha256") != transition_binding.artifact_sha256
            or terminal.get("successor_job_execution_authority_snapshot_sha256")
            != successor_snapshot_binding.artifact_sha256
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "terminal/transition/successor exact binding mismatch",
            )

        claim = self.job_authority.load_exact_successor_lineage_claim_v1(successor_jae)
        if (
            claim.get("schema") != "RUNTIME_JOB_AUTHORITY_SUCCESSOR_LINEAGE_CLAIM_SOURCE_RECORD_V2"
            or claim.get("transition_intent_sha256") != transition_binding.artifact_sha256
            or claim.get("successor_job_execution_authority_snapshot_sha256")
            != successor_snapshot_binding.artifact_sha256
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "successor lineage claim does not exact-bind terminal successor",
            )

        branch_source = context["branch_source"]
        branch_binding = context["branch_binding"]
        registration = {
            "schema": "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V3",
            "registration_revision": 1,
            "job_authority_event_id": successor_jae,
            "job_authority_binding_sha256": successor_snapshot["job_authority_binding_sha256"],
            "job_execution_authority_snapshot_id": terminal["successor_job_execution_authority_snapshot_id"],
            "job_execution_authority_snapshot_sha256": successor_snapshot_binding.artifact_sha256,
            "job_execution_authority_snapshot_artifact_identity_sha256": successor_snapshot_binding.artifact_identity_sha256,
            "job_execution_authority_snapshot_artifact_revision": successor_snapshot_binding.artifact_revision,
            "job_execution_authority_snapshot_artifact_sha256": successor_snapshot_binding.artifact_sha256,
            "activation_basis": "CONTROLLED_SUCCESSOR_AFTER_DRE_NON_APPROVAL_TERMINAL",
            "predecessor_job_authority_event_id": predecessor_jae,
            "predecessor_job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
            "predecessor_job_execution_authority_snapshot_sha256": v3["job_execution_authority_snapshot_sha256"],
            "predecessor_job_execution_snapshot_registration_sha256": v3["job_execution_snapshot_registration_sha256"],
            "preapproval_branch_key_sha256": request_source["preapproval_branch_key_sha256"],
            "preapproval_branch_selection_semantic_sha256": branch_source["branch_selection_semantic_sha256"],
            "preapproval_branch_selection_artifact_identity_sha256": branch_binding.artifact_identity_sha256,
            "preapproval_branch_selection_artifact_revision": branch_binding.artifact_revision,
            "preapproval_branch_selection_artifact_sha256": branch_binding.artifact_sha256,
            "preapproval_transition_intent_sha256": transition_binding.artifact_sha256,
            "preapproval_transition_intent_artifact_identity_sha256": transition_binding.artifact_identity_sha256,
            "preapproval_transition_intent_artifact_revision": transition_binding.artifact_revision,
            "preapproval_transition_intent_artifact_sha256": transition_binding.artifact_sha256,
            "predecessor_decision_request_event_id": v3["decision_request_event_id"],
            "predecessor_decision_request_identity_sha256": request_source["decision_request_identity_sha256"],
            "predecessor_nonapproval_terminal_binding_sha256": terminal_binding.artifact_sha256,
            "predecessor_nonapproval_terminal_artifact_identity_sha256": terminal_binding.artifact_identity_sha256,
            "predecessor_nonapproval_terminal_artifact_revision": terminal_binding.artifact_revision,
            "predecessor_nonapproval_terminal_artifact_sha256": terminal_binding.artifact_sha256,
            "predecessor_approval_slot_key_sha256": None,
            "predecessor_invalidation_sha256": None,
            "state": "ACTIVE_EXECUTION_AUTHORITY_SNAPSHOT",
        }
        registration_binding_dict, registration_binding = self._persist_controlled_reopen_json_v1(
            kind="SUCCESSOR_REGISTRATION_V3",
            job_id=context["job_id"],
            decision_request_event_id=v3["decision_request_event_id"],
            record=registration,
        )
        active_source = self.job_authority.activate_or_replay_exact_preapproval_successor_v1(
            successor_registration_binding=registration_binding,
            human_decision_authority=self.human_decision,
        )
        if (
            active_source.get("job_authority_event_id") != successor_jae
            or active_source.get("job_execution_authority_snapshot_id")
            != terminal["successor_job_execution_authority_snapshot_id"]
            or active_source.get("registration_sha256") != registration_binding.artifact_sha256
        ):
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_CURRENTNESS",
                "successor activation source does not exact-bind V3 registration",
            )
        return {
            "status": "CONTROLLED_REOPEN_RUNTIME_MIGRATION_ACTIVATED",
            "formal_job": True,
            "job_id": context["job_id"],
            "predecessor_job_authority_event_id": predecessor_jae,
            "predecessor_decision_request_event_id": v3["decision_request_event_id"],
            "predecessor_terminal_decision_code": "SUPERSEDED_FOR_CONTROLLED_REOPEN",
            "successor_job_authority_event_id": successor_jae,
            "successor_job_execution_authority_snapshot_id": terminal["successor_job_execution_authority_snapshot_id"],
            "successor_job_execution_authority_snapshot_sha256": successor_snapshot_binding.artifact_sha256,
            "successor_registration_sha256": registration_binding.artifact_sha256,
            "successor_registration_binding": registration_binding_dict,
            "preapproval_transition_intent_sha256": transition_binding.artifact_sha256,
            "non_approval_terminal_binding_sha256": terminal_binding.artifact_sha256,
            "network_called": False,
            "model_called": False,
            "secret_read": False,
            "human_approval_created": False,
            "execution_grant_created": False,
            "attempt_claim_created": False,
        }

    def consume_or_replay_dre_pending_runtime_migration_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        decision_request_event_id: str,
        expected_job_id: str,
        action_code: str,
    ) -> dict[str, Any]:
        """Actual Web/controller consumer for one explicit DRE-pending Runtime migration action."""
        if action_code != "SUPERSEDE_FOR_CONTROLLED_REOPEN":
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_ACTION_REQUIRED",
                "action_code must be SUPERSEDE_FOR_CONTROLLED_REOPEN",
                status_code=400,
            )
        try:
            context = self._controlled_reopen_context_v1(
                project_id=project_id,
                chat_id=chat_id,
                decision_request_event_id=decision_request_event_id,
                expected_job_id=expected_job_id,
            )
            try:
                terminal_source = self.human_decision.load_exact_terminal_source(
                    decision_request_event_id
                )
            except HumanDecisionAuthorityError as exc:
                if str(exc) != "terminal source absent":
                    raise
                terminal_source = None

            if terminal_source is not None:
                terminal, terminal_binding = self._controlled_reopen_terminal_artifact_v1(
                    terminal_source=terminal_source
                )
                return self._complete_dre_pending_runtime_migration_activation_v1(
                    context=context,
                    terminal=terminal,
                    terminal_binding=terminal_binding,
                )

            issuance = self.issue_or_replay_controlled_successor_job_authority_event_v1(
                predecessor_job_authority_event_id=context["predecessor_job_authority_event_id"],
                transition_intent_schema="RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
                transition_stage="DRE_PENDING_NO_TERMINAL_DECISION",
                transition_code="CONTROLLED_REOPEN_RUNTIME_MIGRATION",
            )
            successor_jae = issuance["successor_job_authority_event_id"]
            lineage_sha = issuance["job_lineage_identity_sha256"]
            authority_binding_sha = _sha({
                "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
                "job_authority_event_id": successor_jae,
                "job_lineage_identity_sha256": lineage_sha,
            })

            current_contract, current_contract_sha = self._current_runtime_migration_contract_v1(
                context=context
            )
            _current_contract_binding_dict, _current_contract_binding = (
                self._persist_controlled_reopen_json_v1(
                    kind="CURRENT_RUNTIME_CONTRACT_MANIFEST",
                    job_id=context["job_id"],
                    decision_request_event_id=decision_request_event_id,
                    record=current_contract,
                )
            )

            successor_frozen = dict(context["frozen_manifest"])
            successor_frozen["runtime_contract_manifest_sha256"] = current_contract_sha
            successor_frozen_binding_dict, _successor_frozen_binding = (
                self._persist_controlled_reopen_json_v1(
                    kind="SUCCESSOR_FROZEN_BINDING_MANIFEST",
                    job_id=context["job_id"],
                    decision_request_event_id=decision_request_event_id,
                    record=successor_frozen,
                )
            )

            successor_snapshot = dict(context["predecessor_snapshot"])
            successor_snapshot.update({
                "job_authority_event_id": successor_jae,
                "job_lineage_identity_sha256": lineage_sha,
                "job_authority_binding_sha256": authority_binding_sha,
                "runtime_contract_pin_sha256": current_contract_sha,
                "runtime_execution_identity_sha256": _sha(current_contract["source_bindings"]),
                "frozen_binding_manifest_artifact_identity_sha256":
                    successor_frozen_binding_dict["artifact_identity_sha256"],
                "frozen_binding_manifest_artifact_revision":
                    successor_frozen_binding_dict["artifact_revision"],
                "frozen_binding_manifest_artifact_sha256":
                    successor_frozen_binding_dict["artifact_sha256"],
            })
            successor_snapshot_binding_dict, successor_snapshot_binding = (
                self._persist_controlled_reopen_json_v1(
                    kind="SUCCESSOR_AUTHORITY_SNAPSHOT",
                    job_id=context["job_id"],
                    decision_request_event_id=decision_request_event_id,
                    record=successor_snapshot,
                )
            )
            successor_jxs = "JXS_" + _sha({
                "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
                "job_authority_event_id": successor_jae,
                "snapshot_content_sha256": successor_snapshot_binding.artifact_sha256,
            })

            v3 = context["v3"]
            request_source = context["request_source"]
            transition = {
                "schema": "RUNTIME_JOB_PREAPPROVAL_CONTROLLED_TRANSITION_INTENT_V1",
                "predecessor_stage": "DRE_PENDING_NO_TERMINAL_DECISION",
                "transition_code": "CONTROLLED_REOPEN_RUNTIME_MIGRATION",
                "predecessor_job_authority_event_id": context["predecessor_job_authority_event_id"],
                "predecessor_job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
                "predecessor_job_execution_authority_snapshot_sha256": v3["job_execution_authority_snapshot_sha256"],
                "predecessor_job_execution_snapshot_registration_sha256": v3["job_execution_snapshot_registration_sha256"],
                "predecessor_decision_request_event_id": decision_request_event_id,
                "predecessor_decision_request_identity_sha256": request_source["decision_request_identity_sha256"],
                "successor_job_authority_event_id": successor_jae,
                "successor_job_authority_binding_sha256": authority_binding_sha,
                "successor_job_execution_authority_snapshot_id": successor_jxs,
                "successor_job_execution_authority_snapshot_sha256": successor_snapshot_binding.artifact_sha256,
                "successor_job_execution_authority_snapshot_artifact_identity_sha256":
                    successor_snapshot_binding.artifact_identity_sha256,
                "successor_job_execution_authority_snapshot_artifact_revision":
                    successor_snapshot_binding.artifact_revision,
                "successor_job_execution_authority_snapshot_artifact_sha256":
                    successor_snapshot_binding.artifact_sha256,
                "successor_preparation_state": "PREPARED_NON_EXECUTION_ELIGIBLE",
                "successor_activation_required": True,
            }
            transition_binding_dict, transition_binding = self._persist_controlled_reopen_json_v1(
                kind="PREAPPROVAL_TRANSITION_INTENT",
                job_id=context["job_id"],
                decision_request_event_id=decision_request_event_id,
                record=transition,
            )
            claim = self.job_authority.claim_or_replay_one_transition_bound_successor_lineage_v1(
                transition_intent_binding=transition_binding,
                successor_snapshot_binding=successor_snapshot_binding,
            )
            if (
                claim.get("successor_job_authority_event_id") != successor_jae
                or claim.get("successor_job_execution_authority_snapshot_id") != successor_jxs
                or claim.get("transition_intent_sha256") != transition_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "CONTROLLED_REOPEN_CURRENTNESS",
                    "successor lineage claim differs from prepared transition",
                )

            actor_identity = context["actor_authority_identity_sha256"]
            action = {
                "schema": "RUNTIME_EXPLICIT_HUMAN_NON_APPROVAL_ACTION_RECEIPT_SEMANTIC_V1",
                "decision_request_event_id": decision_request_event_id,
                "decision_request_identity_sha256": request_source["decision_request_identity_sha256"],
                "decision_request_content_sha256": v3["decision_request_content_sha256"],
                "decision_scope_sha256": v3["decision_scope_sha256"],
                "actor_authority_identity_sha256": actor_identity,
                "action_code": "SUPERSEDE_FOR_CONTROLLED_REOPEN",
                "preapproval_transition_intent_sha256": transition_binding.artifact_sha256,
            }
            action_binding_dict, action_binding = self._persist_controlled_reopen_json_v1(
                kind="NON_APPROVAL_HUMAN_ACTION_RECEIPT",
                job_id=context["job_id"],
                decision_request_event_id=decision_request_event_id,
                record=action,
            )
            nonapproval_terminal = {
                "schema": "RUNTIME_NON_APPROVAL_TERMINAL_HUMAN_DECISION_BINDING_V1",
                "job_authority_event_id": context["predecessor_job_authority_event_id"],
                "job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
                "job_execution_authority_snapshot_sha256": v3["job_execution_authority_snapshot_sha256"],
                "job_execution_snapshot_registration_sha256": v3["job_execution_snapshot_registration_sha256"],
                "decision_request_event_id": decision_request_event_id,
                "decision_request_identity_sha256": request_source["decision_request_identity_sha256"],
                "decision_request_content_sha256": v3["decision_request_content_sha256"],
                "decision_scope_sha256": v3["decision_scope_sha256"],
                "human_action_receipt_sha256": action_binding.artifact_sha256,
                "human_action_receipt_artifact_identity_sha256": action_binding.artifact_identity_sha256,
                "human_action_receipt_artifact_revision": action_binding.artifact_revision,
                "human_action_receipt_artifact_sha256": action_binding.artifact_sha256,
                "terminal_decision_code": "SUPERSEDED_FOR_CONTROLLED_REOPEN",
                "preapproval_transition_intent_sha256": transition_binding.artifact_sha256,
                "preapproval_transition_intent_artifact_identity_sha256": transition_binding.artifact_identity_sha256,
                "preapproval_transition_intent_artifact_revision": transition_binding.artifact_revision,
                "preapproval_transition_intent_artifact_sha256": transition_binding.artifact_sha256,
                "successor_job_authority_event_id": successor_jae,
                "successor_job_execution_authority_snapshot_id": successor_jxs,
                "successor_job_execution_authority_snapshot_sha256": successor_snapshot_binding.artifact_sha256,
                "successor_job_execution_authority_snapshot_artifact_identity_sha256":
                    successor_snapshot_binding.artifact_identity_sha256,
                "successor_job_execution_authority_snapshot_artifact_revision":
                    successor_snapshot_binding.artifact_revision,
                "successor_job_execution_authority_snapshot_artifact_sha256":
                    successor_snapshot_binding.artifact_sha256,
            }
            terminal_binding_dict, terminal_binding = self._persist_controlled_reopen_json_v1(
                kind="NON_APPROVAL_TERMINAL_BINDING",
                job_id=context["job_id"],
                decision_request_event_id=decision_request_event_id,
                record=nonapproval_terminal,
            )
            terminal_source = self.human_decision.commit_or_replay_one_terminal_human_decision_for_request_v2(
                decision_request_event_id=decision_request_event_id,
                terminal_decision_code="SUPERSEDED_FOR_CONTROLLED_REOPEN",
                human_action_receipt_binding=action_binding,
                non_approval_terminal_binding=terminal_binding,
            )
            if (
                terminal_source.get("terminal_decision_code") != "SUPERSEDED_FOR_CONTROLLED_REOPEN"
                or terminal_source.get("non_approval_terminal_binding_sha256") != terminal_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "CONTROLLED_REOPEN_CURRENTNESS",
                    "HumanDecision terminal source differs from exact controlled-reopen binding",
                )

            result = self._complete_dre_pending_runtime_migration_activation_v1(
                context=context,
                terminal=nonapproval_terminal,
                terminal_binding=terminal_binding,
            )
            result.update({
                "controlled_successor_jae_issuance_key_sha256":
                    issuance["controlled_successor_jae_issuance_key_sha256"],
                "successor_runtime_contract_manifest_sha256": current_contract_sha,
                "successor_snapshot_binding": successor_snapshot_binding_dict,
                "preapproval_transition_intent_binding": transition_binding_dict,
                "human_action_receipt_binding": action_binding_dict,
                "non_approval_terminal_binding": terminal_binding_dict,
            })
            return result
        except GeneralChatFormalPrepareError:
            raise
        except (JobAuthorityError, HumanDecisionAuthorityError, R009OpaqueArtifactError, KeyError, TypeError, ValueError) as exc:
            raise GeneralChatFormalPrepareError(
                "CONTROLLED_REOPEN_REJECTED",
                str(exc),
            ) from exc


    def _validate_recovery_v2_successor_for_live_approval_v1(
        self,
        *,
        registration: dict[str, Any],
        successor_job_authority_event_id: str,
        expected_successor_job_execution_authority_snapshot_id: str,
        error_code: str,
    ) -> None:
        """Exact-bind the one V2 post-APPROVED invalidation successor admitted to live-approval flow."""
        slot_key = registration.get("predecessor_approval_slot_key_sha256")
        invalidation_sha = registration.get("predecessor_invalidation_sha256")
        transition_sha = registration.get("job_transition_intent_sha256")
        if (
            registration.get("schema")
            != "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2"
            or registration.get("activation_basis")
            != "CONTROLLED_SUCCESSOR_AFTER_PREDECESSOR_INVALIDATION"
            or not isinstance(slot_key, str)
            or _SHA_RE.fullmatch(slot_key) is None
            or not isinstance(invalidation_sha, str)
            or _SHA_RE.fullmatch(invalidation_sha) is None
            or not isinstance(transition_sha, str)
            or _SHA_RE.fullmatch(transition_sha) is None
        ):
            raise GeneralChatFormalPrepareError(
                error_code,
                "recovery V2 successor exact invalidation bindings are missing",
            )

        terminal = self.job_authority.load_exact_approval_execution_slot_terminal_v1(
            approval_slot_key_sha256=slot_key
        )
        if (
            terminal.get("terminal_outcome")
            != "INVALIDATED_BEFORE_ATTEMPT_NO_EXECUTION"
            or _sha(terminal) != invalidation_sha
            or terminal.get("successor_job_authority_event_id")
            != successor_job_authority_event_id
            or terminal.get("successor_job_execution_authority_snapshot_id")
            != expected_successor_job_execution_authority_snapshot_id
            or terminal.get("successor_job_execution_authority_snapshot_sha256")
            != registration.get("job_execution_authority_snapshot_sha256")
            or terminal.get("job_transition_intent_sha256") != transition_sha
        ):
            raise GeneralChatFormalPrepareError(
                error_code,
                "recovery V2 successor invalidation terminal differs",
            )

    def issue_or_replay_active_successor_live_approval_request_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        expected_job_id: str,
        successor_job_authority_event_id: str,
        expected_successor_job_execution_authority_snapshot_id: str,
    ) -> dict[str, Any]:
        """Issue/replay the one live-attempt DRE for an exact already-active controlled successor."""
        if not isinstance(project_id, str) or not project_id:
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_INPUT",
                "project_id required",
                status_code=400,
            )
        if not isinstance(chat_id, str) or not chat_id:
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_INPUT",
                "chat_id required",
                status_code=400,
            )
        if not isinstance(expected_job_id, str) or not expected_job_id:
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_INPUT",
                "expected_job_id required",
                status_code=400,
            )
        if (
            not isinstance(successor_job_authority_event_id, str)
            or re.fullmatch(r"JAE_[0-9a-f]{64}", successor_job_authority_event_id) is None
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_INPUT",
                "successor_job_authority_event_id must be exact JAE_<64 lowercase hex>",
                status_code=400,
            )
        if (
            not isinstance(expected_successor_job_execution_authority_snapshot_id, str)
            or re.fullmatch(
                r"JXS_[0-9a-f]{64}",
                expected_successor_job_execution_authority_snapshot_id,
            )
            is None
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_INPUT",
                "expected_successor_job_execution_authority_snapshot_id must be exact JXS_<64 lowercase hex>",
                status_code=400,
            )

        active_source, registration, registration_binding = (
            self.job_authority.load_exact_active_registration_source_by_jae_v1(
                job_authority_event_id=successor_job_authority_event_id
            )
        )
        registration_schema = registration.get("schema")
        activation_basis = registration.get("activation_basis")
        v3_eligible = (
            registration_schema == "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V3"
            and activation_basis in {
                "CONTROLLED_SUCCESSOR_AFTER_PRE_DRE_SUPERSESSION",
                "CONTROLLED_SUCCESSOR_AFTER_DRE_NON_APPROVAL_TERMINAL",
            }
        )
        recovery_v2_eligible = (
            registration_schema == "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2"
            and activation_basis
                == "CONTROLLED_SUCCESSOR_AFTER_PREDECESSOR_INVALIDATION"
        )
        if (
            active_source.get("job_execution_authority_snapshot_id")
            != expected_successor_job_execution_authority_snapshot_id
            or registration.get("job_authority_event_id")
            != successor_job_authority_event_id
            or registration.get("job_execution_authority_snapshot_id")
            != expected_successor_job_execution_authority_snapshot_id
            or not (v3_eligible or recovery_v2_eligible)
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_CURRENTNESS",
                "exact active registration is not the requested controlled successor",
            )
        if recovery_v2_eligible:
            self._validate_recovery_v2_successor_for_live_approval_v1(
                registration=registration,
                successor_job_authority_event_id=successor_job_authority_event_id,
                expected_successor_job_execution_authority_snapshot_id=
                    expected_successor_job_execution_authority_snapshot_id,
                error_code="SUCCESSOR_APPROVAL_REQUEST_CURRENTNESS",
            )

        snapshot_binding = R009OpaqueArtifactBinding(
            registration["job_execution_authority_snapshot_artifact_identity_sha256"],
            registration["job_execution_authority_snapshot_artifact_revision"],
            registration["job_execution_authority_snapshot_artifact_sha256"],
        )
        snapshot = self._load_exact_json_binding_v1(
            binding=snapshot_binding,
            label="active controlled-successor snapshot",
        )
        if (
            snapshot.get("schema") != "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1"
            or snapshot.get("job_authority_event_id") != successor_job_authority_event_id
            or snapshot_binding.artifact_sha256
            != active_source.get("job_execution_authority_snapshot_sha256")
            or snapshot_binding.artifact_sha256
            != registration.get("job_execution_authority_snapshot_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_CURRENTNESS",
                "active successor snapshot differs from exact registration",
            )

        frozen_binding = R009OpaqueArtifactBinding(
            snapshot["frozen_binding_manifest_artifact_identity_sha256"],
            snapshot["frozen_binding_manifest_artifact_revision"],
            snapshot["frozen_binding_manifest_artifact_sha256"],
        )
        frozen = self._load_exact_json_binding_v1(
            binding=frozen_binding,
            label="active successor frozen binding manifest",
        )
        if (
            frozen.get("schema") != "RUNTIME_S1_GENERAL_CHAT_FROZEN_BINDING_MANIFEST_V1"
            or frozen.get("job_id") != expected_job_id
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_SCOPE_MISMATCH",
                "exact successor frozen manifest differs from requested Job",
            )

        intake_binding = self._r009_binding_from_dict_v1(
            frozen.get("web_formal_job_intake_binding"),
            "Web formal intake",
        )
        intake = self._load_exact_json_binding_v1(
            binding=intake_binding,
            label="Web formal intake",
        )
        if (
            intake.get("schema") != "WEB_FORMAL_JOB_INTAKE_BINDING_V1"
            or intake.get("job_id") != expected_job_id
            or intake.get("project_id") != project_id
            or intake.get("chat_id") != chat_id
            or intake_binding.artifact_sha256
            != frozen.get("web_formal_job_intake_binding_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_SCOPE_MISMATCH",
                "exact Web intake does not bind the requested Project/Chat/Job",
            )

        request_content = {
            "schema": "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_CONTENT_SEMANTIC_V1",
            "job_authority_event_id": successor_job_authority_event_id,
            "job_execution_authority_snapshot_id":
                expected_successor_job_execution_authority_snapshot_id,
            "job_execution_authority_snapshot_sha256": snapshot_binding.artifact_sha256,
            "requested_decision_code": "APPROVE_ONE_LIVE_ATTEMPT",
            **dict(FIRST_SLICE_BUDGET),
        }
        request_content_binding = _persist_exact_json(
            self.store,
            kind=f"SUCCESSOR_LIVE_DECISION_REQUEST_CONTENT:{successor_job_authority_event_id}",
            job_id=expected_job_id,
            record=request_content,
        )

        request_key = _sha({
            "namespace": "RUNTIME_LIVE_EXECUTION_ONE_REQUEST_PER_ACTIVE_SNAPSHOT_V1",
            "job_authority_event_id": successor_job_authority_event_id,
            "job_execution_authority_snapshot_id":
                expected_successor_job_execution_authority_snapshot_id,
            "job_execution_authority_snapshot_sha256": snapshot_binding.artifact_sha256,
            "job_execution_snapshot_registration_sha256":
                registration_binding.artifact_sha256,
        })
        dre = "DRE_" + request_key
        v3 = {
            "schema": "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_BINDING_V3",
            "snapshot_decision_request_key_sha256": request_key,
            "decision_request_event_id": dre,
            "job_authority_event_id": successor_job_authority_event_id,
            "job_execution_authority_snapshot_id":
                expected_successor_job_execution_authority_snapshot_id,
            "job_execution_authority_snapshot_sha256": snapshot_binding.artifact_sha256,
            "job_execution_authority_snapshot_artifact_identity_sha256":
                snapshot_binding.artifact_identity_sha256,
            "job_execution_authority_snapshot_artifact_revision":
                snapshot_binding.artifact_revision,
            "job_execution_authority_snapshot_artifact_sha256":
                snapshot_binding.artifact_sha256,
            "job_execution_snapshot_registration_sha256":
                registration_binding.artifact_sha256,
            "job_execution_snapshot_registration_artifact_identity_sha256":
                registration_binding.artifact_identity_sha256,
            "job_execution_snapshot_registration_artifact_revision":
                registration_binding.artifact_revision,
            "job_execution_snapshot_registration_artifact_sha256":
                registration_binding.artifact_sha256,
            "decision_request_content_sha256": request_content_binding["artifact_sha256"],
            "decision_request_content_artifact_identity_sha256":
                request_content_binding["artifact_identity_sha256"],
            "decision_request_content_artifact_revision":
                request_content_binding["artifact_revision"],
            "decision_request_content_artifact_sha256":
                request_content_binding["artifact_sha256"],
            "decision_scope_sha256": snapshot_binding.artifact_sha256,
            **dict(FIRST_SLICE_BUDGET),
        }
        decision_identity = _sha(v3)
        branch_key = _sha({
            "namespace": "RUNTIME_JOB_PREAPPROVAL_BRANCH_KEY_V1",
            "predecessor_job_authority_event_id": successor_job_authority_event_id,
            "predecessor_job_execution_authority_snapshot_id":
                expected_successor_job_execution_authority_snapshot_id,
            "predecessor_job_execution_authority_snapshot_sha256":
                snapshot_binding.artifact_sha256,
            "predecessor_job_execution_snapshot_registration_sha256":
                registration_binding.artifact_sha256,
        })
        branch = {
            "schema": "RUNTIME_JOB_PREAPPROVAL_DRE_BRANCH_SELECTION_SEMANTIC_V2",
            "preapproval_branch_key_sha256": branch_key,
            "branch_code": "DRE_ISSUANCE_SELECTED",
            "predecessor_job_authority_event_id": successor_job_authority_event_id,
            "predecessor_job_execution_authority_snapshot_id":
                expected_successor_job_execution_authority_snapshot_id,
            "predecessor_job_execution_authority_snapshot_sha256":
                snapshot_binding.artifact_sha256,
            "predecessor_job_execution_snapshot_registration_sha256":
                registration_binding.artifact_sha256,
            "snapshot_decision_request_key_sha256": request_key,
            "decision_request_event_id": dre,
            "decision_request_identity_sha256": decision_identity,
            "request_recovery_mode": "INLINE_COMPLETE_REQUEST_BINDING_V3",
            "decision_request_binding_v3": v3,
        }
        branch_binding_dict = _persist_exact_json(
            self.store,
            kind=f"SUCCESSOR_PREAPPROVAL_DRE_BRANCH:{successor_job_authority_event_id}",
            job_id=expected_job_id,
            record=branch,
        )
        branch_binding = R009OpaqueArtifactBinding(
            branch_binding_dict["artifact_identity_sha256"],
            branch_binding_dict["artifact_revision"],
            branch_binding_dict["artifact_sha256"],
        )
        branch_source = (
            self.job_authority.select_or_replay_one_preapproval_branch_for_active_registration_v2(
                branch_binding=branch_binding
            )
        )
        if (
            branch_source.get("preapproval_branch_key_sha256") != branch_key
            or branch_source.get("branch_code") != "DRE_ISSUANCE_SELECTED"
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_CURRENTNESS",
                "successor DRE branch source differs from exact prepared branch",
            )

        request_source = (
            self.human_decision.issue_or_replay_one_decision_request_for_selected_active_snapshot_v3(
                preapproval_branch_key_sha256=branch_key
            )
        )
        if (
            request_source.get("decision_request_event_id") != dre
            or request_source.get("decision_request_identity_sha256") != decision_identity
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REQUEST_CURRENTNESS",
                "HumanDecision successor request source differs",
            )

        terminal_source = None
        try:
            terminal_source = self.human_decision.load_exact_terminal_source(dre)
        except HumanDecisionAuthorityError as exc:
            if str(exc) != "terminal source absent":
                raise

        base_result = {
            "formal_job": True,
            "job_id": expected_job_id,
            "job_authority_event_id": successor_job_authority_event_id,
            "job_execution_authority_snapshot_id":
                expected_successor_job_execution_authority_snapshot_id,
            "job_execution_authority_snapshot_sha256": snapshot_binding.artifact_sha256,
            "job_execution_snapshot_registration_sha256":
                registration_binding.artifact_sha256,
            "decision_request_event_id": dre,
            "decision_request_identity_sha256": decision_identity,
            "decision_scope_sha256": snapshot_binding.artifact_sha256,
            "requested_decision_code": "APPROVE_ONE_LIVE_ATTEMPT",
            "approval_budget": dict(FIRST_SLICE_BUDGET),
            "credential_value_read": False,
            "network_called": False,
            "model_called": False,
            "grant_created": False,
        }

        if terminal_source is not None:
            if (
                terminal_source.get("decision_request_event_id") != dre
                or terminal_source.get("decision_request_identity_sha256")
                != decision_identity
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_REQUEST_CURRENTNESS",
                    "HumanDecision successor terminal source differs from exact request",
                )
            return {
                **base_result,
                "status": "HUMAN_DECISION_TERMINAL",
                "terminal_decision_code": terminal_source["terminal_decision_code"],
                "terminal_human_action_receipt_sha256":
                    terminal_source["human_action_receipt_sha256"],
                "approval_decision_event_id":
                    terminal_source["approval_decision_event_id"],
                "non_approval_terminal_binding_sha256":
                    terminal_source["non_approval_terminal_binding_sha256"],
            }

        return {
            **base_result,
            "status": "AWAITING_EXPLICIT_HUMAN_APPROVAL",
        }


    def approve_active_plain_initial_live_attempt_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        expected_job_id: str,
        job_authority_event_id: str,
        expected_job_execution_authority_snapshot_id: str,
        decision_request_event_id: str,
    ) -> dict[str, Any]:
        """Commit/replay APPROVED for one no-Source initial General Chat Job.

        The caller must be the explicit product interaction that requests one
        governed generation.  This method performs no Grant creation, attempt
        claim, credential read, provider call, or network action.
        """
        try:
            context = self._controlled_reopen_context_v1(
                project_id=project_id,
                chat_id=chat_id,
                decision_request_event_id=decision_request_event_id,
                expected_job_id=expected_job_id,
            )
            registration = context["predecessor_registration"]
            active_source = context["active_source"]
            request_source = context["request_source"]
            v3 = context["v3"]
            frozen = context["frozen_manifest"]
            job_bundle = context["job_bundle"]
            input_set = frozen.get("input_set")
            if (
                not isinstance(input_set, dict)
                or "library_source_context" in input_set
                or not isinstance(input_set.get("active_context_snapshot"), dict)
                or "retry_lineage" in job_bundle
                or "retry_lineage_sha256" in job_bundle
                or registration.get("schema") != "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2"
                or registration.get("activation_basis") != "INITIAL_JOB_CREATION"
                or registration.get("job_authority_event_id") != job_authority_event_id
                or registration.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or active_source.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or v3.get("job_authority_event_id") != job_authority_event_id
                or v3.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or request_source.get("decision_request_event_id")
                    != decision_request_event_id
                or {key: v3.get(key) for key in FIRST_SLICE_BUDGET}
                    != dict(FIRST_SLICE_BUDGET)
            ):
                raise GeneralChatFormalPrepareError(
                    "PLAIN_INITIAL_APPROVAL_CURRENTNESS",
                    "plain initial Job is not the exact active no-Source approval scope",
                )

            produced = self.human_decision.produce_and_commit_or_replay_one_approved_terminal_for_request_v1(
                decision_request_event_id=decision_request_event_id,
                actor_authority_identity_sha256=context["actor_authority_identity_sha256"],
            )
            terminal = produced.get("terminal_source")
            if (
                not isinstance(terminal, dict)
                or terminal.get("terminal_decision_code") != "APPROVED"
                or terminal.get("decision_request_event_id") != decision_request_event_id
                or terminal.get("decision_request_identity_sha256")
                    != request_source.get("decision_request_identity_sha256")
            ):
                raise GeneralChatFormalPrepareError(
                    "PLAIN_INITIAL_APPROVAL_CURRENTNESS",
                    "plain initial APPROVED terminal differs from exact DRE",
                )
            return {
                "status": "APPROVED_PLAIN_INITIAL_JOB",
                "approval_terminal_current": True,
                "job_id": expected_job_id,
                "job_authority_event_id": job_authority_event_id,
                "job_execution_authority_snapshot_id": expected_job_execution_authority_snapshot_id,
                "decision_request_event_id": decision_request_event_id,
                "human_action_receipt_binding": _binding_dict(
                    produced["human_action_receipt_binding"]
                ),
                "approval_decision_event_binding": _binding_dict(
                    produced["approval_decision_event_binding"]
                ),
                "approval_acceptance_binding": _binding_dict(
                    produced["approval_acceptance_binding"]
                ),
                "network_called": False,
                "model_called": False,
                "secret_read": False,
                "grant_created": False,
                "attempt_claim_created": False,
            }
        except GeneralChatFormalPrepareError:
            raise
        except (HumanDecisionAuthorityError, JobAuthorityError, R009OpaqueArtifactError) as exc:
            raise GeneralChatFormalPrepareError(
                "PLAIN_INITIAL_APPROVAL_REJECTED",
                str(exc),
            ) from exc



    def approve_active_source_initial_live_attempt_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        expected_job_id: str,
        job_authority_event_id: str,
        expected_job_execution_authority_snapshot_id: str,
        decision_request_event_id: str,
    ) -> dict[str, Any]:
        """Commit/replay APPROVED for one exact source-grounded initial Job.

        The caller must be the explicit source Send product interaction.  This
        method is only a fail-closed consumer of the existing HumanDecision
        terminal owner; it performs no Grant creation, attempt claim, credential
        read, provider/model call, or network action.
        """
        try:
            context = self._controlled_reopen_context_v1(
                project_id=project_id,
                chat_id=chat_id,
                decision_request_event_id=decision_request_event_id,
                expected_job_id=expected_job_id,
            )
            registration = context["predecessor_registration"]
            active_source = context["active_source"]
            request_source = context["request_source"]
            v3 = context["v3"]
            frozen = context["frozen_manifest"]
            job_bundle = context["job_bundle"]
            input_set = frozen.get("input_set")
            library_source = input_set.get("library_source_context") if isinstance(input_set, dict) else None
            active_input = input_set.get("active_context_snapshot") if isinstance(input_set, dict) else None
            if (
                not isinstance(input_set, dict)
                or not isinstance(library_source, dict)
                or not isinstance(active_input, dict)
                or "retry_lineage" in input_set
                or "retry_lineage_sha256" in input_set
                or "retry_lineage" in job_bundle
                or "retry_lineage_sha256" in job_bundle
                or registration.get("schema") != "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2"
                or registration.get("activation_basis") != "INITIAL_JOB_CREATION"
                or registration.get("job_authority_event_id") != job_authority_event_id
                or registration.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or active_source.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or v3.get("job_authority_event_id") != job_authority_event_id
                or v3.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or request_source.get("decision_request_event_id") != decision_request_event_id
                or {key: v3.get(key) for key in FIRST_SLICE_BUDGET}
                    != dict(FIRST_SLICE_BUDGET)
            ):
                raise GeneralChatFormalPrepareError(
                    "SOURCE_INITIAL_APPROVAL_CURRENTNESS",
                    "source initial Job is not the exact active initial source approval scope",
                )

            source_context_binding = self._r009_binding_from_dict_v1(
                library_source.get("source_context_artifact_binding"),
                "source context",
            )
            source_context = self._load_exact_json_binding_v1(
                binding=source_context_binding,
                label="source context",
            )
            initiating_binding = {
                "artifact_id": input_set.get("initiating_user_event_artifact_id"),
                "revision": input_set.get("initiating_user_event_artifact_revision"),
                "sha256": input_set.get("initiating_user_event_artifact_sha256"),
            }
            source_facts = self._validate_library_source_context(
                source_context=source_context,
                source_context_sha256=library_source.get("source_context_sha256"),
                project_id=project_id,
                chat_id=chat_id,
                event_id=input_set.get("initiating_user_event_id"),
                content_sha256=input_set.get("initiating_content_sha256"),
                initiating_user_event_binding=initiating_binding,
            )
            expected_source = {
                "source_context_sha256": source_facts["source_context_sha256"],
                "source_ref_id": source_facts["source_ref_id"],
                "source_artifact_id": source_facts["source_artifact_id"],
                "source_artifact_identity_sha256": source_facts["source_artifact_identity_sha256"],
                "source_artifact_revision": source_facts["source_artifact_revision"],
                "source_artifact_sha256": source_facts["source_artifact_sha256"],
                "derivation_sha256": source_facts["derivation_sha256"],
                "selected_source_role": source_facts["selected_source_role"],
                "selected_source_binding_sha256": source_facts["selected_source_binding_sha256"],
                "source_load_plan_sha256": source_facts["source_load_plan_sha256"],
                "source_permission_plan_sha256": source_facts["source_permission_plan_sha256"],
                "source_job_artifact_binding_plan_sha256": source_facts[
                    "source_job_artifact_binding_plan_sha256"
                ],
                "source_predecessor_pack_pin_sha256": source_facts["source_pack_pin_sha256"],
                "question_sha256": source_facts["question_sha256"],
            }
            if (
                source_context_binding.artifact_sha256 != library_source.get("source_context_sha256")
                or any(library_source.get(key) != value for key, value in expected_source.items())
                or job_bundle.get("source_context_sha256") != source_facts["source_context_sha256"]
                or job_bundle.get("source_context_artifact_identity_sha256")
                    != source_context_binding.artifact_identity_sha256
                or job_bundle.get("source_context_artifact_revision")
                    != source_context_binding.artifact_revision
                or job_bundle.get("source_context_artifact_sha256")
                    != source_context_binding.artifact_sha256
                or job_bundle.get("source_ref_id") != source_facts["source_ref_id"]
                or job_bundle.get("source_artifact_identity_sha256")
                    != source_facts["source_artifact_identity_sha256"]
                or job_bundle.get("source_artifact_revision")
                    != source_facts["source_artifact_revision"]
                or job_bundle.get("source_artifact_sha256")
                    != source_facts["source_artifact_sha256"]
                or job_bundle.get("source_derivation_sha256") != source_facts["derivation_sha256"]
                or job_bundle.get("source_load_plan_sha256")
                    != source_facts["source_load_plan_sha256"]
                or job_bundle.get("source_permission_plan_sha256")
                    != source_facts["source_permission_plan_sha256"]
                or job_bundle.get("source_job_artifact_binding_plan_sha256")
                    != source_facts["source_job_artifact_binding_plan_sha256"]
                or job_bundle.get("source_predecessor_pack_pin_sha256")
                    != source_facts["source_pack_pin_sha256"]
            ):
                raise GeneralChatFormalPrepareError(
                    "SOURCE_INITIAL_APPROVAL_CURRENTNESS",
                    "source context differs from frozen input or JobBundle",
                )

            active_binding = self._r009_binding_from_dict_v1(
                active_input.get("active_context_artifact_binding"),
                "active context",
            )
            active_snapshot = self._load_exact_json_binding_v1(
                binding=active_binding,
                label="active context",
            )
            active_facts = self._validate_web_active_context_snapshot_v1(
                active_context_snapshot=active_snapshot,
                active_context_snapshot_sha256=active_input.get("active_context_snapshot_sha256"),
                chat_id=chat_id,
                initiating_user_event_id=input_set.get("initiating_user_event_id"),
                initiating_content_sha256=input_set.get("initiating_content_sha256"),
                accepted_chat_revision=input_set.get("accepted_chat_revision"),
                accepted_head_event_id=input_set.get("accepted_head_event_id"),
            )
            if (
                active_facts.get("active_ancestry_sha256")
                    != active_input.get("active_ancestry_sha256")
                or active_binding.artifact_identity_sha256
                    != job_bundle.get("active_context_artifact_identity_sha256")
                or active_binding.artifact_revision
                    != job_bundle.get("active_context_artifact_revision")
                or active_binding.artifact_sha256
                    != job_bundle.get("active_context_artifact_sha256")
                or active_facts.get("snapshot_sha256")
                    != job_bundle.get("active_context_snapshot_sha256")
                or active_facts.get("active_ancestry_sha256")
                    != job_bundle.get("active_ancestry_sha256")
            ):
                raise GeneralChatFormalPrepareError(
                    "SOURCE_INITIAL_APPROVAL_CURRENTNESS",
                    "active context differs from frozen input or JobBundle",
                )

            produced = self.human_decision.produce_and_commit_or_replay_one_approved_terminal_for_request_v1(
                decision_request_event_id=decision_request_event_id,
                actor_authority_identity_sha256=context["actor_authority_identity_sha256"],
            )
            terminal = produced.get("terminal_source")
            if (
                not isinstance(terminal, dict)
                or terminal.get("terminal_decision_code") != "APPROVED"
                or terminal.get("decision_request_event_id") != decision_request_event_id
                or terminal.get("decision_request_identity_sha256")
                    != request_source.get("decision_request_identity_sha256")
            ):
                raise GeneralChatFormalPrepareError(
                    "SOURCE_INITIAL_APPROVAL_CURRENTNESS",
                    "source initial APPROVED terminal differs from exact DRE",
                )
            return {
                "status": "APPROVED_SOURCE_INITIAL_JOB",
                "approval_terminal_current": True,
                "job_id": expected_job_id,
                "job_authority_event_id": job_authority_event_id,
                "job_execution_authority_snapshot_id": expected_job_execution_authority_snapshot_id,
                "decision_request_event_id": decision_request_event_id,
                "source_ref_id": source_facts["source_ref_id"],
                "source_context_sha256": source_facts["source_context_sha256"],
                "source_artifact_sha256": source_facts["source_artifact_sha256"],
                "human_action_receipt_binding": _binding_dict(
                    produced["human_action_receipt_binding"]
                ),
                "approval_decision_event_binding": _binding_dict(
                    produced["approval_decision_event_binding"]
                ),
                "approval_acceptance_binding": _binding_dict(
                    produced["approval_acceptance_binding"]
                ),
                "network_called": False,
                "model_called": False,
                "secret_read": False,
                "grant_created": False,
                "attempt_claim_created": False,
            }
        except GeneralChatFormalPrepareError:
            raise
        except (HumanDecisionAuthorityError, JobAuthorityError, R009OpaqueArtifactError) as exc:
            raise GeneralChatFormalPrepareError(
                "SOURCE_INITIAL_APPROVAL_REJECTED",
                str(exc),
            ) from exc


    def approve_active_initial_retry_live_attempt_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        expected_job_id: str,
        job_authority_event_id: str,
        expected_job_execution_authority_snapshot_id: str,
        decision_request_event_id: str,
    ) -> dict[str, Any]:
        """Commit/replay APPROVED for one fresh initial Job created by Retry.

        The caller is the explicit Retry user interaction.  This method performs
        no Grant creation, attempt claim, credential read, provider call, or
        network action.
        """
        try:
            context = self._controlled_reopen_context_v1(
                project_id=project_id,
                chat_id=chat_id,
                decision_request_event_id=decision_request_event_id,
                expected_job_id=expected_job_id,
            )
            registration = context["predecessor_registration"]
            active_source = context["active_source"]
            request_source = context["request_source"]
            v3 = context["v3"]
            job_bundle = context["job_bundle"]
            retry_lineage = job_bundle.get("retry_lineage")
            normalized_retry_lineage = _normalize_retry_lineage(retry_lineage)
            if (
                job_bundle.get("retry_lineage_sha256") != _sha(normalized_retry_lineage)
                or registration.get("schema") != "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2"
                or registration.get("activation_basis") != "INITIAL_JOB_CREATION"
                or registration.get("job_authority_event_id") != job_authority_event_id
                or registration.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or active_source.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or v3.get("job_authority_event_id") != job_authority_event_id
                or v3.get("job_execution_authority_snapshot_id")
                    != expected_job_execution_authority_snapshot_id
                or request_source.get("decision_request_event_id")
                    != decision_request_event_id
                or {key: v3.get(key) for key in FIRST_SLICE_BUDGET}
                    != dict(FIRST_SLICE_BUDGET)
            ):
                raise GeneralChatFormalPrepareError(
                    "RETRY_APPROVAL_CURRENTNESS",
                    "fresh Retry Job is not the exact active initial approval scope",
                )

            produced = self.human_decision.produce_and_commit_or_replay_one_approved_terminal_for_request_v1(
                decision_request_event_id=decision_request_event_id,
                actor_authority_identity_sha256=context["actor_authority_identity_sha256"],
            )
            terminal = produced.get("terminal_source")
            if (
                not isinstance(terminal, dict)
                or terminal.get("terminal_decision_code") != "APPROVED"
                or terminal.get("decision_request_event_id") != decision_request_event_id
                or terminal.get("decision_request_identity_sha256")
                    != request_source.get("decision_request_identity_sha256")
            ):
                raise GeneralChatFormalPrepareError(
                    "RETRY_APPROVAL_CURRENTNESS",
                    "fresh Retry APPROVED terminal differs from exact DRE",
                )
            return {
                "status": "APPROVED_FRESH_RETRY_JOB",
                "approval_terminal_current": True,
                "job_id": expected_job_id,
                "job_authority_event_id": job_authority_event_id,
                "job_execution_authority_snapshot_id": expected_job_execution_authority_snapshot_id,
                "decision_request_event_id": decision_request_event_id,
                "retry_lineage": normalized_retry_lineage,
                "retry_lineage_sha256": _sha(normalized_retry_lineage),
                "human_action_receipt_binding": _binding_dict(
                    produced["human_action_receipt_binding"]
                ),
                "approval_decision_event_binding": _binding_dict(
                    produced["approval_decision_event_binding"]
                ),
                "approval_acceptance_binding": _binding_dict(
                    produced["approval_acceptance_binding"]
                ),
                "network_called": False,
                "model_called": False,
                "secret_read": False,
                "grant_created": False,
                "attempt_claim_created": False,
            }
        except GeneralChatFormalPrepareError:
            raise
        except (HumanDecisionAuthorityError, JobAuthorityError, R009OpaqueArtifactError) as exc:
            raise GeneralChatFormalPrepareError(
                "RETRY_APPROVAL_REJECTED",
                str(exc),
            ) from exc


    def approve_active_successor_live_attempt_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        expected_job_id: str,
        successor_job_authority_event_id: str,
        expected_successor_job_execution_authority_snapshot_id: str,
        decision_request_event_id: str,
    ) -> dict[str, Any]:
        """Commit/replay one exact APPROVED HumanDecision terminal for an active controlled successor."""
        if not isinstance(project_id, str) or not project_id:
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_INPUT",
                "project_id required",
                status_code=400,
            )
        if not isinstance(chat_id, str) or not chat_id:
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_INPUT",
                "chat_id required",
                status_code=400,
            )
        if not isinstance(expected_job_id, str) or not expected_job_id:
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_INPUT",
                "expected_job_id required",
                status_code=400,
            )
        if (
            not isinstance(successor_job_authority_event_id, str)
            or re.fullmatch(r"JAE_[0-9a-f]{64}", successor_job_authority_event_id) is None
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_INPUT",
                "successor_job_authority_event_id must be exact JAE_<64 lowercase hex>",
                status_code=400,
            )
        if (
            not isinstance(expected_successor_job_execution_authority_snapshot_id, str)
            or re.fullmatch(
                r"JXS_[0-9a-f]{64}",
                expected_successor_job_execution_authority_snapshot_id,
            ) is None
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_INPUT",
                "expected_successor_job_execution_authority_snapshot_id must be exact JXS_<64 lowercase hex>",
                status_code=400,
            )
        if (
            not isinstance(decision_request_event_id, str)
            or re.fullmatch(r"DRE_[0-9a-f]{64}", decision_request_event_id) is None
        ):
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_INPUT",
                "decision_request_event_id must be exact DRE_<64 lowercase hex>",
                status_code=400,
            )

        try:
            active_source, registration, registration_binding = (
                self.job_authority.load_exact_active_registration_source_by_jae_v1(
                    job_authority_event_id=successor_job_authority_event_id
                )
            )
            registration_schema = registration.get("schema")
            activation_basis = registration.get("activation_basis")
            v3_eligible = (
                registration_schema == "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V3"
                and activation_basis in {
                    "CONTROLLED_SUCCESSOR_AFTER_PRE_DRE_SUPERSESSION",
                    "CONTROLLED_SUCCESSOR_AFTER_DRE_NON_APPROVAL_TERMINAL",
                }
            )
            recovery_v2_eligible = (
                registration_schema == "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2"
                and activation_basis
                    == "CONTROLLED_SUCCESSOR_AFTER_PREDECESSOR_INVALIDATION"
            )
            if (
                not (v3_eligible or recovery_v2_eligible)
                or registration.get("job_authority_event_id")
                    != successor_job_authority_event_id
                or registration.get("job_execution_authority_snapshot_id")
                    != expected_successor_job_execution_authority_snapshot_id
                or active_source.get("job_execution_authority_snapshot_id")
                    != expected_successor_job_execution_authority_snapshot_id
                or active_source.get("job_execution_authority_snapshot_sha256")
                    != registration.get("job_execution_authority_snapshot_sha256")
                or active_source.get("registration_sha256")
                    != registration_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_CURRENTNESS",
                    "exact active controlled-successor registration differs",
                )
            if recovery_v2_eligible:
                self._validate_recovery_v2_successor_for_live_approval_v1(
                    registration=registration,
                    successor_job_authority_event_id=successor_job_authority_event_id,
                    expected_successor_job_execution_authority_snapshot_id=
                        expected_successor_job_execution_authority_snapshot_id,
                    error_code="SUCCESSOR_APPROVAL_CURRENTNESS",
                )

            snapshot_binding = R009OpaqueArtifactBinding(
                registration["job_execution_authority_snapshot_artifact_identity_sha256"],
                registration["job_execution_authority_snapshot_artifact_revision"],
                registration["job_execution_authority_snapshot_artifact_sha256"],
            )
            snapshot = self._load_exact_json_binding_v1(
                binding=snapshot_binding,
                label="approval active successor snapshot",
            )
            if (
                snapshot.get("schema") != "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1"
                or snapshot.get("job_authority_event_id")
                    != successor_job_authority_event_id
                or registration.get("job_execution_authority_snapshot_sha256")
                    != snapshot_binding.artifact_sha256
                or active_source.get("job_execution_authority_snapshot_sha256")
                    != snapshot_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_CURRENTNESS",
                    "active successor snapshot differs from exact registration",
                )

            frozen_binding = R009OpaqueArtifactBinding(
                snapshot["frozen_binding_manifest_artifact_identity_sha256"],
                snapshot["frozen_binding_manifest_artifact_revision"],
                snapshot["frozen_binding_manifest_artifact_sha256"],
            )
            frozen = self._load_exact_json_binding_v1(
                binding=frozen_binding,
                label="approval active successor frozen binding manifest",
            )
            if (
                frozen.get("schema")
                    != "RUNTIME_S1_GENERAL_CHAT_FROZEN_BINDING_MANIFEST_V1"
                or frozen.get("job_id") != expected_job_id
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_SCOPE_MISMATCH",
                    "exact successor frozen manifest differs from requested Job",
                )

            intake_binding = self._r009_binding_from_dict_v1(
                frozen.get("web_formal_job_intake_binding"),
                "approval Web formal intake",
            )
            intake = self._load_exact_json_binding_v1(
                binding=intake_binding,
                label="approval Web formal intake",
            )
            if (
                intake.get("schema") != "WEB_FORMAL_JOB_INTAKE_BINDING_V1"
                or intake.get("job_id") != expected_job_id
                or intake.get("project_id") != project_id
                or intake.get("chat_id") != chat_id
                or intake_binding.artifact_sha256
                    != frozen.get("web_formal_job_intake_binding_sha256")
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_SCOPE_MISMATCH",
                    "exact Web intake does not bind the requested Project/Chat/Job",
                )

            request_source = self.human_decision.load_exact_request_source(
                decision_request_event_id
            )
            v3 = request_source["decision_request_binding_v3"]
            decision_identity = request_source["decision_request_identity_sha256"]
            if (
                request_source.get("decision_request_event_id")
                    != decision_request_event_id
                or v3.get("schema")
                    != "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_BINDING_V3"
                or v3.get("decision_request_event_id")
                    != decision_request_event_id
                or v3.get("job_authority_event_id")
                    != successor_job_authority_event_id
                or v3.get("job_execution_authority_snapshot_id")
                    != expected_successor_job_execution_authority_snapshot_id
                or v3.get("job_execution_authority_snapshot_sha256")
                    != snapshot_binding.artifact_sha256
                or v3.get("job_execution_authority_snapshot_artifact_identity_sha256")
                    != snapshot_binding.artifact_identity_sha256
                or v3.get("job_execution_authority_snapshot_artifact_revision")
                    != snapshot_binding.artifact_revision
                or v3.get("job_execution_authority_snapshot_artifact_sha256")
                    != snapshot_binding.artifact_sha256
                or v3.get("job_execution_snapshot_registration_sha256")
                    != registration_binding.artifact_sha256
                or v3.get("job_execution_snapshot_registration_artifact_identity_sha256")
                    != registration_binding.artifact_identity_sha256
                or v3.get("job_execution_snapshot_registration_artifact_revision")
                    != registration_binding.artifact_revision
                or v3.get("job_execution_snapshot_registration_artifact_sha256")
                    != registration_binding.artifact_sha256
                or v3.get("decision_scope_sha256")
                    != snapshot_binding.artifact_sha256
                or {
                    key: v3.get(key)
                    for key in FIRST_SLICE_BUDGET
                } != dict(FIRST_SLICE_BUDGET)
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_CURRENTNESS",
                    "exact successor DRE request does not bind current successor Authority",
                )

            request_content_binding = R009OpaqueArtifactBinding(
                v3["decision_request_content_artifact_identity_sha256"],
                v3["decision_request_content_artifact_revision"],
                v3["decision_request_content_artifact_sha256"],
            )
            request_content = self._load_exact_json_binding_v1(
                binding=request_content_binding,
                label="approval successor DRE request content",
            )
            request_content_manifest, _request_content_bytes = (
                self.store.load_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=
                        request_content_binding.artifact_identity_sha256,
                    artifact_revision=request_content_binding.artifact_revision,
                    artifact_sha256=request_content_binding.artifact_sha256,
                )
            )
            if (
                request_content_manifest.job_id != expected_job_id
                or request_content.get("schema")
                    != "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_CONTENT_SEMANTIC_V1"
                or request_content.get("job_authority_event_id")
                    != successor_job_authority_event_id
                or request_content.get("job_execution_authority_snapshot_id")
                    != expected_successor_job_execution_authority_snapshot_id
                or request_content.get("job_execution_authority_snapshot_sha256")
                    != snapshot_binding.artifact_sha256
                or request_content.get("requested_decision_code")
                    != "APPROVE_ONE_LIVE_ATTEMPT"
                or {
                    key: request_content.get(key)
                    for key in FIRST_SLICE_BUDGET
                } != dict(FIRST_SLICE_BUDGET)
                or v3.get("decision_request_content_sha256")
                    != request_content_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_CURRENTNESS",
                    "exact successor DRE content is not one bounded live-attempt approval request",
                )

            branch_key = request_source.get("preapproval_branch_key_sha256")
            branch_source, branch, branch_binding = (
                self.job_authority.load_exact_preapproval_branch_by_key_v1(
                    preapproval_branch_key_sha256=branch_key
                )
            )
            if (
                branch.get("schema")
                    != "RUNTIME_JOB_PREAPPROVAL_DRE_BRANCH_SELECTION_SEMANTIC_V2"
                or branch.get("branch_code") != "DRE_ISSUANCE_SELECTED"
                or branch.get("predecessor_job_authority_event_id")
                    != successor_job_authority_event_id
                or branch.get("predecessor_job_execution_authority_snapshot_id")
                    != expected_successor_job_execution_authority_snapshot_id
                or branch.get("predecessor_job_execution_authority_snapshot_sha256")
                    != snapshot_binding.artifact_sha256
                or branch.get("predecessor_job_execution_snapshot_registration_sha256")
                    != registration_binding.artifact_sha256
                or branch.get("decision_request_event_id")
                    != decision_request_event_id
                or branch.get("decision_request_identity_sha256")
                    != decision_identity
                or branch.get("decision_request_binding_v3") != v3
                or branch_source.get("branch_artifact_identity_sha256")
                    != branch_binding.artifact_identity_sha256
                or branch_source.get("branch_artifact_revision")
                    != branch_binding.artifact_revision
                or branch_source.get("branch_artifact_sha256")
                    != branch_binding.artifact_sha256
                or request_source.get(
                    "preapproval_branch_selection_artifact_identity_sha256"
                ) != branch_binding.artifact_identity_sha256
                or request_source.get(
                    "preapproval_branch_selection_artifact_revision"
                ) != branch_binding.artifact_revision
                or request_source.get(
                    "preapproval_branch_selection_artifact_sha256"
                ) != branch_binding.artifact_sha256
                or request_source.get(
                    "preapproval_branch_selection_semantic_sha256"
                ) != branch_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_CURRENTNESS",
                    "exact successor DRE branch does not bind exact request/current successor",
                )

            existing_terminal = None
            try:
                existing_terminal = self.human_decision.load_exact_terminal_source(
                    decision_request_event_id
                )
            except HumanDecisionAuthorityError as exc:
                if str(exc) != "terminal source absent":
                    raise

            if existing_terminal is not None:
                if (
                    existing_terminal.get("decision_request_event_id")
                        != decision_request_event_id
                    or existing_terminal.get("decision_request_identity_sha256")
                        != decision_identity
                ):
                    raise GeneralChatFormalPrepareError(
                        "SUCCESSOR_APPROVAL_CURRENTNESS",
                        "existing HumanDecision terminal does not bind exact successor DRE",
                    )
                if existing_terminal.get("terminal_decision_code") != "APPROVED":
                    raise GeneralChatFormalPrepareError(
                        "SUCCESSOR_APPROVAL_TERMINAL_CONFLICT",
                        "successor DRE already has a non-APPROVED terminal decision",
                    )

            actor_source = (
                self.human_decision.load_exact_local_single_user_opaque_actor_identity_v1()
            )
            actor_sha = actor_source.get("actor_authority_identity_sha256")
            if (
                actor_source.get("schema")
                    != "RUNTIME_LOCAL_SINGLE_USER_OPAQUE_ACTOR_IDENTITY_SOURCE_V1"
                or not isinstance(actor_sha, str)
                or _SHA_RE.fullmatch(actor_sha) is None
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_ACTOR_IDENTITY",
                    "Runtime local opaque actor identity source is invalid",
                )

            approved = (
                self.human_decision.produce_and_commit_or_replay_one_approved_terminal_for_request_v1(
                    decision_request_event_id=decision_request_event_id,
                    actor_authority_identity_sha256=actor_sha,
                )
            )
            terminal_source = approved["terminal_source"]
            terminal_reload = self.human_decision.load_exact_terminal_source(
                decision_request_event_id
            )
            if terminal_source != terminal_reload:
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_CURRENTNESS",
                    "APPROVED terminal source changed on exact reload",
                )
            if (
                terminal_source.get("decision_request_event_id")
                    != decision_request_event_id
                or terminal_source.get("decision_request_identity_sha256")
                    != decision_identity
                or terminal_source.get("terminal_decision_code") != "APPROVED"
                or not isinstance(
                    terminal_source.get("approval_decision_event_id"),
                    str,
                )
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_CURRENTNESS",
                    "APPROVED terminal does not bind exact successor DRE",
                )

            action_binding = approved["human_action_receipt_binding"]
            approval_binding = approved["approval_decision_event_binding"]
            acceptance_binding = approved["approval_acceptance_binding"]
            if (
                terminal_source.get("human_action_receipt_sha256")
                    != action_binding.artifact_sha256
                or terminal_source.get("approval_decision_event_binding_sha256")
                    != approval_binding.artifact_sha256
                or terminal_source.get("approval_acceptance_semantic_sha256")
                    != acceptance_binding.artifact_sha256
            ):
                raise GeneralChatFormalPrepareError(
                    "SUCCESSOR_APPROVAL_CURRENTNESS",
                    "APPROVED terminal source differs from exact approval artifacts",
                )

            return {
                "status": "HUMAN_DECISION_TERMINAL",
                "formal_job": True,
                "job_id": expected_job_id,
                "job_authority_event_id": successor_job_authority_event_id,
                "job_execution_authority_snapshot_id":
                    expected_successor_job_execution_authority_snapshot_id,
                "job_execution_authority_snapshot_sha256":
                    snapshot_binding.artifact_sha256,
                "job_execution_snapshot_registration_sha256":
                    registration_binding.artifact_sha256,
                "decision_request_event_id": decision_request_event_id,
                "decision_request_identity_sha256": decision_identity,
                "decision_scope_sha256": snapshot_binding.artifact_sha256,
                "terminal_decision_code": "APPROVED",
                "approval_decision_event_id":
                    terminal_source["approval_decision_event_id"],
                "human_action_receipt_binding": _binding_dict(action_binding),
                "approval_decision_event_binding": _binding_dict(approval_binding),
                "approval_acceptance_binding": _binding_dict(acceptance_binding),
                "terminal_source": dict(terminal_source),
                "approval_budget": dict(FIRST_SLICE_BUDGET),
                "actor_identity_source_loaded_by_runtime": True,
                "credential_value_read": False,
                "network_called": False,
                "model_called": False,
                "grant_created": False,
                "attempt_claim_created": False,
            }
        except GeneralChatFormalPrepareError:
            raise
        except (
            JobAuthorityError,
            HumanDecisionAuthorityError,
            R009OpaqueArtifactError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise GeneralChatFormalPrepareError(
                "SUCCESSOR_APPROVAL_REJECTED",
                str(exc),
            ) from exc

    def inspect_streaming_approval_terminal_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        expected_job_id: str,
        decision_request_event_id: str,
    ) -> dict[str, Any]:
        """Read exact approval-terminal state without grant/claim/provider execution."""
        try:
            context = self._controlled_reopen_context_v1(
                project_id=project_id,
                chat_id=chat_id,
                decision_request_event_id=decision_request_event_id,
                expected_job_id=expected_job_id,
            )
            request_source = context["request_source"]
            try:
                terminal = self.human_decision.load_exact_terminal_source(
                    decision_request_event_id
                )
            except HumanDecisionAuthorityError as exc:
                if str(exc) == "terminal source absent":
                    return {
                        "status": "AWAITING_EXPLICIT_HUMAN_APPROVAL",
                        "approval_terminal_current": False,
                        "job_id": expected_job_id,
                        "decision_request_event_id": decision_request_event_id,
                        "terminal_decision_code": None,
                        "network_called": False,
                        "model_called": False,
                        "secret_read": False,
                        "grant_created": False,
                        "attempt_claim_created": False,
                    }
                raise
            exact_approved = bool(
                terminal.get("terminal_decision_code") == "APPROVED"
                and terminal.get("decision_request_event_id") == decision_request_event_id
                and terminal.get("decision_request_identity_sha256")
                == request_source.get("decision_request_identity_sha256")
            )
            terminal_code = terminal.get("terminal_decision_code")
            if not isinstance(terminal_code, str):
                terminal_code = "UNKNOWN"
            return {
                "status": "APPROVED_EXACT_TERMINAL" if exact_approved else "TERMINAL_NOT_APPROVED",
                "approval_terminal_current": exact_approved,
                "job_id": expected_job_id,
                "decision_request_event_id": decision_request_event_id,
                "terminal_decision_code": terminal_code,
                "network_called": False,
                "model_called": False,
                "secret_read": False,
                "grant_created": False,
                "attempt_claim_created": False,
            }
        except GeneralChatFormalPrepareError:
            raise
        except HumanDecisionAuthorityError as exc:
            raise GeneralChatFormalPrepareError(
                "STREAMING_APPROVAL_STATUS_UNAVAILABLE",
                "exact HumanDecision terminal could not be read",
            ) from exc

    def execute_approved_streaming_attempt_v1(
        self,
        *,
        project_id: str,
        chat_id: str,
        expected_job_id: str,
        decision_request_event_id: str,
        emit_visible_delta: Callable[[str], None],
        stop_control: Any | None = None,
        web_current_context_guard: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Consume one already-approved P1-S2 streaming attempt through existing Runtime owners.

        Provisional deltas are presentation-only callbacks.  This method creates no new
        approval/permission authority and delegates final attempt/result persistence to the
        existing ``FormalModelJobLedger`` + ``execute_one_formal_model_attempt`` path.
        """
        if not callable(emit_visible_delta):
            raise GeneralChatFormalPrepareError(
                "STREAMING_INPUT_INVALID",
                "emit_visible_delta must be callable",
                status_code=400,
            )
        if stop_control is not None:
            from universal_runtime.core.formal_model_live_composition import P1S3StopControl
            if not isinstance(stop_control, P1S3StopControl):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_STOP_CONTROL_INVALID",
                    "exact P1-S3 StopControl is required",
                    status_code=400,
                )
            if stop_control.key != (project_id, chat_id, expected_job_id, decision_request_event_id):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_STOP_CONTROL_STALE",
                    "StopControl tuple differs from the exact streaming execution",
                )

        context = self._controlled_reopen_context_v1(
            project_id=project_id,
            chat_id=chat_id,
            decision_request_event_id=decision_request_event_id,
            expected_job_id=expected_job_id,
        )
        request_source = context["request_source"]
        v3 = context["v3"]
        frozen = context["frozen_manifest"]
        snapshot = context["predecessor_snapshot"]
        job_bundle_record = context["job_bundle_record"]
        job_bundle = context["job_bundle"]

        terminal = self.human_decision.load_exact_terminal_source(decision_request_event_id)
        if (
            terminal.get("terminal_decision_code") != "APPROVED"
            or terminal.get("decision_request_event_id") != decision_request_event_id
            or terminal.get("decision_request_identity_sha256")
            != request_source.get("decision_request_identity_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_APPROVAL_REQUIRED",
                "exact HumanDecision terminal is not APPROVED for this DRE",
            )

        approval_binding = R009OpaqueArtifactBinding(
            terminal["approval_decision_event_artifact_identity_sha256"],
            terminal["approval_decision_event_artifact_revision"],
            terminal["approval_decision_event_artifact_sha256"],
        )
        approval = self._load_exact_json_binding_v1(
            binding=approval_binding,
            label="approval decision event",
        )
        acceptance_binding = R009OpaqueArtifactBinding(
            terminal["approval_acceptance_artifact_identity_sha256"],
            terminal["approval_acceptance_artifact_revision"],
            terminal["approval_acceptance_artifact_sha256"],
        )
        acceptance = self._load_exact_json_binding_v1(
            binding=acceptance_binding,
            label="approval acceptance",
        )
        request_content_binding = R009OpaqueArtifactBinding(
            v3["decision_request_content_artifact_identity_sha256"],
            v3["decision_request_content_artifact_revision"],
            v3["decision_request_content_artifact_sha256"],
        )
        request_content = self._load_exact_json_binding_v1(
            binding=request_content_binding,
            label="decision request content",
        )
        if (
            approval.get("decision_code") != "APPROVED"
            or acceptance.get("decision_code") != "APPROVED"
            or approval.get("approval_decision_event_id") != terminal.get("approval_decision_event_id")
            or acceptance.get("approval_decision_event_id") != terminal.get("approval_decision_event_id")
            or acceptance.get("approval_decision_event_binding_sha256") != approval_binding.artifact_sha256
            or request_content.get("requested_decision_code") != "APPROVE_ONE_LIVE_ATTEMPT"
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_APPROVAL_CURRENTNESS",
                "approval/request semantic tuple is stale or mismatched",
            )
        approval_budget = {key: acceptance.get(key) for key in FIRST_SLICE_BUDGET}
        if approval_budget != FIRST_SLICE_BUDGET:
            raise GeneralChatFormalPrepareError(
                "STREAMING_APPROVAL_BUDGET",
                "streaming requires the unchanged one-attempt/no-retry/no-fallback budget",
            )
        for key, expected in FIRST_SLICE_BUDGET.items():
            if approval.get(key) != expected or request_content.get(key) != expected:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_APPROVAL_BUDGET",
                    f"approval/request budget mismatch at {key}",
                )
        authority_budget = snapshot.get("execution_budget")
        if authority_budget != FIRST_SLICE_BUDGET:
            raise GeneralChatFormalPrepareError(
                "STREAMING_AUTHORITY_BUDGET",
                "active snapshot execution budget differs from the P1-S2 ceiling",
            )

        predecessor_contract = context["predecessor_runtime_contract"]
        adoption_sha = _require_sha(
            predecessor_contract.get("model_catalog_adoption_record_sha256"),
            "model_catalog_adoption_record_sha256",
        )
        pack_action_sha = _require_sha(
            predecessor_contract.get("pack_action_sha256"),
            "pack_action_sha256",
        )
        current_contract = self._runtime_contract_manifest(
            adoption_record_sha256=adoption_sha,
            pack_action_sha256=pack_action_sha,
            streaming=True,
        )
        current_contract_sha = _sha(current_contract)
        if (
            current_contract_sha != frozen.get("runtime_contract_manifest_sha256")
            or current_contract_sha != snapshot.get("runtime_contract_pin_sha256")
            or predecessor_contract.get("provider_rules", {}).get("stream") is not True
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_RUNTIME_CURRENTNESS",
                "P1-S2 Runtime contract is not exact-current for this approved Job",
            )

        mr = frozen.get("model_resolution")
        pc = frozen.get("provider_execution_config")
        if not isinstance(mr, dict) or not isinstance(pc, dict):
            raise GeneralChatFormalPrepareError(
                "STREAMING_MODEL_BINDING",
                "frozen model/provider binding is missing",
            )
        resolution = ResolvedModelExecution(
            model_policy_revision=mr["model_policy_revision"],
            model_decision_sha256=mr["model_decision_sha256"],
            selected_profile=mr["selected_profile"],
            catalog_revision=mr["catalog_revision"],
            catalog_sha256=mr["catalog_sha256"],
            update_mode=ModelUpdateMode(mr["update_mode"]),
            model_entry_id=mr["model_entry_id"],
            provider=mr["provider"],
            model=mr["model"],
            resolution_reason=mr["resolution_reason"],
            resolution_sha256=mr["resolution_sha256"],
        )
        if resolution.to_dict() != mr:
            raise GeneralChatFormalPrepareError(
                "STREAMING_MODEL_BINDING",
                "ResolvedModelExecution does not reconstruct exactly",
            )
        provider_config = ProviderExecutionConfig.create(
            revision=pc["revision"],
            provider=pc["provider"],
            resolved_model_entry_id=pc["resolved_model_entry_id"],
            model_resolution_sha256=pc["model_resolution_sha256"],
            endpoint_origin=pc["endpoint_origin"],
            api_route=pc["api_route"],
            adapter_relative_path=pc["adapter_relative_path"],
            adapter_sha256=pc["adapter_sha256"],
            transport_client_class=pc["transport_client_class"],
            transport_package_versions=pc["transport_package_versions"],
            credential_ref_id=pc["credential_ref_id"],
            credential_ref_class=pc["credential_ref_class"],
            stream=pc["stream"],
            proxy_mode=pc["proxy_mode"],
            proxy_config_sha256=pc["proxy_config_sha256"],
        )
        if (
            provider_config.payload() != pc
            or dict(provider_config.transport_package_versions)
            != {"httpx": P1_S3_HTTPX_VERSION, "openai": P1_S3_OPENAI_VERSION}
            or job_bundle.get("model_resolution_sha256") != resolution.resolution_sha256
            or job_bundle.get("provider_execution_config_sha256") != provider_config.semantic_sha256
            or frozen.get("provider_execution_config_sha256") != provider_config.semantic_sha256
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_MODEL_BINDING",
                "exact P1-S2 model/provider config binding differs",
            )

        promoted_pack = self.pack_registry.resolve_promoted_pack(PACK_ID, PACK_VERSION)
        current_pack_pin = JobPackPin.from_resolved_pack(expected_job_id, promoted_pack).to_dict()
        if current_pack_pin != frozen.get("pack_pin"):
            raise GeneralChatFormalPrepareError(
                "STREAMING_PACK_CURRENTNESS",
                "current promoted Pack differs from frozen Job pin",
            )
        required_inputs = frozen.get("load_plan", {}).get("required_inputs")
        if not isinstance(required_inputs, list) or len(required_inputs) != 1:
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROMPT_CURRENTNESS",
                "exact one-system-prompt LoadPlan required",
            )
        prompt_input = required_inputs[0]
        content_root = Path(promoted_pack.content_root or "")
        prompt_path = content_root / prompt_input.get("reference", "")
        if (
            prompt_input.get("role") != "system_prompt"
            or not prompt_path.is_file()
            or _file_sha(prompt_path) != prompt_input.get("expected_sha256")
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROMPT_CURRENTNESS",
                "system prompt differs from frozen LoadPlan",
            )
        system_prompt = prompt_path.read_text(encoding="utf-8")

        project_instructions_input = frozen.get("input_set", {}).get("project_instructions")
        if not isinstance(project_instructions_input, dict):
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_INSTRUCTIONS_CURRENTNESS",
                "frozen Project Instructions binding is missing",
            )
        frozen_project_instruction_binding = project_instructions_input.get(
            "project_instruction_binding"
        )
        frozen_project_instructions_sha256 = project_instructions_input.get(
            "project_instructions_sha256"
        )
        if (
            not isinstance(frozen_project_instruction_binding, dict)
            or not isinstance(frozen_project_instructions_sha256, str)
            or _SHA_RE.fullmatch(frozen_project_instructions_sha256) is None
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_INSTRUCTIONS_CURRENTNESS",
                "frozen Project Instructions identity is invalid",
            )
        try:
            current_project_instruction_facts = WebContinuityService(
                self.store
            ).read_project_instructions_current(
                project_id=frozen.get("input_set", {}).get("project_id"),
            )
        except WebContinuityError as exc:
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_INSTRUCTIONS_CURRENTNESS",
                f"{exc.code}: {exc.message}",
                status_code=exc.status_code,
            ) from exc
        if (
            current_project_instruction_facts.get("project_instruction_binding")
            != frozen_project_instruction_binding
            or frozen_project_instructions_sha256
            != current_project_instruction_facts.get("project_instruction_binding", {}).get("sha256")
            or job_bundle.get("project_instructions_sha256")
            != frozen_project_instructions_sha256
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_INSTRUCTIONS_CURRENTNESS",
                "Project Instructions changed after formal Job prepare",
            )
        system_prompt = _compose_system_prompt_with_project_instructions(
            system_prompt=system_prompt,
            project_instructions=current_project_instruction_facts["project_instructions"],
        )

        library_source = frozen.get("input_set", {}).get("library_source_context")
        source_text: str | None = None
        user_request: str | None = None
        if isinstance(library_source, dict):
            source_context_binding = self._r009_binding_from_dict_v1(
                library_source.get("source_context_artifact_binding"),
                "source context",
            )
            source_context = self._load_exact_json_binding_v1(
                binding=source_context_binding,
                label="source context",
            )
            if (
                source_context_binding.artifact_sha256 != library_source.get("source_context_sha256")
                or source_context.get("source_ref_id") != library_source.get("source_ref_id")
            ):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_SOURCE_CURRENTNESS",
                    "source context differs from frozen input",
                )
            source_text = source_context.get("decoded_text")
            user_request = source_context.get("question")
            if (
                not isinstance(source_text, str)
                or not source_text
                or not isinstance(user_request, str)
                or not user_request
            ):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_SOURCE_CURRENTNESS",
                    "exact source/question text is missing",
                )
        elif library_source is not None:
            raise GeneralChatFormalPrepareError(
                "STREAMING_SOURCE_CURRENTNESS",
                "library source context must be an object when present",
            )

        memory_guard_input = frozen.get("input_set", {}).get("project_memory_state_guard")
        project_memory_state_guard = None
        project_memory_state_guard_binding = None
        if isinstance(memory_guard_input, dict):
            project_memory_state_guard_binding = self._r009_binding_from_dict_v1(
                memory_guard_input.get("project_memory_state_guard_artifact_binding"),
                "project memory state guard",
            )
            project_memory_state_guard = self._load_exact_json_binding_v1(
                binding=project_memory_state_guard_binding,
                label="project memory state guard",
            )
            try:
                ProjectMemoryService(self.store).validate_state_guard_current(
                    project_id=frozen.get("input_set", {}).get("project_id"),
                    project_memory_state_guard=project_memory_state_guard,
                    project_memory_state_guard_sha256=memory_guard_input.get("project_memory_state_guard_sha256"),
                )
            except ProjectMemoryError as exc:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_PROJECT_MEMORY_CURRENTNESS",
                    f"{exc.code}: {exc.message}",
                ) from exc
        elif memory_guard_input is not None:
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_MEMORY_CURRENTNESS",
                "project memory state guard input must be an object when present",
            )

        memory_input = frozen.get("input_set", {}).get("project_memory_context")
        project_memory_context = None
        project_memory_context_binding = None
        if isinstance(memory_input, dict):
            project_memory_context_binding = self._r009_binding_from_dict_v1(
                memory_input.get("project_memory_context_artifact_binding"),
                "project memory context",
            )
            project_memory_context = self._load_exact_json_binding_v1(
                binding=project_memory_context_binding,
                label="project memory context",
            )
            try:
                ProjectMemoryService(self.store).validate_context_current(
                    project_id=frozen.get("input_set", {}).get("project_id"),
                    project_memory_context=project_memory_context,
                    project_memory_context_sha256=memory_input.get("project_memory_context_sha256"),
                )
            except ProjectMemoryError as exc:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_PROJECT_MEMORY_CURRENTNESS",
                    f"{exc.code}: {exc.message}",
                ) from exc
        elif memory_input is not None:
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_MEMORY_CURRENTNESS",
                "project memory context input must be an object when present",
            )
        if project_memory_context is not None and project_memory_state_guard is None:
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_MEMORY_CURRENTNESS",
                "Project Memory context is missing its exact state guard",
            )
        if (
            project_memory_state_guard is not None
            and project_memory_context is None
            and project_memory_state_guard.get("active_memory_count") != 0
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_MEMORY_CURRENTNESS",
                "ACTIVE Project Memory state guard is missing its exact Memory context",
            )

        personal_input = frozen.get("input_set", {}).get("personal_context")
        personal_context = None
        if isinstance(personal_input, dict):
            if personal_input.get("authority_class") != PERSONAL_CONTEXT_AUTHORITY_CLASS:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_PERSONAL_CONTEXT_CURRENTNESS",
                    "Personal Context authority classification differs",
                )
            personal_binding = self._r009_binding_from_dict_v1(
                personal_input.get("personal_context_artifact_binding"),
                "personal context",
            )
            personal_context = self._load_exact_json_binding_v1(
                binding=personal_binding,
                label="personal context",
            )
            personal_context = validate_non_authority_personal_context_snapshot(
                personal_context=personal_context,
                personal_context_sha256=personal_input.get("personal_context_sha256"),
            )
        elif personal_input is not None:
            raise GeneralChatFormalPrepareError(
                "STREAMING_PERSONAL_CONTEXT_CURRENTNESS",
                "Personal Context input must be an object when present",
            )

        history_input = frozen.get("input_set", {}).get("project_history_context")
        project_history_context = None
        if isinstance(history_input, dict):
            history_binding = self._r009_binding_from_dict_v1(
                history_input.get("project_history_context_artifact_binding"),
                "project history context",
            )
            project_history_context = self._load_exact_json_binding_v1(
                binding=history_binding,
                label="project history context",
            )
            try:
                project_history_context = WebContinuityService(self.store).validate_project_history_context_current(
                    project_id=frozen.get("input_set", {}).get("project_id"),
                    exclude_chat_id=frozen.get("input_set", {}).get("chat_id"),
                    project_history_context=project_history_context,
                    project_history_context_sha256=history_input.get("project_history_context_sha256"),
                )
            except WebContinuityError as exc:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_PROJECT_HISTORY_CURRENTNESS",
                    f"{exc.code}: {exc.message}",
                    status_code=exc.status_code,
                ) from exc
        elif history_input is not None:
            raise GeneralChatFormalPrepareError(
                "STREAMING_PROJECT_HISTORY_CURRENTNESS",
                "Project History context input must be an object when present",
            )

        profile_path = self.runtime_home / "config/model_profiles.yaml"
        try:
            import yaml
            profile_doc = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise GeneralChatFormalPrepareError(
                "STREAMING_MODEL_PROFILE_CURRENTNESS",
                "model profile config is unavailable",
            ) from exc
        profile = profile_doc.get("profiles", {}).get(LOGICAL_PROFILE) if isinstance(profile_doc, dict) else None
        if (
            not isinstance(profile, dict)
            or profile.get("provider") != resolution.provider
            or profile.get("thinking") not in ("enabled", "disabled")
            or profile.get("reasoning_effort") not in ("low", "high", "max")
            or isinstance(profile.get("max_tokens"), bool)
            or not isinstance(profile.get("max_tokens"), int)
            or profile.get("max_tokens") < 1
        ):
            raise GeneralChatFormalPrepareError(
                "STREAMING_MODEL_PROFILE_CURRENTNESS",
                "selected model profile is invalid or stale",
            )

        active_input = frozen.get("input_set", {}).get("active_context_snapshot")
        if isinstance(active_input, dict):
            active_binding = self._r009_binding_from_dict_v1(
                active_input.get("active_context_artifact_binding"),
                "active context",
            )
            active_snapshot = self._load_exact_json_binding_v1(
                binding=active_binding,
                label="active context",
            )
            try:
                active_snapshot_sha = validate_active_context_snapshot(active_snapshot)
            except WebConversationGraphError as exc:
                raise GeneralChatFormalPrepareError("STREAMING_ACTIVE_CONTEXT", f"{exc.code}: {exc.message}") from exc
            if (
                active_snapshot_sha != active_input.get("active_context_snapshot_sha256")
                or active_snapshot.get("active_ancestry_sha256") != active_input.get("active_ancestry_sha256")
                or active_snapshot.get("chat_revision") != active_input.get("chat_revision")
                or active_snapshot.get("head_event_id") != active_input.get("head_event_id")
            ):
                raise GeneralChatFormalPrepareError("STREAMING_ACTIVE_CONTEXT", "frozen active context binding differs")
            try:
                validate_current_context_guard(
                    active_context_snapshot=active_snapshot,
                    guard=web_current_context_guard,
                )
            except WebConversationGraphError as exc:
                code = "STREAMING_WEB_CONTEXT_GUARD_REQUIRED" if exc.code == "ACTIVE_CONTEXT_GUARD_REQUIRED" else "STREAMING_WEB_CONTEXT_STALE"
                raise GeneralChatFormalPrepareError(code, exc.message) from exc

            if isinstance(library_source, dict):
                messages = _source_provider_messages_from_active_snapshot_v1(
                    system_prompt=system_prompt,
                    active_context_snapshot=active_snapshot,
                    source_text=source_text,
                    user_request=user_request,
                    project_memory_context=project_memory_context,
                    personal_context=personal_context,
                    project_history_context=project_history_context,
                )
            else:
                messages = _plain_provider_messages_from_active_snapshot_v1(
                    system_prompt=system_prompt,
                    active_context_snapshot=active_snapshot,
                    project_memory_context=project_memory_context,
                    personal_context=personal_context,
                    project_history_context=project_history_context,
                )
        elif isinstance(library_source, dict):
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"source_text": source_text, "user_request": user_request},
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ]
        else:
            raise GeneralChatFormalPrepareError(
                "STREAMING_ACTIVE_CONTEXT_REQUIRED",
                "no-Source General Chat requires exact frozen active conversation context",
            )

        authority_binding = {
            "job_authority_event_id": v3["job_authority_event_id"],
            "job_execution_authority_snapshot_id": v3["job_execution_authority_snapshot_id"],
            "job_execution_authority_snapshot_sha256": v3["job_execution_authority_snapshot_sha256"],
            "job_execution_authority_snapshot_artifact_identity_sha256": v3[
                "job_execution_authority_snapshot_artifact_identity_sha256"
            ],
            "job_execution_authority_snapshot_artifact_revision": v3[
                "job_execution_authority_snapshot_artifact_revision"
            ],
            "job_execution_authority_snapshot_artifact_sha256": v3[
                "job_execution_authority_snapshot_artifact_sha256"
            ],
            "job_execution_snapshot_registration_sha256": v3[
                "job_execution_snapshot_registration_sha256"
            ],
            "job_execution_snapshot_registration_artifact_identity_sha256": v3[
                "job_execution_snapshot_registration_artifact_identity_sha256"
            ],
            "job_execution_snapshot_registration_artifact_revision": v3[
                "job_execution_snapshot_registration_artifact_revision"
            ],
            "job_execution_snapshot_registration_artifact_sha256": v3[
                "job_execution_snapshot_registration_artifact_sha256"
            ],
            "decision_request_event_id": decision_request_event_id,
            "decision_request_identity_sha256": request_source["decision_request_identity_sha256"],
            "decision_scope_sha256": v3["decision_scope_sha256"],
            "approval_decision_event_id": terminal["approval_decision_event_id"],
            "approval_decision_event_binding_sha256": approval_binding.artifact_sha256,
            "approval_acceptance_semantic_sha256": acceptance_binding.artifact_sha256,
            "approval_acceptance_artifact_identity_sha256": acceptance_binding.artifact_identity_sha256,
            "approval_acceptance_artifact_revision": acceptance_binding.artifact_revision,
            "approval_acceptance_artifact_sha256": acceptance_binding.artifact_sha256,
        }
        import universal_runtime.core.formal_model_job as formal_job_module
        required_authority_fields = set(getattr(formal_job_module, "_REQUIRED_AUTHORITY_FIELDS", ()))
        if set(authority_binding) != required_authority_fields:
            raise GeneralChatFormalPrepareError(
                "STREAMING_AUTHORITY_CONTRACT",
                "formal Job authority binding field contract changed",
            )

        job_bundle_sha256 = job_bundle_record.get("job_bundle_sha256")
        if not isinstance(job_bundle_sha256, str) or _SHA_RE.fullmatch(job_bundle_sha256) is None:
            raise GeneralChatFormalPrepareError(
                "STREAMING_JOB_CURRENTNESS",
                "exact JobBundle SHA is invalid",
            )
        job_bundle_binding = frozen.get("job_bundle_binding")
        intake_binding = frozen.get("web_formal_job_intake_binding")
        if not isinstance(job_bundle_binding, dict) or not isinstance(intake_binding, dict):
            raise GeneralChatFormalPrepareError(
                "STREAMING_JOB_CURRENTNESS",
                "exact JobBundle/intake bindings are missing",
            )

        def assert_job_authority_current() -> None:
            active2, registration2, registration_binding2 = (
                self.job_authority.load_exact_active_registration_source_by_jae_v1(
                    job_authority_event_id=v3["job_authority_event_id"]
                )
            )
            if (
                active2 != context["active_source"]
                or registration2 != context["predecessor_registration"]
                or registration_binding2 != context["predecessor_registration_binding"]
            ):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_JOB_AUTHORITY_STALE",
                    "active execution authority changed after approval",
                )

        def assert_human_approval_current() -> None:
            if self.human_decision.load_exact_terminal_source(decision_request_event_id) != terminal:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_HUMAN_APPROVAL_STALE",
                    "HumanDecision terminal changed after approval",
                )

        def assert_provider_config_current(config: ProviderExecutionConfig) -> None:
            if config.semantic_sha256 != provider_config.semantic_sha256:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_PROVIDER_CONFIG_STALE",
                    "provider config object changed before provider request",
                )
            try:
                current_versions = {
                    "httpx": importlib.metadata.version("httpx"),
                    "openai": importlib.metadata.version("openai"),
                }
            except importlib.metadata.PackageNotFoundError as exc:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_SDK_CURRENTNESS",
                    "installed streaming SDK dependency is unavailable",
                ) from exc
            if (
                current_versions != dict(config.transport_package_versions)
                or current_versions != {"httpx": P1_S3_HTTPX_VERSION, "openai": P1_S3_OPENAI_VERSION}
            ):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_SDK_CURRENTNESS",
                    "installed openai/httpx versions changed after Job freeze",
                )
            current2 = self._runtime_contract_manifest(
                adoption_record_sha256=adoption_sha,
                pack_action_sha256=pack_action_sha,
                streaming=True,
            )
            if _sha(current2) != current_contract_sha:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_RUNTIME_CURRENTNESS",
                    "Runtime streaming contract changed before provider request",
                )
            if _file_sha(prompt_path) != prompt_input.get("expected_sha256"):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_PROMPT_CURRENTNESS",
                    "system prompt changed before provider request",
                )
            try:
                project_instructions_current2 = WebContinuityService(
                    self.store
                ).read_project_instructions_current(
                    project_id=frozen.get("input_set", {}).get("project_id"),
                )
            except WebContinuityError as exc:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_PROJECT_INSTRUCTIONS_CURRENTNESS",
                    f"{exc.code}: {exc.message}",
                    status_code=exc.status_code,
                ) from exc
            if (
                project_instructions_current2.get("project_instruction_binding")
                != frozen_project_instruction_binding
                or project_instructions_current2.get("project_instructions")
                != current_project_instruction_facts.get("project_instructions")
            ):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_PROJECT_INSTRUCTIONS_CURRENTNESS",
                    "Project Instructions changed before provider request",
                )
            if isinstance(library_source, dict):
                source2 = self._load_exact_json_binding_v1(
                    binding=source_context_binding,
                    label="source context",
                )
                if source2 != source_context:
                    raise GeneralChatFormalPrepareError(
                        "STREAMING_SOURCE_CURRENTNESS",
                        "source context changed before provider request",
                    )
            if project_memory_state_guard is not None:
                try:
                    ProjectMemoryService(self.store).validate_state_guard_current(
                        project_id=frozen.get("input_set", {}).get("project_id"),
                        project_memory_state_guard=project_memory_state_guard,
                        project_memory_state_guard_sha256=memory_guard_input.get("project_memory_state_guard_sha256"),
                    )
                except ProjectMemoryError as exc:
                    raise GeneralChatFormalPrepareError(
                        "STREAMING_PROJECT_MEMORY_CURRENTNESS",
                        f"{exc.code}: {exc.message}",
                    ) from exc
            if project_memory_context is not None:
                try:
                    ProjectMemoryService(self.store).validate_context_current(
                        project_id=frozen.get("input_set", {}).get("project_id"),
                        project_memory_context=project_memory_context,
                        project_memory_context_sha256=memory_input.get("project_memory_context_sha256"),
                    )
                except ProjectMemoryError as exc:
                    raise GeneralChatFormalPrepareError(
                        "STREAMING_PROJECT_MEMORY_CURRENTNESS",
                        f"{exc.code}: {exc.message}",
                    ) from exc
            if project_history_context is not None:
                try:
                    WebContinuityService(self.store).validate_project_history_context_current(
                        project_id=frozen.get("input_set", {}).get("project_id"),
                        exclude_chat_id=frozen.get("input_set", {}).get("chat_id"),
                        project_history_context=project_history_context,
                        project_history_context_sha256=history_input.get("project_history_context_sha256"),
                    )
                except WebContinuityError as exc:
                    raise GeneralChatFormalPrepareError(
                        "STREAMING_PROJECT_HISTORY_CURRENTNESS",
                        f"{exc.code}: {exc.message}",
                        status_code=exc.status_code,
                    ) from exc


        def resolve_credential(ref_id: str, ref_class: str) -> str:
            if (
                ref_id != provider_config.credential_ref_id
                or ref_class != provider_config.credential_ref_class
                or ref_class != "ENVIRONMENT_VARIABLE"
            ):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_CREDENTIAL_SCOPE",
                    "credential reference differs from the exact Job plan",
                )
            # Reuse the existing Runtime config bootstrap at the exact credential boundary.
            # Importing ``universal_runtime.config`` loads the Runtime-local .env through
            # the existing config owner; the secret value is still resolved only by ref_id
            # and is never copied into Job/Artifact data.
            from universal_runtime import config as _runtime_config
            _ = _runtime_config.PROJECT_ROOT
            import os
            value = os.getenv(ref_id)
            if not isinstance(value, str) or not value:
                raise GeneralChatFormalPrepareError(
                    "STREAMING_CREDENTIAL_UNAVAILABLE",
                    "approved credential reference is unavailable",
                )
            return value

        from universal_runtime.core.formal_model_live_composition import execute_one_formal_model_attempt
        from universal_runtime.models.deepseek_streaming import (
            issue_formal_deepseek_chat_completion_streaming,
        )

        def issue_provider_request(
            config: ProviderExecutionConfig,
            resolved: ResolvedModelExecution,
            credential: str,
        ):
            return issue_formal_deepseek_chat_completion_streaming(
                config,
                resolved,
                credential,
                messages=messages,
                max_tokens=profile["max_tokens"],
                reasoning_effort=profile["reasoning_effort"],
                thinking=profile["thinking"],
                emit_visible_delta=emit_visible_delta,
                explicit_loopback_proxy_url=None,
                timeout_seconds=180.0,
                stop_control=stop_control,
                execution_instance_id=(
                    stop_control.execution_instance_id if stop_control is not None else None
                ),
            )

        def prepare_execution_bindings():
            grant_record, grant_binding = self.ledger.persist_model_execution_grant(
                job_id=expected_job_id,
                job_bundle_sha256=job_bundle_sha256,
                job_bundle_binding=job_bundle_binding,
                authority_binding=authority_binding,
                authority_budget=authority_budget,
                approval_budget=approval_budget,
                model_resolution_sha256=resolution.resolution_sha256,
                provider_execution_config_sha256=provider_config.semantic_sha256,
            )
            _ = grant_record
            execution_record, execution_binding = self.ledger.persist_execution_binding(
                job_id=expected_job_id,
                job_bundle_sha256=job_bundle_sha256,
                intake_binding=intake_binding,
                grant_binding=grant_binding,
                provider_execution_config_sha256=provider_config.semantic_sha256,
                authority_binding=authority_binding,
                model_resolution_sha256=resolution.resolution_sha256,
            )
            _ = execution_record
            return grant_binding, execution_binding

        if stop_control is None:
            grant_binding, execution_binding = prepare_execution_bindings()
            prepare_bindings_for_attempt = None
        else:
            grant_binding = None
            execution_binding = None
            prepare_bindings_for_attempt = prepare_execution_bindings

        live = execute_one_formal_model_attempt(
            self.ledger,
            job_id=expected_job_id,
            job_bundle_sha256=job_bundle_sha256,
            execution_binding=execution_binding,
            grant_binding=grant_binding,
            authority_binding=authority_binding,
            model_resolution=resolution,
            provider_execution_config=provider_config,
            assert_job_authority_current=assert_job_authority_current,
            assert_human_approval_current=assert_human_approval_current,
            assert_provider_config_current=assert_provider_config_current,
            resolve_credential=resolve_credential,
            issue_provider_request=issue_provider_request,
            stop_control=stop_control,
            prepare_execution_bindings=prepare_bindings_for_attempt,
        )
        if live.get("status") == "ATTEMPT_CLAIMED_CANCELLED_BY_USER":
            cancellation = live.get("cancellation_outcome")
            cancellation_binding = live.get("cancellation_outcome_binding")
            if not isinstance(cancellation, dict) or not isinstance(cancellation_binding, dict):
                raise GeneralChatFormalPrepareError(
                    "STREAMING_CANCELLATION_RECEIPT_MISSING",
                    "confirmed STOP lacks exact Runtime cancellation receipt",
                )
            return {
                "status": "FORMAL_MODEL_STREAM_CANCELLED",
                "job_id": expected_job_id,
                "decision_request_event_id": decision_request_event_id,
                "provider_execution_config_sha256": provider_config.semantic_sha256,
                "cancellation_outcome": cancellation,
                "cancellation_outcome_binding": cancellation_binding,
                "provisional_stream_authority": "NONE_PRESENTATION_ONLY",
                "provisional_stream_persisted": False,
                "retry_observed": False,
                "fallback_observed": False,
            }
        if live.get("status") == "STOPPED_BEFORE_CLAIM_NO_ATTEMPT":
            raise GeneralChatFormalPrepareError(
                "STOPPED_BEFORE_CLAIM_NO_ATTEMPT",
                "STOP won before a successful claim; no Grant/Claim/provider request was created",
            )
        if live.get("status") != "FORMAL_MODEL_RESULT_COMMITTED":
            raise GeneralChatFormalPrepareError(
                "STREAMING_ATTEMPT_NOT_NEW",
                "approved attempt slot is already consumed or cannot issue another provider request",
            )
        formal_result = live.get("formal_result_commit")
        formal_result_binding = live.get("formal_result_commit_binding")
        if not isinstance(formal_result, dict) or not isinstance(formal_result_binding, dict):
            raise GeneralChatFormalPrepareError(
                "STREAMING_FORMAL_RESULT_MISSING",
                "Runtime formal result commit is missing after provider completion",
            )
        assistant_text = self.ledger.load_assistant_output_text(formal_result)
        return {
            "status": "FORMAL_MODEL_STREAM_RESULT_COMMITTED",
            "job_id": expected_job_id,
            "decision_request_event_id": decision_request_event_id,
            "provider_execution_config_sha256": provider_config.semantic_sha256,
            "web_formal_job_intake_binding": intake_binding,
            "formal_result_commit_binding": formal_result_binding,
            "assistant_text": assistant_text,
            "assistant_content_sha256": _sha_bytes(assistant_text.encode("utf-8")),
            "provisional_stream_authority": "NONE_PRESENTATION_ONLY",
            "provisional_stream_persisted": False,
            "retry_observed": False,
            "fallback_observed": False,
        }

    def finalize_approval_request(
        self,
        *,
        prepared: GeneralChatPhaseAPreparedJob,
        intake_binding_record: dict[str, Any],
        intake_binding: dict[str, Any],
    ) -> dict[str, Any]:
        if intake_binding_record.get("job_id") != prepared.job_id:
            raise GeneralChatFormalPrepareError("INTAKE_JOB_MISMATCH", "intake belongs to another Job")
        if intake_binding_record.get("job_bundle_sha256") != prepared.job_bundle_record.get("job_bundle_sha256"):
            raise GeneralChatFormalPrepareError("INTAKE_JOB_BUNDLE_MISMATCH", "intake differs from exact JobBundle")
        intake_sha = intake_binding.get("artifact_sha256")
        if not isinstance(intake_sha, str) or _SHA_RE.fullmatch(intake_sha) is None:
            raise GeneralChatFormalPrepareError("INVALID_INTAKE_BINDING", "exact intake binding required")

        input_set_binding = _persist_exact_json(
            self.store,
            kind="JOB_LINEAGE_INPUT_SET",
            job_id=prepared.job_id,
            record=prepared.input_set,
        )
        issuance_source = self.job_authority.issue_or_replay_one_initial_job_authority_event_v1(
            job_bundle_binding=R009OpaqueArtifactBinding(
                prepared.job_bundle_binding["artifact_identity_sha256"],
                prepared.job_bundle_binding["artifact_revision"],
                prepared.job_bundle_binding["artifact_sha256"],
            ),
            web_formal_job_intake_binding=R009OpaqueArtifactBinding(
                intake_binding["artifact_identity_sha256"],
                intake_binding["artifact_revision"],
                intake_binding["artifact_sha256"],
            ),
            input_set_binding=R009OpaqueArtifactBinding(
                input_set_binding["artifact_identity_sha256"],
                input_set_binding["artifact_revision"],
                input_set_binding["artifact_sha256"],
            ),
        )
        if issuance_source.get("job_id") != prepared.job_id:
            raise GeneralChatFormalPrepareError("JOB_AUTHORITY_CURRENTNESS", "initial JAE source belongs to another Job")
        jae = issuance_source["job_authority_event_id"]
        lineage_sha = issuance_source["job_lineage_identity_sha256"]
        authority_binding = {
            "schema": "RUNTIME_JOB_APPROVAL_AUTHORITY_BINDING_V1",
            "job_authority_event_id": jae,
            "job_lineage_identity_sha256": lineage_sha,
        }
        authority_binding_sha = _sha(authority_binding)

        frozen_manifest = {
            "schema": "RUNTIME_S1_GENERAL_CHAT_FROZEN_BINDING_MANIFEST_V1",
            "job_id": prepared.job_id,
            "job_bundle_binding": prepared.job_bundle_binding,
            "job_bundle_sha256": prepared.job_bundle_record["job_bundle_sha256"],
            "web_formal_job_intake_binding": intake_binding,
            "web_formal_job_intake_binding_sha256": intake_sha,
            "runtime_contract_manifest_sha256": prepared.runtime_contract_manifest_sha256,
            "pack_pin": prepared.pack_pin,
            "permission_plan": prepared.permission_plan,
            "load_plan": prepared.load_plan,
            "model_decision": prepared.model_decision,
            "model_resolution": prepared.model_resolution,
            "provider_execution_config": prepared.provider_execution_config,
            "provider_execution_config_sha256": prepared.provider_execution_config_sha256,
            "input_set": prepared.input_set,
            "network_permission_plan": prepared.network_permission_plan,
            "authorized_request_plan": prepared.authorized_request_plan,
            "secret_access_plan": prepared.secret_access_plan,
            "model_profile_binding": prepared.model_profile_binding,
            "persistence_plan": prepared.persistence_plan,
            "phase_a_execution_ceiling": {
                "credential_read": False,
                "network": False,
                "model_call": False,
                "grant_creation": False,
                "attempt_claim": False,
            },
        }
        frozen_binding = _persist_exact_json(
            self.store,
            kind="FROZEN_BINDING_MANIFEST",
            job_id=prepared.job_id,
            record=frozen_manifest,
        )

        snapshot = {
            "schema": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_V1",
            "snapshot_revision": 1,
            "job_authority_event_id": jae,
            "job_lineage_identity_sha256": lineage_sha,
            "job_authority_binding_sha256": authority_binding_sha,
            "runtime_contract_pin_sha256": prepared.runtime_contract_manifest_sha256,
            "runtime_execution_identity_sha256": prepared.runtime_execution_identity_sha256,
            "pack_pin_sha256": _sha(prepared.pack_pin),
            "workflow_pin_sha256": prepared.workflow_pin_sha256,
            "rule_pin_sha256": prepared.rule_pin_sha256,
            "adapter_executor_pin_set_sha256": prepared.adapter_executor_pin_set_sha256,
            "input_set_sha256": issuance_source["input_set_sha256"],
            "load_plan_sha256": prepared.job_bundle_record["job_bundle"]["load_plan_sha256"],
            "filesystem_permission_plan_sha256": prepared.job_bundle_record["job_bundle"][
                "permission_plan_sha256"
            ],
            "network_permission_plan_sha256": _sha(prepared.network_permission_plan),
            "authorized_request_plan_sha256": _sha(prepared.authorized_request_plan),
            "secret_access_plan_sha256": _sha(prepared.secret_access_plan),
            "model_policy_binding_sha256": prepared.model_decision["decision_sha256"],
            "model_profile_binding_sha256": _sha(prepared.model_profile_binding),
            "resolved_model_binding_sha256": prepared.model_resolution["resolution_sha256"],
            "output_contract_sha256": prepared.output_contract_sha256,
            "persistence_plan_sha256": _sha(prepared.persistence_plan),
            "frozen_binding_manifest_artifact_identity_sha256": frozen_binding[
                "artifact_identity_sha256"
            ],
            "frozen_binding_manifest_artifact_revision": frozen_binding["artifact_revision"],
            "frozen_binding_manifest_artifact_sha256": frozen_binding["artifact_sha256"],
            "execution_budget": dict(FIRST_SLICE_BUDGET),
        }
        snapshot_binding = _persist_exact_json(
            self.store,
            kind="JOB_AUTHORITY_SNAPSHOT",
            job_id=prepared.job_id,
            record=snapshot,
        )
        jxs = "JXS_" + _sha({
            "namespace": "RUNTIME_JOB_EXECUTION_AUTHORITY_SNAPSHOT_ID_V1",
            "job_authority_event_id": jae,
            "snapshot_content_sha256": snapshot_binding["artifact_sha256"],
        })
        registration = {
            "schema": "RUNTIME_JOB_EXECUTION_SNAPSHOT_REGISTRATION_V2",
            "registration_revision": 1,
            "job_authority_event_id": jae,
            "job_authority_binding_sha256": authority_binding_sha,
            "job_execution_authority_snapshot_id": jxs,
            "job_execution_authority_snapshot_sha256": snapshot_binding["artifact_sha256"],
            "job_execution_authority_snapshot_artifact_identity_sha256": snapshot_binding[
                "artifact_identity_sha256"
            ],
            "job_execution_authority_snapshot_artifact_revision": snapshot_binding[
                "artifact_revision"
            ],
            "job_execution_authority_snapshot_artifact_sha256": snapshot_binding["artifact_sha256"],
            "activation_basis": "INITIAL_JOB_CREATION",
            "predecessor_approval_slot_key_sha256": None,
            "predecessor_invalidation_sha256": None,
            "job_transition_intent_sha256": None,
            "state": "ACTIVE_EXECUTION_AUTHORITY_SNAPSHOT",
        }
        registration_binding_dict = _persist_exact_json(
            self.store,
            kind="JOB_AUTHORITY_REGISTRATION",
            job_id=prepared.job_id,
            record=registration,
        )

        registration_binding = R009OpaqueArtifactBinding(
            registration_binding_dict["artifact_identity_sha256"],
            registration_binding_dict["artifact_revision"],
            registration_binding_dict["artifact_sha256"],
        )
        active_source = self.job_authority.register_or_replay_one_initial_snapshot_for_issued_jae_v1(
            registration_binding=registration_binding
        )
        if (
            active_source.get("job_execution_authority_snapshot_id") != jxs
            or active_source.get("job_execution_authority_snapshot_sha256") != snapshot_binding["artifact_sha256"]
            or active_source.get("registration_sha256") != registration_binding_dict["artifact_sha256"]
        ):
            raise GeneralChatFormalPrepareError("JOB_AUTHORITY_CURRENTNESS", "active registration differs")

        request_content = {
            "schema": "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_CONTENT_SEMANTIC_V1",
            "job_authority_event_id": jae,
            "job_execution_authority_snapshot_id": jxs,
            "job_execution_authority_snapshot_sha256": snapshot_binding["artifact_sha256"],
            "requested_decision_code": "APPROVE_ONE_LIVE_ATTEMPT",
            **dict(FIRST_SLICE_BUDGET),
        }
        request_content_binding = _persist_exact_json(
            self.store,
            kind="LIVE_DECISION_REQUEST_CONTENT",
            job_id=prepared.job_id,
            record=request_content,
        )
        request_key = _sha({
            "namespace": "RUNTIME_LIVE_EXECUTION_ONE_REQUEST_PER_ACTIVE_SNAPSHOT_V1",
            "job_authority_event_id": jae,
            "job_execution_authority_snapshot_id": jxs,
            "job_execution_authority_snapshot_sha256": snapshot_binding["artifact_sha256"],
            "job_execution_snapshot_registration_sha256": registration_binding_dict["artifact_sha256"],
        })
        dre = "DRE_" + request_key
        v3 = {
            "schema": "RUNTIME_LIVE_EXECUTION_DECISION_REQUEST_BINDING_V3",
            "snapshot_decision_request_key_sha256": request_key,
            "decision_request_event_id": dre,
            "job_authority_event_id": jae,
            "job_execution_authority_snapshot_id": jxs,
            "job_execution_authority_snapshot_sha256": snapshot_binding["artifact_sha256"],
            "job_execution_authority_snapshot_artifact_identity_sha256": snapshot_binding[
                "artifact_identity_sha256"
            ],
            "job_execution_authority_snapshot_artifact_revision": snapshot_binding["artifact_revision"],
            "job_execution_authority_snapshot_artifact_sha256": snapshot_binding["artifact_sha256"],
            "job_execution_snapshot_registration_sha256": registration_binding_dict["artifact_sha256"],
            "job_execution_snapshot_registration_artifact_identity_sha256": registration_binding_dict[
                "artifact_identity_sha256"
            ],
            "job_execution_snapshot_registration_artifact_revision": registration_binding_dict[
                "artifact_revision"
            ],
            "job_execution_snapshot_registration_artifact_sha256": registration_binding_dict[
                "artifact_sha256"
            ],
            "decision_request_content_sha256": request_content_binding["artifact_sha256"],
            "decision_request_content_artifact_identity_sha256": request_content_binding[
                "artifact_identity_sha256"
            ],
            "decision_request_content_artifact_revision": request_content_binding["artifact_revision"],
            "decision_request_content_artifact_sha256": request_content_binding["artifact_sha256"],
            "decision_scope_sha256": snapshot_binding["artifact_sha256"],
            **dict(FIRST_SLICE_BUDGET),
        }
        decision_identity = _sha(v3)
        branch_key = _sha({
            "namespace": "RUNTIME_JOB_PREAPPROVAL_BRANCH_KEY_V1",
            "predecessor_job_authority_event_id": jae,
            "predecessor_job_execution_authority_snapshot_id": jxs,
            "predecessor_job_execution_authority_snapshot_sha256": snapshot_binding["artifact_sha256"],
            "predecessor_job_execution_snapshot_registration_sha256": registration_binding_dict[
                "artifact_sha256"
            ],
        })
        branch = {
            "schema": "RUNTIME_JOB_PREAPPROVAL_DRE_BRANCH_SELECTION_SEMANTIC_V2",
            "preapproval_branch_key_sha256": branch_key,
            "branch_code": "DRE_ISSUANCE_SELECTED",
            "predecessor_job_authority_event_id": jae,
            "predecessor_job_execution_authority_snapshot_id": jxs,
            "predecessor_job_execution_authority_snapshot_sha256": snapshot_binding["artifact_sha256"],
            "predecessor_job_execution_snapshot_registration_sha256": registration_binding_dict[
                "artifact_sha256"
            ],
            "snapshot_decision_request_key_sha256": request_key,
            "decision_request_event_id": dre,
            "decision_request_identity_sha256": decision_identity,
            "request_recovery_mode": "INLINE_COMPLETE_REQUEST_BINDING_V3",
            "decision_request_binding_v3": v3,
        }
        branch_binding_dict = _persist_exact_json(
            self.store,
            kind="PREAPPROVAL_DRE_BRANCH",
            job_id=prepared.job_id,
            record=branch,
        )
        branch_binding = R009OpaqueArtifactBinding(
            branch_binding_dict["artifact_identity_sha256"],
            branch_binding_dict["artifact_revision"],
            branch_binding_dict["artifact_sha256"],
        )
        branch_source = self.job_authority.select_or_replay_one_preapproval_branch_for_active_registration_v2(
            branch_binding=branch_binding
        )
        if branch_source.get("preapproval_branch_key_sha256") != branch_key:
            raise GeneralChatFormalPrepareError("PREAPPROVAL_BRANCH_CURRENTNESS", "branch source mismatch")

        request_source = self.human_decision.issue_or_replay_one_decision_request_for_selected_active_snapshot_v3(
            preapproval_branch_key_sha256=branch_key
        )
        if (
            request_source.get("decision_request_event_id") != dre
            or request_source.get("decision_request_identity_sha256") != decision_identity
        ):
            raise GeneralChatFormalPrepareError("HUMAN_REQUEST_CURRENTNESS", "human request source mismatch")

        return {
            "status": "AWAITING_EXPLICIT_HUMAN_APPROVAL",
            "formal_job": True,
            "job_id": prepared.job_id,
            "job_bundle_sha256": prepared.job_bundle_record["job_bundle_sha256"],
            "job_bundle_binding": prepared.job_bundle_binding,
            "web_formal_job_intake_binding": intake_binding,
            "job_authority_event_id": jae,
            "job_execution_authority_snapshot_id": jxs,
            "job_execution_authority_snapshot_sha256": snapshot_binding["artifact_sha256"],
            "job_execution_snapshot_registration_sha256": registration_binding_dict["artifact_sha256"],
            "decision_request_event_id": dre,
            "decision_request_identity_sha256": decision_identity,
            "decision_scope_sha256": snapshot_binding["artifact_sha256"],
            "requested_decision_code": "APPROVE_ONE_LIVE_ATTEMPT",
            "approval_budget": dict(FIRST_SLICE_BUDGET),
            "model_profile": LOGICAL_PROFILE,
            "provider": prepared.model_resolution["provider"],
            "model_entry_id": prepared.model_resolution["model_entry_id"],
            "provider_execution_config_sha256": prepared.provider_execution_config_sha256,
            "endpoint_origin": prepared.provider_execution_config["endpoint_origin"],
            "api_route": prepared.provider_execution_config["api_route"],
            "proxy_mode": prepared.provider_execution_config["proxy_mode"],
            "credential_ref_id": prepared.provider_execution_config["credential_ref_id"],
            "credential_ref_class": prepared.provider_execution_config["credential_ref_class"],
            "credential_value_read": False,
            "network_called": False,
            "model_called": False,
            "grant_created": False,
            "attempt_claim_created": False,
        }
