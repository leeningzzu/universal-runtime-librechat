from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.util import find_spec

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import queue
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.core.formal_model_job import FormalModelJobLedger
from universal_runtime.core.job_authority import JobAuthorityRegistry
from universal_runtime.core.formal_model_live_composition import (
    P1S3StopControl,
    P1S3StopControlError,
    P1S3StopControlRegistry,
)
from universal_runtime.core.job_artifact_bindings import (
    JobArtifactBindingError,
    assert_job_artifact_binding_current,
    create_job_artifact_binding_plan,
)
from universal_runtime.core.job_permissions import JobFilesystemPermissionPlan, JobPermissionError
from universal_runtime.core.job_pins import JobCapabilityPin, JobPinError
from universal_runtime.core.load_plan import LoadInput, LoadPlan, ParseMode
from universal_runtime.document_artifact_consumer import (
    DocumentArtifactConsumerError,
    persist_local_document_bundle,
    project_native_document_format_for_filename,
)
from universal_runtime.document_parse_adapter import DoclingSidecarBinding
from universal_runtime.web_general_chat_formal_prepare import (
    GeneralChatFormalPrepareError,
    GeneralChatFormalPrepareService,
    validate_non_authority_personal_context_snapshot,
)
from universal_runtime.web_conversation_graph import build_active_context_snapshot
from universal_runtime.version import __version__
from universal_runtime.web_continuity import (
    PROJECT_CONTEXT_POLICIES,
    PROJECT_CONTEXT_POLICY_PROJECT_ONLY,
    WebContinuityError,
    WebContinuityService,
)
from universal_runtime.web_project_semantic_search import (
    ProjectSemanticSearchAdapter,
    ProjectSemanticSearchError,
)
from universal_runtime.web_project_memory import ProjectMemoryError, ProjectMemoryService
from universal_runtime.c5_supported_runtime_owner import (
    supported_runtime_owner, supported_runtime_attestation,
)
from universal_runtime.c5_retirement_runtime_routes import (
    install_project_retirement_routes,
    register_project_execution_under_c5_fence,
)
from universal_runtime.web_project_context_mcp import create_project_context_mcp

def _first_party_runtime_root() -> Path:
    """Derive logical Runtime home from the actual canonical CLI provider.

    The current Windows Daily imports webapp from a replaceable machine-local
    overlay, while cli.py remains in Runtime's canonical src package. Module
    location is not Runtime data identity. No user/drive/host path is stored.
    """
    spec = find_spec("universal_runtime.cli")
    if spec is None or not isinstance(spec.origin, str):
        raise RuntimeError("RUNTIME_FIRST_PARTY_CANONICAL_CLI_UNAVAILABLE")
    path = Path(spec.origin)
    if path.name != "cli.py" or path.parent.name != "universal_runtime" or path.parent.parent.name != "src":
        raise RuntimeError("RUNTIME_FIRST_PARTY_CLI_SOURCE_ROLE_INVALID")
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("RUNTIME_FIRST_PARTY_CANONICAL_CLI_INVALID")
    resolved = path.resolve(strict=True)
    root = resolved.parents[2]
    current = root / "src" / "universal_runtime" / "cli.py"
    if not current.is_file() or current.is_symlink() or current.resolve(strict=True) != resolved:
        raise RuntimeError("RUNTIME_FIRST_PARTY_CANONICAL_CLI_CHANGED")
    return root


ROOT = _first_party_runtime_root()
CORE_GENERAL_CHAT_CAPABILITY_MANIFEST = (
    Path(__file__).resolve().parent / 'core_capabilities' / 'general_chat_r001' / 'capability.json'
)


def _semantic_search_sidecar_root() -> Path | None:
    raw = os.environ.get("UNIVERSAL_RUNTIME_FASTEMBED_SIDECAR_ROOT")
    if raw is None or not raw.strip():
        return None
    path = Path(raw)
    if not path.is_absolute():
        raise RuntimeError("UNIVERSAL_RUNTIME_FASTEMBED_SIDECAR_ROOT must be absolute")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise RuntimeError("UNIVERSAL_RUNTIME_FASTEMBED_SIDECAR_ROOT does not exist")
    return resolved
_PROJECT_CONTEXT_MCP, _PROJECT_CONTEXT_MCP_ASGI = create_project_context_mcp(
    runtime_root=ROOT,
    service_getter=lambda: _service(),
)


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    # Native OS owner retained through one supported ASGI lifespan only;
    # separate admission is required for independent Job/file writers.
    with supported_runtime_owner():
        async with _PROJECT_CONTEXT_MCP.session_manager.run():
            yield


app = FastAPI(title="Local Universal Runtime", version=__version__, lifespan=_app_lifespan)

@app.get("/_c5/supported-owner-attestation")
def _c5_supported_owner_attestation(request: Request):
    """Exact version attestation over existing Runtime bridge authentication."""
    expected = os.environ.get("UNIVERSAL_RUNTIME_BRIDGE_GUARD_SHA256", "")
    supplied = request.headers.get("x-ur-bridge-guard", "")
    actual = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", expected or "") or not hmac.compare_digest(actual, expected):
        raise HTTPException(status_code=403, detail="C5_OWNER_BRIDGE_AUTH_REQUIRED")
    try:
        return supported_runtime_attestation()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="C5_SUPPORTED_OWNER_UNAVAILABLE") from exc

_BRIDGE_GUARD_SHA256 = os.environ.get("UNIVERSAL_RUNTIME_BRIDGE_GUARD_SHA256", "").strip().lower()


def _request_client_is_loopback(request: Request) -> bool:
    if request.client is None or not request.client.host:
        return False
    host = request.client.host.split("%", 1)[0]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@app.middleware("http")
async def _require_bridge_guard_for_nonloopback(request: Request, call_next):
    if _request_client_is_loopback(request):
        return await call_next(request)
    if not _BRIDGE_GUARD_SHA256 or not re.fullmatch(r"[0-9a-f]{64}", _BRIDGE_GUARD_SHA256):
        return JSONResponse(status_code=503, content={"detail": "RUNTIME_BRIDGE_GUARD_NOT_CONFIGURED"})
    supplied = request.headers.get("x-ur-bridge-guard", "")
    actual = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual, _BRIDGE_GUARD_SHA256):
        return JSONResponse(status_code=403, content={"detail": "RUNTIME_BRIDGE_GUARD_REQUIRED"})
    return await call_next(request)


app.mount("/mcp/project-context", _PROJECT_CONTEXT_MCP_ASGI)

_MARKDOWN_IT_VERSION = "14.3.1"
_MARKDOWN_IT_VENDOR_SHA256 = "b1d56e32cbc489aac37dfe76136c5040840eb7af693785ba3a83310c2b4f4999"
_MARKDOWN_IT_VENDOR_PATH = (
    Path(__file__).resolve().parent / "web_vendor" / "markdown-it-14.3.1.min.js"
)

_SERVICE: WebContinuityService | None = None
P1_S2_STREAM_QUEUE_MAX = 32
_P1_S3_STOP_REGISTRY = P1S3StopControlRegistry()


def _p1_s3_active_project_execution_count(project_id: str) -> int:
    """Read the exact process-local active execution owner for one Runtime Project."""
    if not isinstance(project_id, str) or re.fullmatch(r"PRJ_[A-Za-z0-9_]{8,128}", project_id) is None:
        raise RuntimeError("C5_CURRENT_EXECUTION_PROJECT_ID_INVALID")
    registry = _P1_S3_STOP_REGISTRY
    lock = getattr(registry, "_lock", None)
    items = getattr(registry, "_items", None)
    if lock is None or not isinstance(items, dict):
        raise RuntimeError("C5_CURRENT_EXECUTION_REGISTRY_UNAVAILABLE")
    with lock:
        count = 0
        for control in items.values():
            if not callable(getattr(control, "snapshot", None)):
                raise RuntimeError("C5_CURRENT_EXECUTION_RECORD_INVALID")
            snapshot = control.snapshot()
            if not isinstance(snapshot, dict):
                raise RuntimeError("C5_CURRENT_EXECUTION_RECORD_INVALID")
            if snapshot.get("project_id") == project_id and snapshot.get("phase") != "WORKER_TERMINAL":
                count += 1
        return count


def _register_p1_s3_execution_under_c5_fence(
    *, project_id: str, chat_id: str, job_id: str,
    decision_request_event_id: str, execution_instance_id: str,
) -> P1S3StopControl:
    """Linearize current execution registration against one exact C5 Project lease."""
    try:
        return register_project_execution_under_c5_fence(
            runtime_project_id=project_id,
            register=lambda: _P1_S3_STOP_REGISTRY.register(
                project_id=project_id,
                chat_id=chat_id,
                job_id=job_id,
                decision_request_event_id=decision_request_event_id,
                execution_instance_id=execution_instance_id,
            ),
        )
    except RuntimeError as exc:
        if str(exc) == "C5_PROJECT_DELETE_LEASE_ACTIVE":
            raise P1S3StopControlError(
                "C5_PROJECT_DELETE_LEASE_ACTIVE",
                "Project deletion holds the current execution fence",
            ) from exc
        raise


_DOCUMENT_UPLOAD_MAX_BYTES = 64 * 1024 * 1024
_DOCLING_C1_COMBINED_LOCK_SHA256 = "3011b7dbce2adb82940674fd4b7f87fb04a58a9d893525380e9c3b0cf508aa2c"
_DOCLING_C1_ACCEPTED_INSTALL_RESULT_SHA256 = "f8842462bba2f1fd9329160c64eb4a8ee4bd587f3bf39c882afb0fdfe203542d"
_DOCLING_C1_EXPECTED_PACKAGES = (('docling-slim', '2.126.0'), ('docling-core', '2.95.0'), ('defusedxml', '0.7.1'), ('doclang', '0.7.3'), ('docling-parse', '7.17.0'), ('filetype', '1.2.0'), ('jsonref', '1.1.0'), ('jsonschema', '4.26.0'), ('latex2mathml', '3.81.1'), ('numpy', '2.5.3'), ('pandas', '3.0.5'), ('pillow', '12.3.0'), ('pluggy', '1.6.0'), ('pydantic', '2.13.5'), ('pydantic_core', '2.46.5'), ('pydantic-settings', '2.15.0'), ('pypdfium2', '5.13.0'), ('python-docx', '1.2.0'), ('PyYAML', '6.0.3'), ('requests', '2.34.2'), ('charset-normalizer', '3.5.1'), ('idna', '3.19'), ('rtree', '1.4.1'), ('scipy', '1.18.1'), ('tabulate', '0.10.0'), ('tqdm', '4.70.0'), ('typer', '0.26.8'), ('typing_extensions', '4.16.0'), ('urllib3', '2.7.0'), ('annotated-doc', '0.0.5'), ('annotated-types', '0.8.0'), ('attrs', '26.1.0'), ('certifi', '2026.7.22'), ('jsonschema-specifications', '2025.9.1'), ('lxml', '6.1.3'), ('python-dateutil', '2.9.0.post0'), ('python-dotenv', '1.2.3'), ('pywin32', '312'), ('referencing', '0.37.0'), ('rich', '15.0.0'), ('Pygments', '2.21.0'), ('markdown-it-py', '4.2.0'), ('mdurl', '0.1.2'), ('rpds-py', '2026.6.3'), ('shellingham', '1.5.4'), ('six', '1.17.0'), ('typing-inspection', '0.4.4'), ('colorama', '0.4.6'), ('tzdata', '2026.3'))


def _document_base_filename(filename: str) -> str:
    if not isinstance(filename, str) or not filename or Path(filename).name != filename:
        raise WebContinuityError("INVALID_DOCUMENT_FILENAME", "document filename must be a base name", status_code=400)
    return filename


def _document_upload_filename(filename: str) -> str:
    filename = _document_base_filename(filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise WebContinuityError("UNSUPPORTED_DOCUMENT_FORMAT", "local document parsing accepts only PDF/DOCX", status_code=400)
    return filename


def _native_document_bundle_filename(filename: str) -> str:
    filename = _document_base_filename(filename)
    if project_native_document_format_for_filename(filename) is None:
        raise WebContinuityError(
            "UNSUPPORTED_DOCUMENT_FORMAT",
            "native Project Source bundle type is not allowlisted",
            status_code=400,
        )
    return filename


def _accepted_c1_docling_sidecar_binding() -> DoclingSidecarBinding:
    return DoclingSidecarBinding(
        sidecar_root=Path(os.environ.get("INQUIRY_DOCLING_SIDE_CAR_ROOT", str(ROOT / ".sidecars" / "docling_slim_2_126_0_plane_c_c1"))),
        combined_lock_sha256=_DOCLING_C1_COMBINED_LOCK_SHA256,
        accepted_install_result_sha256=_DOCLING_C1_ACCEPTED_INSTALL_RESULT_SHA256,
        expected_packages=_DOCLING_C1_EXPECTED_PACKAGES,
    )


def _document_ingest_job_id(*, filename: str, input_sha256: str) -> str:
    # Bundle Artifact identity is content/provenance-derived, not command-derived. Keep
    # the ArtifactStore job identity stable across exact retries and across Projects so
    # an already-committed bundle can be replayed after a later Project-adoption STOP.
    raw = "\x1f".join(
        (
            "UR_WEB_DOCUMENT_BUNDLE_JOB_R002",
            filename,
            input_sha256,
            _DOCLING_C1_COMBINED_LOCK_SHA256,
            _DOCLING_C1_ACCEPTED_INSTALL_RESULT_SHA256,
        )
    ).encode("utf-8")
    return "JOB_WEBDOC_" + hashlib.sha256(raw).hexdigest()[:24].upper()


def _ingest_document_upload_bytes(
    *,
    service: WebContinuityService,
    command_id: str,
    project_id: str,
    expected_project_revision: int,
    filename: str,
    raw_bytes: bytes,
    chat_id: str | None,
) -> dict[str, Any]:
    filename = _document_upload_filename(filename)
    if not isinstance(raw_bytes, bytes) or not raw_bytes:
        raise WebContinuityError("EMPTY_DOCUMENT_UPLOAD", "document upload bytes must be non-empty", status_code=400)
    if len(raw_bytes) > _DOCUMENT_UPLOAD_MAX_BYTES:
        raise WebContinuityError("DOCUMENT_UPLOAD_TOO_LARGE", "document upload exceeds 64 MiB first-slice limit", status_code=413)

    current = service.resume_project(project_id)
    project = current.get("project")
    if not isinstance(project, dict) or project.get("project_revision") != expected_project_revision:
        raise WebContinuityError("STALE_PROJECT_REVISION", "expected project revision is stale", status_code=409)
    if chat_id is not None:
        rows = [x for x in current.get("chats", []) if x.get("chat", {}).get("chat_id") == chat_id]
        if len(rows) != 1:
            raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)

    input_sha = hashlib.sha256(raw_bytes).hexdigest()
    scratch_root = (service.store.root / "_web_document_scratch").resolve()
    if service.store.root != scratch_root.parent:
        raise WebContinuityError("SCRATCH_SCOPE_INVALID", "document scratch root escapes ArtifactStore root", status_code=500)
    scratch_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="ur_web_doc_", dir=scratch_root) as td:
            run_root = Path(td).resolve()
            source_path = run_root / filename
            source_path.write_bytes(raw_bytes)
            if source_path.read_bytes() != raw_bytes:
                raise WebContinuityError("DOCUMENT_UPLOAD_BYTE_MISMATCH", "document upload changed after local staging", status_code=500)
            parse_work = run_root / "parse_work"
            parse_work.mkdir()
            try:
                bundle = persist_local_document_bundle(
                    store=service.store,
                    input_path=source_path,
                    expected_input_sha256=input_sha,
                    allowed_roots=(run_root,),
                    parse_work_root=parse_work,
                    sidecar=_accepted_c1_docling_sidecar_binding(),
                    job_id=_document_ingest_job_id(
                        filename=filename,
                        input_sha256=input_sha,
                    ),
                )
            except (DocumentArtifactConsumerError, OSError, PermissionError, ValueError) as exc:
                raise WebContinuityError("DOCUMENT_PARSE_OR_BUNDLE_FAILED", str(exc), status_code=409) from exc
    finally:
        try:
            scratch_root.rmdir()
        except OSError:
            pass

    prefix = "RUNTIME_OPAQUE_"
    if not bundle.artifact_id.startswith(prefix):
        raise WebContinuityError("DOCUMENT_BUNDLE_BINDING_INVALID", "bundle artifact identity is invalid", status_code=500)
    identity = bundle.artifact_id[len(prefix):].lower()
    if re.fullmatch(r"[0-9a-f]{64}", identity) is None:
        raise WebContinuityError("DOCUMENT_BUNDLE_BINDING_INVALID", "bundle artifact identity SHA is invalid", status_code=500)
    bundle_binding = {
        "artifact_id": bundle.artifact_id,
        "artifact_identity_sha256": identity,
        "revision": bundle.artifact_revision,
        "sha256": bundle.artifact_sha256,
    }
    adopted = service.adopt_document_bundle_source(
        command_id=command_id,
        project_id=project_id,
        expected_project_revision=expected_project_revision,
        document_bundle_binding=bundle_binding,
        chat_id=chat_id,
        runtime_owned_c1_document_bundle=True,
    )
    return {
        **adopted,
        "document_bundle_artifact": {
            "artifact_id": bundle.artifact_id,
            "revision": bundle.artifact_revision,
            "sha256": bundle.artifact_sha256,
            "input_sha256": bundle.input_sha256,
            "input_format": bundle.input_format,
            "markdown_sha256": bundle.markdown_sha256,
            "json_sha256": bundle.json_sha256,
            "member_manifest_sha256": bundle.member_manifest_sha256,
            "persistence_class": bundle.persistence_class,
        },
    }


def _native_document_bundle_job_id(*, filename: str, bundle_sha256: str) -> str:
    raw = "\x1f".join(
        (
            "UR_WEB_LIBRECHAT_NATIVE_DOCUMENT_BUNDLE_JOB_R001",
            filename,
            bundle_sha256,
        )
    ).encode("utf-8")
    return "JOB_WEBNATIVE_" + hashlib.sha256(raw).hexdigest()[:24].upper()


def _ingest_prebuilt_document_bundle_bytes(
    *,
    service: WebContinuityService,
    command_id: str,
    project_id: str,
    expected_project_revision: int,
    filename: str,
    bundle_bytes: bytes,
) -> dict[str, Any]:
    filename = _native_document_bundle_filename(filename)
    if not isinstance(bundle_bytes, bytes) or not bundle_bytes:
        raise WebContinuityError("EMPTY_DOCUMENT_BUNDLE", "document bundle bytes must be non-empty", status_code=400)
    if len(bundle_bytes) > _DOCUMENT_UPLOAD_MAX_BYTES:
        raise WebContinuityError(
            "DOCUMENT_BUNDLE_TOO_LARGE",
            "document bundle exceeds 64 MiB internal limit",
            status_code=413,
        )

    current = service.resume_project(project_id)
    project = current.get("project")
    if not isinstance(project, dict) or project.get("project_revision") != expected_project_revision:
        raise WebContinuityError("STALE_PROJECT_REVISION", "expected project revision is stale", status_code=409)

    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    try:
        from universal_runtime.document_artifact_consumer import persist_librechat_native_document_bundle

        bundle = persist_librechat_native_document_bundle(
            store=service.store,
            bundle_bytes=bundle_bytes,
            expected_source_filename=filename,
            job_id=_native_document_bundle_job_id(filename=filename, bundle_sha256=bundle_sha),
        )
    except (DocumentArtifactConsumerError, OSError, PermissionError, ValueError) as exc:
        raise WebContinuityError("DOCUMENT_BUNDLE_ADMISSION_FAILED", str(exc), status_code=409) from exc

    prefix = "RUNTIME_OPAQUE_"
    if not bundle.artifact_id.startswith(prefix):
        raise WebContinuityError("DOCUMENT_BUNDLE_BINDING_INVALID", "bundle artifact identity is invalid", status_code=500)
    identity = bundle.artifact_id[len(prefix):].lower()
    if re.fullmatch(r"[0-9a-f]{64}", identity) is None:
        raise WebContinuityError("DOCUMENT_BUNDLE_BINDING_INVALID", "bundle artifact identity SHA is invalid", status_code=500)
    bundle_binding = {
        "artifact_id": bundle.artifact_id,
        "artifact_identity_sha256": identity,
        "revision": bundle.artifact_revision,
        "sha256": bundle.artifact_sha256,
    }
    adopted = service.adopt_document_bundle_source(
        command_id=command_id,
        project_id=project_id,
        expected_project_revision=expected_project_revision,
        document_bundle_binding=bundle_binding,
        chat_id=None,
    )
    return {
        **adopted,
        "document_bundle_artifact": {
            "artifact_id": bundle.artifact_id,
            "revision": bundle.artifact_revision,
            "sha256": bundle.artifact_sha256,
            "input_sha256": bundle.input_sha256,
            "input_format": bundle.input_format,
            "markdown_sha256": bundle.markdown_sha256,
            "json_sha256": bundle.json_sha256,
            "member_manifest_sha256": bundle.member_manifest_sha256,
            "persistence_class": bundle.persistence_class,
        },
    }


def _service() -> WebContinuityService:
    global _SERVICE
    if _SERVICE is None:
        artifact_root = Path(os.environ.get("UNIVERSAL_RUNTIME_ARTIFACT_ROOT", str(ROOT / "artifacts")))
        machine_local_env = os.environ.get("UNIVERSAL_RUNTIME_MACHINE_LOCAL_STATE_ROOT")
        if machine_local_env:
            machine_local_state_root = Path(machine_local_env)
        else:
            local_app_data = os.environ.get("LOCALAPPDATA")
            machine_local_state_root = (
                Path(local_app_data) / "UniversalRuntime" / "machine_local"
                if local_app_data
                else ROOT / ".universal_runtime_machine_local"
            )
        _SERVICE = WebContinuityService(
            ArtifactStore(artifact_root),
            machine_local_state_root=machine_local_state_root,
        )
    return _SERVICE


# Adds only the existing Runtime retirement/SourceRef read-only C5 routes.
# Destructive admission remains owner/membership/current-execution fenced;
# normal deletion uses the durable forward receipt and creates no global backup.
install_project_retirement_routes(
    app,
    _service,
    runtime_root=ROOT,
    active_worker_count=_P1_S3_STOP_REGISTRY.active_count,
    active_project_worker_count=_p1_s3_active_project_execution_count,
    owner_attestation=supported_runtime_attestation,
)


def _memory_service() -> ProjectMemoryService:
    return ProjectMemoryService(_service().store)


def _raise_memory_http(exc: ProjectMemoryError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


def _raise_http(exc: WebContinuityError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


def _require_dict(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail={"code": "INVALID_JSON", "message": "JSON object required"})
    return payload


def _int_field(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise HTTPException(status_code=400, detail={"code": "INVALID_INPUT", "message": f"{key} must be an integer"})
    return value


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _p1_s2_sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    if event not in {"open", "delta", "final", "error", "cancelled"}:
        raise ValueError("unsupported P1-S2 SSE event")
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"event: {event}\ndata: {raw}\n\n".encode("utf-8")


def _p1_s2_stream_worker(
    *,
    formal_service: Any,
    project_formal_result: Any,
    command_id: str,
    project_id: str,
    chat_id: str,
    job_id: str,
    decision_request_event_id: str,
    emit_event: Any,
    stop_control: P1S3StopControl | None = None,
) -> dict[str, Any]:
    """Run one exact approved streaming attempt; provisional deltas stay out of Chat authority."""
    visible_parts: list[str] = []
    sequence = 0
    provisional_delivery_complete = True
    provisional_delta_drop_count = 0

    def emit_visible_delta(text: str) -> None:
        nonlocal sequence, provisional_delivery_complete, provisional_delta_drop_count
        if not isinstance(text, str) or not text:
            raise RuntimeError("streaming visible delta must be non-empty text")
        sequence += 1
        visible_parts.append(text)
        delivered = emit_event("delta", {"sequence": sequence, "text": text})
        if delivered is False:
            provisional_delivery_complete = False
            provisional_delta_drop_count += 1

    current_context = _current_active_context_snapshot(project_id, chat_id)
    current_context_guard = {
        "chat_revision": current_context.get("chat_revision"),
        "head_event_id": current_context.get("head_event_id"),
        "active_context_snapshot_sha256": current_context.get("active_context_snapshot_sha256"),
    }
    result = formal_service.execute_approved_streaming_attempt_v1(
        project_id=project_id,
        chat_id=chat_id,
        expected_job_id=job_id,
        decision_request_event_id=decision_request_event_id,
        emit_visible_delta=emit_visible_delta,
        stop_control=stop_control,
        web_current_context_guard=current_context_guard,
    )
    if result.get("status") == "FORMAL_MODEL_STREAM_CANCELLED":
        cancellation = result.get("cancellation_outcome")
        binding = result.get("cancellation_outcome_binding")
        if not isinstance(cancellation, dict) or not isinstance(binding, dict):
            raise RuntimeError("confirmed cancellation lacks exact Runtime receipt")
        cancelled_payload = {
            "job_id": job_id,
            "decision_request_event_id": decision_request_event_id,
            "code": cancellation.get("cancellation_code"),
            "cancellation_receipt_sha256": binding.get("artifact_sha256"),
            "cancellation_receipt_identity_sha256": binding.get("artifact_identity_sha256"),
            "cancellation_receipt_binding": {
                "artifact_identity_sha256": binding.get("artifact_identity_sha256"),
                "artifact_revision": binding.get("artifact_revision"),
                "artifact_sha256": binding.get("artifact_sha256"),
            },
            "partial_output_persisted": cancellation.get("partial_output_persisted"),
            "retry_allowed": cancellation.get("retry_allowed"),
        }
        if (
            cancelled_payload["code"] != "ATTEMPT_CLAIMED_CANCELLED_BY_USER"
            or cancelled_payload["partial_output_persisted"] is not False
            or cancelled_payload["retry_allowed"] is not False
        ):
            raise RuntimeError("Runtime cancellation receipt semantic mismatch")
        emit_event("cancelled", cancelled_payload)
        return {"formal": result, "projection": None, "cancelled": cancelled_payload}

    assistant_text = result.get("assistant_text")
    if not isinstance(assistant_text, str) or not assistant_text:
        raise RuntimeError("streaming formal result assistant text missing")
    if "".join(visible_parts) != assistant_text:
        raise RuntimeError("provisional visible deltas differ from Runtime final assistant output")

    projection = project_formal_result(
        command_id=command_id + "-project-final",
        project_id=project_id,
        chat_id=chat_id,
        intake_binding=result.get("web_formal_job_intake_binding"),
        formal_result_commit_binding=result.get("formal_result_commit_binding"),
    )
    if projection.get("status") != "PROJECTED":
        raise RuntimeError("Runtime formal result did not project exactly once")
    assistant_event = projection.get("assistant_event")
    chat = projection.get("chat")
    if not isinstance(assistant_event, dict) or not isinstance(chat, dict):
        raise RuntimeError("canonical projected assistant/chat state missing")
    if assistant_event.get("content") != assistant_text:
        raise RuntimeError("canonical projected assistant differs from streamed final text")

    final_payload = {
        "job_id": job_id,
        "decision_request_event_id": decision_request_event_id,
        "visible_delta_count": sequence,
        "assistant_text": assistant_text,
        "assistant_content_sha256": hashlib.sha256(assistant_text.encode("utf-8")).hexdigest(),
        "assistant_event_id": assistant_event.get("event_id"),
        "assistant_parent_event_id": assistant_event.get("parent_event_id"),
        "chat_revision": chat.get("chat_revision"),
        "head_event_id": chat.get("head_event_id"),
        "provisional_stream_persisted": False,
        "provisional_delivery_complete": provisional_delivery_complete,
        "provisional_delta_drop_count": provisional_delta_drop_count,
    }
    emit_event("final", final_payload)
    return {"formal": result, "projection": projection, "final": final_payload}


def _stable_web_job_id(*parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return "JOB_LIBSRC_" + hashlib.sha256(raw).hexdigest()[:24].upper()


def _p1_s3_execution_instance_id(
    *, project_id: str, chat_id: str, job_id: str, decision_request_event_id: str, command_id: str
) -> str:
    raw = "\x1f".join(
        ("UR_WEB_R004_P1_S3_EXECUTION_INSTANCE_V1", project_id, chat_id, job_id, decision_request_event_id, command_id)
    ).encode("utf-8")
    return "EXEC_P1S3_" + hashlib.sha256(raw).hexdigest()[:24].upper()


def _source_context_post_append_recovery(
    *,
    command_id: str,
    message_command_id: str,
    expected_chat_revision: int,
    source_ref_id: str,
    question_sha256: str,
    appended: dict[str, Any],
    reason_code: str,
    message: str,
) -> dict[str, Any]:
    """Return an explicit idempotent recovery contract after USER_MESSAGE commit."""
    return {
        "result": "STOP_NATIVE_SOURCE_CONTEXT_POST_APPEND_RECOVERABLE_R002",
        "formal_model_job_executed": False,
        "model_provider_call": False,
        "network_call": False,
        "chat": appended["chat"],
        "event": appended["event"],
        "source_context": None,
        "source_context_sha256": None,
        "recovery": {
            "schema": "UR_LIBRARY_SOURCE_CONTEXT_POST_APPEND_RECOVERY_R001",
            "recovery_class": "IDEMPOTENT_SAME_COMMAND_RETRY",
            "reason_code": reason_code,
            "message": message,
            "retry_command_id": command_id,
            "message_command_id": message_command_id,
            "original_expected_chat_revision": expected_chat_revision,
            "source_ref_id": source_ref_id,
            "question_sha256": question_sha256,
            "initiating_user_event_id": appended["event"]["event_id"],
            "retry_precondition": "SOURCE_AND_CAPABILITY_CURRENTNESS_RESTORED",
            "retry_must_reuse_exact": ["retry_command_id", "original_expected_chat_revision", "source_ref_id", "question"],
            "duplicate_user_message_on_exact_retry": False,
            "formal_job_prepared": False,
            "human_approval_requested": False,
            "provider_call": False,
        },
    }


def _prepare_native_source_context(
    *,
    command_id: str,
    project_id: str,
    chat_id: str,
    expected_chat_revision: int,
    source_ref_id: str,
    content: str | None = None,
    existing_user_event_id: str | None = None,
) -> dict[str, Any]:
    """Compose one native Runtime SourceRef into one exact formal-input proposal."""
    if not isinstance(command_id, str) or not command_id:
        raise WebContinuityError("INVALID_COMMAND_ID", "command_id must be non-empty")
    if not isinstance(source_ref_id, str) or not source_ref_id:
        raise WebContinuityError("INVALID_INPUT", "source_ref_id must be non-empty")
    if existing_user_event_id is None:
        if not isinstance(content, str) or content == "":
            raise WebContinuityError("INVALID_INPUT", "content must be non-empty text")
    elif not isinstance(existing_user_event_id, str) or not existing_user_event_id:
        raise WebContinuityError("INVALID_INPUT", "existing_user_event_id must be non-empty text")

    service = _service()
    before = service.resume_project(project_id)
    chat_rows = [item for item in before.get("chats", []) if item.get("chat", {}).get("chat_id") == chat_id]
    if len(chat_rows) != 1:
        raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
    existing_user_event = None
    if existing_user_event_id is not None:
        chat_record = chat_rows[0]["chat"]
        if chat_record.get("chat_revision") != expected_chat_revision or chat_record.get("head_event_id") != existing_user_event_id:
            raise WebContinuityError("STALE_CHAT", "existing USER_MESSAGE must be exact current head", status_code=409)
        event_rows = [item for item in chat_rows[0].get("events", []) if item.get("event", {}).get("event_id") == existing_user_event_id]
        if len(event_rows) != 1:
            raise WebContinuityError("STALE_OR_TAMPERED", "existing initiating USER_MESSAGE did not resolve exactly once", status_code=409)
        existing_user_event = event_rows[0]
        event_record = existing_user_event.get("event") or {}
        if event_record.get("event_type") != "USER_MESSAGE" or event_record.get("actor_class") != "USER":
            raise WebContinuityError("INVALID_EXISTING_USER_EVENT", "existing event must be USER_MESSAGE", status_code=409)
        content = event_record.get("content")
        if not isinstance(content, str) or not content:
            raise WebContinuityError("INVALID_EXISTING_USER_EVENT", "existing USER_MESSAGE content missing", status_code=409)
        if _canonical_sha256({"content": content}) is None:
            raise WebContinuityError("INVALID_EXISTING_USER_EVENT", "existing USER_MESSAGE content invalid", status_code=409)
        existing_source_refs = event_record.get("related_source_ref_ids")
        if not isinstance(existing_source_refs, list) or source_ref_id not in existing_source_refs:
            raise WebContinuityError(
                "SOURCE_CONTEXT_EXISTING_USER_EVENT_SOURCE_MISMATCH",
                "existing USER_MESSAGE provenance does not contain the requested SourceRef",
                status_code=409,
            )
    source_rows = [item for item in before.get("sources", []) if item.get("source_ref", {}).get("source_ref_id") == source_ref_id]
    if len(source_rows) != 1:
        raise WebContinuityError("SOURCE_NOT_BOUND", "SourceRef is not bound to this Project", status_code=404)
    source_row = source_rows[0]
    source_ref = source_row["source_ref"]
    if source_ref.get("project_id") != project_id:
        raise WebContinuityError("SCOPE_MISMATCH", "SourceRef project mismatch", status_code=409)

    source_binding = source_ref.get("source_artifact_binding")
    if not isinstance(source_binding, dict):
        raise WebContinuityError("SOURCE_STALE_OR_TAMPERED", "source binding missing", status_code=409)
    try:
        source_manifest, source_bytes = service.store.load_exact_r009_opaque_artifact_r001_v1(
            artifact_identity_sha256=source_binding["artifact_identity_sha256"],
            artifact_revision=int(source_binding["revision"]),
            artifact_sha256=source_binding["sha256"],
        )
    except Exception as exc:
        raise WebContinuityError("SOURCE_STALE_OR_TAMPERED", "source exact-byte binding failed", status_code=409) from exc
    if hashlib.sha256(source_bytes).hexdigest() != source_binding.get("sha256"):
        raise WebContinuityError("SOURCE_STALE_OR_TAMPERED", "source SHA mismatch", status_code=409)

    derivation = source_row.get("text_derivation")
    if not isinstance(derivation, dict) or derivation.get("source_sha256") != source_binding.get("sha256"):
        raise WebContinuityError("DERIVATION_STALE", "TextDerivation source binding mismatch", status_code=409)
    decoded_text = derivation.get("decoded_text")
    if not isinstance(decoded_text, str):
        raise WebContinuityError("DERIVATION_STALE", "TextDerivation decoded text missing", status_code=409)
    if hashlib.sha256(decoded_text.encode("utf-8")).hexdigest() != derivation.get("derivation_sha256"):
        raise WebContinuityError("DERIVATION_STALE", "TextDerivation SHA mismatch", status_code=409)

    question_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    provisional_job_id = _stable_web_job_id(project_id, chat_id, source_ref_id, command_id, question_sha)
    try:
        pin = JobCapabilityPin.from_manifest(
            job_id=provisional_job_id,
            manifest_path=CORE_GENERAL_CHAT_CAPABILITY_MANIFEST,
        )
        pin.assert_current(CORE_GENERAL_CHAT_CAPABILITY_MANIFEST)
        permission = JobFilesystemPermissionPlan.from_job_pin(pin, [service.store.root])
        load_plan = LoadPlan.from_inputs(
            plan_id=provisional_job_id + "-source-load",
            project_root=str(service.store.root),
            allowed_roots=[str(service.store.root)],
            required_inputs=[
                LoadInput(
                    reference=source_manifest.path,
                    role="PROJECT_SOURCE_PRIMARY",
                    expected_sha256=source_manifest.sha256,
                    parse_mode=ParseMode.BYTES,
                    required=True,
                    byte_budget=len(source_bytes),
                )
            ],
            execution_budget=1,
            load_budget=len(source_bytes),
        )
        authorized = permission.authorize_load_plan(pin, load_plan)
        binding_plan = create_job_artifact_binding_plan(
            job_pin=pin,
            selected={"PROJECT_SOURCE_PRIMARY": source_manifest},
            authorized_load=authorized,
        )
        selected_binding = assert_job_artifact_binding_current(
            binding_plan,
            job_id=pin.job_id,
            role="PROJECT_SOURCE_PRIMARY",
            artifact_id=source_manifest.artifact_id,
            revision=source_manifest.revision,
            sha256=source_manifest.sha256,
        )
    except (JobPinError, JobPermissionError, JobArtifactBindingError, ValueError) as exc:
        raise WebContinuityError("SOURCE_CONTEXT_REJECTED", str(exc), status_code=409) from exc

    message_command_id = "ctxmsg-" + hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:32]
    if existing_user_event is None:
        appended = service.append_user_message(
            command_id=message_command_id,
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=expected_chat_revision,
            content=content,
            related_source_ref_ids=[source_ref_id],
        )
    else:
        appended = {"chat": chat_rows[0]["chat"], "event": existing_user_event["event"]}

    try:
        pin.assert_current(CORE_GENERAL_CHAT_CAPABILITY_MANIFEST)
    except JobPinError:
        if existing_user_event is not None:
            raise WebContinuityError("SOURCE_CONTEXT_EXISTING_USER_EVENT_STALE", "Capability pin changed while binding the existing regenerate USER_MESSAGE", status_code=409)
        return _source_context_post_append_recovery(
            command_id=command_id,
            message_command_id=message_command_id,
            expected_chat_revision=expected_chat_revision,
            source_ref_id=source_ref_id,
            question_sha256=question_sha,
            appended=appended,
            reason_code="CAPABILITY_PIN_STALE_AFTER_USER_MESSAGE",
            message="Capability pin changed after the initiating USER_MESSAGE was committed. Restore currentness and retry the exact same source-context command; the USER_MESSAGE will be replayed, not duplicated.",
        )
    try:
        source_manifest_after, source_bytes_after = service.store.load_exact_r009_opaque_artifact_r001_v1(
            artifact_identity_sha256=source_binding["artifact_identity_sha256"],
            artifact_revision=int(source_binding["revision"]),
            artifact_sha256=source_binding["sha256"],
        )
    except Exception:
        if existing_user_event is not None:
            raise WebContinuityError("SOURCE_CONTEXT_EXISTING_USER_EVENT_STALE", "Source currentness changed while binding the existing regenerate USER_MESSAGE", status_code=409)
        return _source_context_post_append_recovery(
            command_id=command_id,
            message_command_id=message_command_id,
            expected_chat_revision=expected_chat_revision,
            source_ref_id=source_ref_id,
            question_sha256=question_sha,
            appended=appended,
            reason_code="SOURCE_STALE_AFTER_USER_MESSAGE",
            message="Source currentness changed after the initiating USER_MESSAGE was committed. Restore exact source currentness and retry the same source-context command; the USER_MESSAGE will be replayed, not duplicated.",
        )
    if source_manifest_after.sha256 != source_manifest.sha256 or source_bytes_after != source_bytes:
        if existing_user_event is not None:
            raise WebContinuityError("SOURCE_CONTEXT_EXISTING_USER_EVENT_STALE", "Source bytes changed while binding the existing regenerate USER_MESSAGE", status_code=409)
        return _source_context_post_append_recovery(
            command_id=command_id,
            message_command_id=message_command_id,
            expected_chat_revision=expected_chat_revision,
            source_ref_id=source_ref_id,
            question_sha256=question_sha,
            appended=appended,
            reason_code="SOURCE_CHANGED_AFTER_USER_MESSAGE",
            message="Source bytes changed after the initiating USER_MESSAGE was committed. Restore exact source currentness and retry the same source-context command; the USER_MESSAGE will be replayed, not duplicated.",
        )

    after = service.resume_project(project_id)
    event_id = appended["event"]["event_id"]
    event_rows = []
    for chat_row in after.get("chats", []):
        if chat_row.get("chat", {}).get("chat_id") != chat_id:
            continue
        event_rows.extend(item for item in chat_row.get("events", []) if item.get("event", {}).get("event_id") == event_id)
    if len(event_rows) != 1 or not isinstance(event_rows[0].get("binding") if event_rows else None, dict):
        if existing_user_event is not None:
            raise WebContinuityError("SOURCE_CONTEXT_EXISTING_USER_EVENT_BINDING_UNRESOLVED", "Existing regenerate USER_MESSAGE binding did not resolve exactly once", status_code=409)
        return _source_context_post_append_recovery(
            command_id=command_id,
            message_command_id=message_command_id,
            expected_chat_revision=expected_chat_revision,
            source_ref_id=source_ref_id,
            question_sha256=question_sha,
            appended=appended,
            reason_code="USER_EVENT_BINDING_UNRESOLVED_AFTER_APPEND",
            message="The committed initiating USER_MESSAGE did not resolve to one exact binding. Re-read current Runtime state and retry only the same source-context command; exact retry cannot duplicate the USER_MESSAGE.",
        )
    event_binding = event_rows[0]["binding"]

    context = {
        "schema": "UR_LIBRARY_NATIVE_SOURCE_CONTEXT_R001",
        "authority_class": "NON_AUTHORITY_FORMAL_INPUT_PROPOSAL",
        "project_id": project_id,
        "chat_id": chat_id,
        "initiating_user_event": {
            "event_id": event_id,
            "content_sha256": appended["event"]["content_sha256"],
            "binding": event_binding,
        },
        "source_ref_id": source_ref_id,
        "filename": source_ref.get("filename"),
        "media_type": source_binding.get("media_type"),
        "source_artifact": {
            "artifact_id": source_manifest.artifact_id,
            "artifact_identity_sha256": source_binding["artifact_identity_sha256"],
            "revision": source_manifest.revision,
            "sha256": source_manifest.sha256,
            "byte_size": len(source_bytes),
        },
        "derivation_sha256": derivation["derivation_sha256"],
        "selected_source_role": selected_binding.role,
        "selected_source_binding": {
            "artifact_id": selected_binding.artifact_id,
            "revision": selected_binding.revision,
            "sha256": selected_binding.sha256,
        },
        "load_plan_sha256": authorized.load_plan_sha256,
        "permission_plan_sha256": authorized.permission_plan_sha256,
        "job_artifact_binding_plan_sha256": binding_plan.binding_plan_sha256,
        "capability_pin": pin.to_dict(),
        "question": content,
        "decoded_text": decoded_text,
    }
    return {
        "result": "PASS_NATIVE_SOURCE_CONTEXT_PREPARE_R001",
        "formal_model_job_executed": False,
        "model_provider_call": False,
        "network_call": False,
        "chat": appended["chat"],
        "event": appended["event"],
        "existing_user_event_reused": existing_user_event is not None,
        "source_context": context,
        "source_context_sha256": _canonical_sha256(context),
    }


def _regenerate_post_branch_recovery(
    *,
    command_id: str,
    project_id: str,
    chat_id: str,
    source_ref_id: str,
    target_assistant_event_id: str,
    original_expected_chat_revision: int,
    branch: dict[str, Any],
    reason_code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "result": "STOP_REGENERATE_POST_BRANCH_RECOVERABLE_R001",
        "formal_model_job_executed": False,
        "model_provider_call": False,
        "network_call": False,
        "chat": branch["chat"],
        "event": branch["event"],
        "recovery": {
            "schema": "UR_WEB_R004_P1_REGENERATE_POST_BRANCH_RECOVERY_R001",
            "reason_code": reason_code,
            "message": message,
            "retry_command_id": command_id,
            "original_expected_chat_revision": original_expected_chat_revision,
            "target_assistant_event_id": target_assistant_event_id,
            "source_ref_id": source_ref_id,
            "new_user_event_id": branch["event"]["event_id"],
            "post_branch_chat_revision": branch["chat"]["chat_revision"],
            "post_branch_head_event_id": branch["chat"]["head_event_id"],
            "regenerated_from_user_event_id": branch["event"].get("regenerated_from_user_event_id"),
            "regenerated_from_assistant_event_id": branch["event"].get("regenerated_from_assistant_event_id"),
            "retry_must_reuse_exact": [
                "retry_command_id",
                "original_expected_chat_revision",
                "target_assistant_event_id",
                "source_ref_id",
            ],
            "duplicate_user_message_on_exact_retry": False,
            "predecessor_job_replay": False,
        },
    }


def _prepare_source_grounded_regenerate(
    *,
    command_id: str,
    project_id: str,
    chat_id: str,
    expected_chat_revision: int,
    target_assistant_event_id: str,
    source_ref_id: str,
    streaming: bool = False,
) -> dict[str, Any]:
    """Fresh sibling USER branch -> current Source Context -> fresh Job/approval request; no provider call."""
    if not isinstance(command_id, str) or not command_id:
        raise WebContinuityError("INVALID_COMMAND_ID", "command_id must be non-empty")
    branch = _service().regenerate_successful_assistant_as_branch(
        command_id=command_id,
        project_id=project_id,
        chat_id=chat_id,
        expected_chat_revision=expected_chat_revision,
        target_assistant_event_id=target_assistant_event_id,
    )
    context_command_id = "regenctx-" + hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:32]
    formal_command_id = "regenformal-" + hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:32]
    try:
        context = _prepare_native_source_context(
            command_id=context_command_id,
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=branch["chat"]["chat_revision"],
            source_ref_id=source_ref_id,
            existing_user_event_id=branch["event"]["event_id"],
        )
        if context.get("existing_user_event_reused") is not True:
            raise WebContinuityError("REGENERATE_DUPLICATE_USER_GUARD", "regenerate source context did not reuse the existing USER_MESSAGE", status_code=409)
        formal = _prepare_source_grounded_formal_approval(
            command_id=formal_command_id,
            project_id=project_id,
            chat_id=chat_id,
            source_context=context["source_context"],
            source_context_sha256=context["source_context_sha256"],
            streaming=streaming,
        )
        if formal.get("job_id") == branch.get("predecessor_job_id"):
            raise WebContinuityError("REGENERATE_PREDECESSOR_JOB_REPLAY_FORBIDDEN", "regenerate must create a fresh Job identity", status_code=409)
    except (WebContinuityError, GeneralChatFormalPrepareError) as exc:
        return _regenerate_post_branch_recovery(
            command_id=command_id,
            project_id=project_id,
            chat_id=chat_id,
            source_ref_id=source_ref_id,
            target_assistant_event_id=target_assistant_event_id,
            original_expected_chat_revision=expected_chat_revision,
            branch=branch,
            reason_code=getattr(exc, "code", type(exc).__name__),
            message=str(exc),
        )
    return {
        "result": "PASS_SOURCE_GROUNDED_REGENERATE_PREPARE_R001",
        "formal_model_job_executed": False,
        "model_provider_call": False,
        "network_call": False,
        "branch": branch,
        "chat": context["chat"],
        "event": context["event"],
        "source_context": context["source_context"],
        "source_context_sha256": context["source_context_sha256"],
        "formal": formal,
        "predecessor_job_id": branch["predecessor_job_id"],
        "fresh_job_id": formal["job_id"],
    }


def _find_exact_event(project_id: str, chat_id: str, event_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    resumed = _service().resume_project(project_id)
    rows = [row for row in resumed.get("chats", []) if row.get("chat", {}).get("chat_id") == chat_id]
    if len(rows) != 1:
        raise WebContinuityError("SCOPE_MISMATCH", "chat does not belong to project", status_code=409)
    event_rows = [item for item in rows[0].get("events", []) if item.get("event", {}).get("event_id") == event_id]
    if len(event_rows) != 1:
        raise WebContinuityError("STALE_OR_TAMPERED", "initiating user event did not resolve exactly once", status_code=409)
    return rows[0]["chat"], event_rows[0]["event"], event_rows[0]["binding"]


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "mode": "shadow"}


@app.get("/api/web/projects")
def web_projects() -> list[dict[str, Any]]:
    try:
        return _service().list_projects()
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects")
async def web_project_create(request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().create_project(
            command_id=payload.get("command_id"),
            display_name=payload.get("display_name"),
            instructions=payload.get("instructions", ""),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.get("/api/web/project-instructions/resolve")
def web_project_instructions_resolve(command_id: str, display_name: str) -> dict[str, Any]:
    try:
        resolved = _service().resolve_project_instructions_by_creation_identity(
            command_id=command_id,
            display_name=display_name,
        )
        if resolved is None:
            return {"found": False}
        return {"found": True, **resolved}
    except WebContinuityError as exc:
        _raise_http(exc)


@app.get("/api/web/projects/{project_id}")
def web_project_resume(project_id: str) -> dict[str, Any]:
    try:
        return _service().resume_project(project_id)
    except WebContinuityError as exc:
        _raise_http(exc)


@app.put("/api/web/projects/{project_id}/instructions")
async def web_project_instructions(project_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().revise_project_instructions(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=_int_field(payload, "expected_project_revision"),
            instructions=payload.get("instructions", ""),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.get("/api/web/projects/{project_id}/context-policy")
def web_project_context_policy_get(project_id: str) -> dict[str, Any]:
    try:
        return _service().get_project_context_policy(project_id=project_id)
    except WebContinuityError as exc:
        _raise_http(exc)


@app.put("/api/web/projects/{project_id}/context-policy")
async def web_project_context_policy_put(project_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().set_project_context_policy(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=_int_field(payload, "expected_project_revision"),
            context_policy=payload.get("context_policy"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.get("/api/web/projects/{project_id}/local-work-binding")
def web_project_local_work_binding_get(project_id: str) -> dict[str, Any]:
    try:
        return _service().get_project_local_work_binding(project_id=project_id)
    except WebContinuityError as exc:
        _raise_http(exc)


@app.put("/api/web/projects/{project_id}/local-work-binding")
async def web_project_local_work_binding_put(project_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().bind_project_local_work(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=_int_field(payload, "expected_project_revision"),
            executor=payload.get("executor"),
            local_project_root=payload.get("local_project_root"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.delete("/api/web/projects/{project_id}/local-work-binding")
async def web_project_local_work_binding_delete(project_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().unbind_project_local_work(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=_int_field(payload, "expected_project_revision"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.get("/api/web/projects/{project_id}/assistant-profile-binding")
def web_project_assistant_profile_binding_get(project_id: str) -> dict[str, Any]:
    try:
        return _service().get_project_assistant_profile_binding(project_id=project_id)
    except WebContinuityError as exc:
        _raise_http(exc)


@app.put("/api/web/projects/{project_id}/assistant-profile-binding")
async def web_project_assistant_profile_binding_put(
    project_id: str,
    request: Request,
) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().bind_project_assistant_profile(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=_int_field(payload, "expected_project_revision"),
            assistant_profile_id=payload.get("assistant_profile_id"),
            assistant_profile_revision=payload.get("assistant_profile_revision"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.delete("/api/web/projects/{project_id}/assistant-profile-binding")
async def web_project_assistant_profile_binding_delete(
    project_id: str,
    request: Request,
) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().unbind_project_assistant_profile(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=_int_field(payload, "expected_project_revision"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


def _memory_current_project(project_id: str) -> dict[str, Any]:
    current = _service().resume_project(project_id)
    project = current.get("project")
    if not isinstance(project, dict) or project.get("project_id") != project_id:
        raise WebContinuityError("SCOPE_MISMATCH", "project memory scope is unavailable", status_code=409)
    return project


@app.get("/api/web/projects/{project_id}/memory")
def web_project_memory_list(project_id: str) -> dict[str, Any]:
    try:
        _memory_current_project(project_id)
        return _memory_service().list_memories(project_id=project_id)
    except WebContinuityError as exc:
        _raise_http(exc)
    except ProjectMemoryError as exc:
        _raise_memory_http(exc)


@app.get("/api/web/projects/{project_id}/memory/context")
def web_project_memory_context(project_id: str) -> dict[str, Any]:
    try:
        _memory_current_project(project_id)
        return _memory_service().current_context(project_id=project_id)
    except WebContinuityError as exc:
        _raise_http(exc)
    except ProjectMemoryError as exc:
        _raise_memory_http(exc)


@app.post("/api/web/projects/{project_id}/memory")
async def web_project_memory_create(project_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        project = _memory_current_project(project_id)
        expected_project_revision = _int_field(payload, "expected_project_revision")
        if project.get("project_revision") != expected_project_revision:
            raise WebContinuityError("STALE_PROJECT_REVISION", "expected project revision is stale", status_code=409)
        return _memory_service().create_memory(
            command_id=payload.get("command_id"),
            project_id=project_id,
            content=payload.get("content"),
            project_revision_at_create=expected_project_revision,
        )
    except WebContinuityError as exc:
        _raise_http(exc)
    except ProjectMemoryError as exc:
        _raise_memory_http(exc)


@app.put("/api/web/projects/{project_id}/memory/{memory_id}")
async def web_project_memory_revise(project_id: str, memory_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        _memory_current_project(project_id)
        return _memory_service().revise_memory(
            command_id=payload.get("command_id"),
            project_id=project_id,
            memory_id=memory_id,
            expected_memory_revision=_int_field(payload, "expected_memory_revision"),
            content=payload.get("content"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)
    except ProjectMemoryError as exc:
        _raise_memory_http(exc)


@app.post("/api/web/projects/{project_id}/memory/{memory_id}/enabled")
async def web_project_memory_enabled(project_id: str, memory_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        _memory_current_project(project_id)
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise HTTPException(status_code=400, detail={"code":"INVALID_INPUT","message":"enabled must be boolean"})
        return _memory_service().set_memory_enabled(
            command_id=payload.get("command_id"),
            project_id=project_id,
            memory_id=memory_id,
            expected_memory_revision=_int_field(payload, "expected_memory_revision"),
            enabled=enabled,
        )
    except WebContinuityError as exc:
        _raise_http(exc)
    except ProjectMemoryError as exc:
        _raise_memory_http(exc)


@app.delete("/api/web/projects/{project_id}/memory/{memory_id}")
async def web_project_memory_delete(project_id: str, memory_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        _memory_current_project(project_id)
        return _memory_service().delete_memory(
            command_id=payload.get("command_id"),
            project_id=project_id,
            memory_id=memory_id,
            expected_memory_revision=_int_field(payload, "expected_memory_revision"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)
    except ProjectMemoryError as exc:
        _raise_memory_http(exc)


@app.post("/api/web/projects/{project_id}/chats")
async def web_chat_create(project_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().create_chat(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=_int_field(payload, "expected_project_revision"),
            title=payload.get("title", "New Chat"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.put("/api/web/projects/{project_id}/chats/{chat_id}/title")
async def web_chat_rename(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().rename_chat(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
            title=payload.get("title"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/archive")
async def web_chat_archive(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().archive_chat(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/unarchive")
async def web_chat_unarchive(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().unarchive_chat(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/delete")
async def web_chat_delete(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().delete_chat(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/messages")
async def web_chat_append(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().append_user_message(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
            content=payload.get("content"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.get("/api/web/projects/{project_id}/chats/{chat_id}/branch-state")
async def web_chat_branch_state(project_id: str, chat_id: str) -> dict[str, Any]:
    try:
        return _service().get_chat_branch_state(project_id=project_id, chat_id=chat_id)
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/messages/{event_id}/edit-branch")
async def web_chat_edit_branch(project_id: str, chat_id: str, event_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().edit_user_message_as_branch(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
            target_user_event_id=event_id,
            content=payload.get("content"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)




def _plain_regenerate_predecessor_provenance_v1(
    *,
    project_id: str,
    chat_id: str,
    target_assistant_event_id: str,
) -> dict[str, Any]:
    """Read-only predecessor provenance check; no branch mutation."""
    resumed = _service().resume_project(project_id)
    chat_rows = [
        row
        for row in resumed.get("chats", [])
        if isinstance(row, dict)
        and isinstance(row.get("chat"), dict)
        and row["chat"].get("chat_id") == chat_id
    ]
    if len(chat_rows) != 1:
        raise WebContinuityError(
            "PLAIN_REGENERATE_CHAT_CURRENTNESS_STOP",
            "plain Regenerate requires one exact current Chat projection",
            status_code=409,
        )
    event_rows = chat_rows[0].get("events")
    if not isinstance(event_rows, list):
        raise WebContinuityError(
            "PLAIN_REGENERATE_CHAT_CURRENTNESS_STOP",
            "plain Regenerate Chat event projection is unavailable",
            status_code=409,
        )
    events: dict[str, dict[str, Any]] = {}
    for row in event_rows:
        if not isinstance(row, dict) or not isinstance(row.get("event"), dict):
            continue
        event = row["event"]
        event_id = event.get("event_id")
        if isinstance(event_id, str) and event_id:
            events[event_id] = event

    target = events.get(target_assistant_event_id)
    if (
        not isinstance(target, dict)
        or target.get("event_type") != "ASSISTANT_MESSAGE"
        or target.get("actor_class") != "ASSISTANT"
    ):
        raise WebContinuityError(
            "PLAIN_REGENERATE_TARGET_CURRENTNESS_STOP",
            "plain Regenerate target Assistant is unavailable in the exact Chat projection",
            status_code=409,
        )
    original_user_event_id = target.get("parent_event_id")
    original_user = events.get(original_user_event_id)
    if (
        not isinstance(original_user, dict)
        or original_user.get("event_type") != "USER_MESSAGE"
        or original_user.get("actor_class") != "USER"
    ):
        raise WebContinuityError(
            "PLAIN_REGENERATE_PARENT_CURRENTNESS_STOP",
            "plain Regenerate target must have one exact USER parent",
            status_code=409,
        )
    if original_user.get("related_source_ref_ids") != []:
        raise WebContinuityError(
            "PLAIN_REGENERATE_PROVENANCE_STOP",
            "plain Regenerate requires predecessor USER provenance with exactly zero SourceRef ids before branch creation",
            status_code=409,
        )
    return {
        "target_assistant_event_id": target_assistant_event_id,
        "original_user_event_id": original_user_event_id,
        "predecessor_job_id": target.get("related_job_id"),
        "related_source_ref_ids": [],
    }


def _prepare_plain_regenerate_and_approve(
    *,
    command_id: str,
    project_id: str,
    chat_id: str,
    expected_chat_revision: int,
    target_assistant_event_id: str,
    streaming: bool = True,
) -> dict[str, Any]:
    """Fresh no-Source USER sibling -> fresh plain Job -> exact approval; no provider call."""
    if not isinstance(command_id, str) or not command_id:
        raise WebContinuityError("INVALID_COMMAND_ID", "command_id must be non-empty")

    predecessor = _plain_regenerate_predecessor_provenance_v1(
        project_id=project_id,
        chat_id=chat_id,
        target_assistant_event_id=target_assistant_event_id,
    )
    branch = _service().regenerate_successful_assistant_as_branch(
        command_id=command_id,
        project_id=project_id,
        chat_id=chat_id,
        expected_chat_revision=expected_chat_revision,
        target_assistant_event_id=target_assistant_event_id,
    )

    try:
        original_user = branch.get("predecessor_user_event")
        new_user = branch.get("event")
        predecessor_assistant = branch.get("predecessor_assistant_event")
        if (
            not isinstance(original_user, dict)
            or original_user.get("event_id") != predecessor["original_user_event_id"]
            or original_user.get("related_source_ref_ids") != []
            or not isinstance(predecessor_assistant, dict)
            or predecessor_assistant.get("event_id") != predecessor["target_assistant_event_id"]
            or not isinstance(new_user, dict)
            or new_user.get("related_source_ref_ids") != []
        ):
            raise WebContinuityError(
                "PLAIN_REGENERATE_POST_BRANCH_PROVENANCE_STOP",
                "plain Regenerate branch provenance changed after the pre-mutation zero-Source check",
                status_code=409,
            )

        formal_command_id = "plainregenformal-" + hashlib.sha256(command_id.encode("utf-8")).hexdigest()[:32]
        prepared = _prepare_plain_formal_approval(
            command_id=formal_command_id,
            project_id=project_id,
            chat_id=chat_id,
            event_id=new_user["event_id"],
            streaming=streaming,
        )
        if prepared.get("job_id") == branch.get("predecessor_job_id"):
            raise WebContinuityError(
                "PLAIN_REGENERATE_PREDECESSOR_JOB_REPLAY_FORBIDDEN",
                "plain Regenerate must create a fresh Job identity",
                status_code=409,
            )
        formal = GeneralChatFormalPrepareService(runtime_home=ROOT, artifact_store=_service().store)
        approved = formal.approve_active_plain_initial_live_attempt_v1(
            project_id=project_id,
            chat_id=chat_id,
            expected_job_id=prepared["job_id"],
            job_authority_event_id=prepared["job_authority_event_id"],
            expected_job_execution_authority_snapshot_id=prepared["job_execution_authority_snapshot_id"],
            decision_request_event_id=prepared["decision_request_event_id"],
        )
        if (
            approved.get("status") != "APPROVED_PLAIN_INITIAL_JOB"
            or approved.get("approval_terminal_current") is not True
            or approved.get("network_called") is not False
            or approved.get("model_called") is not False
            or approved.get("secret_read") is not False
            or approved.get("grant_created") is not False
            or approved.get("attempt_claim_created") is not False
        ):
            raise GeneralChatFormalPrepareError(
                "PLAIN_REGENERATE_APPROVAL_CURRENTNESS",
                "plain Regenerate approval did not preserve the pre-execution ceiling",
            )
    except (WebContinuityError, GeneralChatFormalPrepareError) as exc:
        original_user = branch.get("predecessor_user_event")
        new_user = branch.get("event")
        if not isinstance(new_user, dict) or not isinstance(branch.get("chat"), dict):
            raise WebContinuityError(
                "PLAIN_REGENERATE_RECOVERY_BINDING_STOP",
                "plain Regenerate branch exists but exact recovery binding is unavailable",
                status_code=409,
            ) from exc
        return {
            "result": "STOP_PLAIN_REGENERATE_POST_BRANCH_RECOVERABLE_R001",
            "formal_model_job_executed": False,
            "model_provider_call": False,
            "network_call": False,
            "branch": branch,
            "chat": branch["chat"],
            "event": new_user,
            "recovery": {
                "retry_command_id": command_id,
                "original_expected_chat_revision": expected_chat_revision,
                "target_assistant_event_id": target_assistant_event_id,
                "new_user_event_id": new_user["event_id"],
                "post_branch_chat_revision": branch["chat"]["chat_revision"],
                "post_branch_head_event_id": branch["chat"]["head_event_id"],
                "predecessor_user_event_id": original_user.get("event_id") if isinstance(original_user, dict) else None,
                "reason_code": getattr(exc, "code", type(exc).__name__),
                "message": str(exc),
            },
        }

    formal_result = {
        **prepared,
        **approved,
        "status": "APPROVED_PLAIN_INITIAL_JOB",
        "human_action_trigger": "EXPLICIT_PLAIN_REGENERATE_AND_APPROVE_ONE_GENERATION_CONFIRM",
        "provider_called": False,
        "network_called": False,
        "model_called": False,
        "source_context": None,
        "source_context_sha256": None,
    }
    return {
        "result": "PASS_PLAIN_REGENERATE_PREPARE_R001",
        "formal_model_job_executed": False,
        "model_provider_call": False,
        "network_call": False,
        "branch": branch,
        "chat": prepared["chat"],
        "event": new_user,
        "source_context": None,
        "source_context_sha256": None,
        "formal": formal_result,
        "predecessor_job_id": branch["predecessor_job_id"],
        "fresh_job_id": prepared["job_id"],
    }


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/messages/{assistant_event_id}/regenerate-plain/send-and-approve")
async def web_chat_regenerate_plain_send_and_approve(
    project_id: str,
    chat_id: str,
    assistant_event_id: str,
    request: Request,
) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        prepared = _prepare_plain_regenerate_and_approve(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
            target_assistant_event_id=assistant_event_id,
            streaming=True,
        )
        if prepared.get("result") == "STOP_PLAIN_REGENERATE_POST_BRANCH_RECOVERABLE_R001":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PLAIN_REGENERATE_POST_BRANCH_RECOVERABLE",
                    "message": prepared["recovery"]["message"],
                    "recovery": prepared["recovery"],
                    "chat": prepared["chat"],
                    "event": prepared["event"],
                },
            )
        return prepared
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/messages/{assistant_event_id}/regenerate-source-grounded/prepare")
async def web_chat_regenerate_source_grounded_prepare(
    project_id: str,
    chat_id: str,
    assistant_event_id: str,
    request: Request,
) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    streaming = payload.get("streaming", False)
    if not isinstance(streaming, bool):
        raise HTTPException(status_code=400, detail={"code": "INVALID_STREAMING_MODE", "message": "streaming must be boolean"})
    try:
        prepared = _prepare_source_grounded_regenerate(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
            target_assistant_event_id=assistant_event_id,
            source_ref_id=payload.get("source_ref_id"),
            streaming=streaming,
        )
        if prepared.get("result") == "STOP_REGENERATE_POST_BRANCH_RECOVERABLE_R001":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REGENERATE_POST_BRANCH_RECOVERABLE",
                    "message": prepared["recovery"]["message"],
                    "recovery": prepared["recovery"],
                    "chat": prepared["chat"],
                    "event": prepared["event"],
                },
            )
        return prepared
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/active-head")
async def web_chat_select_active_head(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().select_chat_head(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
            target_head_event_id=payload.get("target_head_event_id"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/source-context/prepare")
async def web_source_context_prepare(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        prepared = _prepare_native_source_context(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=_int_field(payload, "expected_chat_revision"),
            source_ref_id=payload.get("source_ref_id"),
            content=payload.get("content"),
        )
        if prepared.get("result") == "STOP_NATIVE_SOURCE_CONTEXT_POST_APPEND_RECOVERABLE_R002":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SOURCE_CONTEXT_POST_APPEND_RECOVERABLE",
                    "message": prepared["recovery"]["message"],
                    "recovery": prepared["recovery"],
                    "chat": prepared["chat"],
                    "event": prepared["event"],
                },
            )
        return prepared
    except WebContinuityError as exc:
        _raise_http(exc)


def _current_active_context_snapshot(project_id: str, chat_id: str) -> dict[str, Any]:
    projection = _service().get_active_chat_ancestry(project_id=project_id, chat_id=chat_id)
    try:
        return build_active_context_snapshot(
            active_ancestry=projection["active_ancestry"],
            events=projection["events"],
        )
    except Exception as exc:
        raise WebContinuityError("ACTIVE_CONTEXT_INVALID", "current active conversation context is invalid", status_code=409) from exc


def _effective_personal_context_for_project(
    *,
    project_id: str,
    requested_personal_context: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None, str]:
    projection = _service().get_project_context_policy(project_id=project_id)
    context_policy = projection.get("context_policy")
    if context_policy == PROJECT_CONTEXT_POLICY_PROJECT_ONLY:
        return None, None, context_policy
    effective = requested_personal_context
    return (
        effective,
        _canonical_sha256(effective) if effective is not None else None,
        str(context_policy),
    )


def _prepare_source_grounded_formal_approval(
    *,
    command_id: str,
    project_id: str,
    chat_id: str,
    source_context: dict[str, Any],
    source_context_sha256: str,
    streaming: bool = False,
    retry_lineage: dict[str, Any] | None = None,
    include_project_memory: bool = False,
    personal_context: dict[str, Any] | None = None,
    personal_context_sha256: str | None = None,
) -> dict[str, Any]:
    """Compose exact Source Context -> immutable Formal Job -> intake -> approval request only."""
    event_id = source_context.get("initiating_user_event", {}).get("event_id")
    chat, initiating_event, initiating_binding = _find_exact_event(project_id, chat_id, event_id)
    if chat.get("head_event_id") != event_id:
        raise WebContinuityError("STALE_CHAT", "initiating USER_MESSAGE is no longer chat head", status_code=409)
    active_context_snapshot = _current_active_context_snapshot(project_id, chat_id)
    if (
        active_context_snapshot.get("chat_revision") != chat.get("chat_revision")
        or active_context_snapshot.get("head_event_id") != event_id
    ):
        raise WebContinuityError("STALE_CHAT", "active context changed during formal preparation", status_code=409)
    if not isinstance(include_project_memory, bool):
        raise WebContinuityError("INVALID_MEMORY_MODE", "include_project_memory must be boolean", status_code=400)
    try:
        memory_projection = (
            _memory_service().current_context(project_id=project_id)
            if include_project_memory
            else {
                "active_memory_count": 0,
                "project_memory_context": None,
                "project_memory_context_sha256": None,
                "project_memory_state_guard": None,
                "project_memory_state_guard_sha256": None,
                "state_binding": None,
            }
        )
    except ProjectMemoryError as exc:
        raise GeneralChatFormalPrepareError(
            "PROJECT_MEMORY_CONTEXT_CURRENTNESS",
            f"{exc.code}: {exc.message}",
            status_code=exc.status_code,
        ) from exc
    formal = GeneralChatFormalPrepareService(runtime_home=ROOT, artifact_store=_service().store)
    prepared = formal.prepare_job_bundle(
        project_id=project_id,
        chat_id=chat_id,
        initiating_user_event=initiating_event,
        initiating_user_event_binding=initiating_binding,
        accepted_chat_revision=chat["chat_revision"],
        accepted_head_event_id=event_id,
        source_context=source_context,
        source_context_sha256=source_context_sha256,
        active_context_snapshot=active_context_snapshot,
        active_context_snapshot_sha256=active_context_snapshot["active_context_snapshot_sha256"],
        project_memory_context=memory_projection["project_memory_context"],
        project_memory_context_sha256=memory_projection["project_memory_context_sha256"],
        project_memory_state_guard=memory_projection["project_memory_state_guard"],
        project_memory_state_guard_sha256=memory_projection["project_memory_state_guard_sha256"],
        personal_context=personal_context,
        personal_context_sha256=personal_context_sha256,
        streaming=streaming,
        retry_lineage=retry_lineage,
    )
    intake = _service().bind_formal_job_intake(
        command_id=command_id,
        project_id=project_id,
        chat_id=chat_id,
        initiating_user_event_id=event_id,
        expected_chat_revision=chat["chat_revision"],
        expected_head_event_id=event_id,
        job_id=prepared.job_id,
        job_bundle_binding=prepared.job_bundle_binding,
    )
    approval = formal.finalize_approval_request(
        prepared=prepared,
        intake_binding_record=intake["intake_binding_record"],
        intake_binding=intake["intake_binding"],
    )
    return {
        **approval,
        "source_context_sha256": source_context_sha256,
        "project_memory_context_sha256": memory_projection["project_memory_context_sha256"],
        "project_memory_state_guard_sha256": memory_projection["project_memory_state_guard_sha256"],
        "project_memory_state_binding": memory_projection["state_binding"],
        "project_memory_active_count": memory_projection["active_memory_count"],
        "project_memory_ids": (
            [item["memory_id"] for item in memory_projection["project_memory_context"]["items"]]
            if memory_projection["project_memory_context"] is not None
            else []
        ),
        "personal_context_sha256": prepared.personal_context_sha256,
        "personal_context_binding": prepared.personal_context_binding,
        "chat": chat,
        "intake_binding_record": intake["intake_binding_record"],
        "intake_binding": intake["intake_binding"],
    }


def _prepare_plain_formal_approval(
    *,
    command_id: str,
    project_id: str,
    chat_id: str,
    event_id: str,
    streaming: bool = True,
    retry_lineage: dict[str, Any] | None = None,
    include_project_memory: bool = False,
    personal_context: dict[str, Any] | None = None,
    personal_context_sha256: str | None = None,
) -> dict[str, Any]:
    """Compose exact no-Source USER head -> Formal Job -> intake -> approval request only."""
    if not isinstance(command_id, str) or not command_id:
        raise WebContinuityError("INVALID_COMMAND_ID", "command_id must be non-empty", status_code=400)
    chat, initiating_event, initiating_binding = _find_exact_event(project_id, chat_id, event_id)
    if chat.get("head_event_id") != event_id:
        raise WebContinuityError("STALE_CHAT", "initiating USER_MESSAGE is no longer chat head", status_code=409)
    active_context_snapshot = _current_active_context_snapshot(project_id, chat_id)
    if (
        active_context_snapshot.get("chat_revision") != chat.get("chat_revision")
        or active_context_snapshot.get("head_event_id") != event_id
    ):
        raise WebContinuityError("STALE_CHAT", "active context changed during plain formal preparation", status_code=409)
    if not isinstance(include_project_memory, bool):
        raise WebContinuityError("INVALID_MEMORY_MODE", "include_project_memory must be boolean", status_code=400)
    try:
        memory_projection = (
            _memory_service().current_context(project_id=project_id)
            if include_project_memory
            else {
                "active_memory_count": 0,
                "project_memory_context": None,
                "project_memory_context_sha256": None,
                "project_memory_state_guard": None,
                "project_memory_state_guard_sha256": None,
                "state_binding": None,
            }
        )
    except ProjectMemoryError as exc:
        raise GeneralChatFormalPrepareError(
            "PROJECT_MEMORY_CONTEXT_CURRENTNESS",
            f"{exc.code}: {exc.message}",
            status_code=exc.status_code,
        ) from exc
    formal = GeneralChatFormalPrepareService(runtime_home=ROOT, artifact_store=_service().store)
    prepared = formal.prepare_job_bundle(
        project_id=project_id,
        chat_id=chat_id,
        initiating_user_event=initiating_event,
        initiating_user_event_binding=initiating_binding,
        accepted_chat_revision=chat["chat_revision"],
        accepted_head_event_id=event_id,
        source_context=None,
        source_context_sha256=None,
        active_context_snapshot=active_context_snapshot,
        active_context_snapshot_sha256=active_context_snapshot["active_context_snapshot_sha256"],
        project_memory_context=memory_projection["project_memory_context"],
        project_memory_context_sha256=memory_projection["project_memory_context_sha256"],
        project_memory_state_guard=memory_projection["project_memory_state_guard"],
        project_memory_state_guard_sha256=memory_projection["project_memory_state_guard_sha256"],
        personal_context=personal_context,
        personal_context_sha256=personal_context_sha256,
        streaming=streaming,
        retry_lineage=retry_lineage,
    )
    intake_command_id = "plain-formal-intake-" + _canonical_sha256({
        "plain_send_command_id": command_id,
        "project_id": project_id,
        "chat_id": chat_id,
        "initiating_user_event_id": event_id,
        "job_id": prepared.job_id,
    })
    intake = _service().bind_formal_job_intake(
        command_id=intake_command_id,
        project_id=project_id,
        chat_id=chat_id,
        initiating_user_event_id=event_id,
        expected_chat_revision=chat["chat_revision"],
        expected_head_event_id=event_id,
        job_id=prepared.job_id,
        job_bundle_binding=prepared.job_bundle_binding,
    )
    approval = formal.finalize_approval_request(
        prepared=prepared,
        intake_binding_record=intake["intake_binding_record"],
        intake_binding=intake["intake_binding"],
    )
    return {
        **approval,
        "source_context": None,
        "source_context_sha256": None,
        "project_memory_context_sha256": memory_projection["project_memory_context_sha256"],
        "project_memory_state_guard_sha256": memory_projection["project_memory_state_guard_sha256"],
        "project_memory_state_binding": memory_projection["state_binding"],
        "project_memory_active_count": memory_projection["active_memory_count"],
        "project_memory_ids": (
            [item["memory_id"] for item in memory_projection["project_memory_context"]["items"]]
            if memory_projection["project_memory_context"] is not None
            else []
        ),
        "personal_context_sha256": prepared.personal_context_sha256,
        "personal_context_binding": prepared.personal_context_binding,
        "chat": chat,
        "initiating_user_event": initiating_event,
        "intake_binding_record": intake["intake_binding_record"],
        "intake_binding": intake["intake_binding"],
    }


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/plain/send-and-approve")
async def web_plain_formal_send_and_approve(
    project_id: str,
    chat_id: str,
    request: Request,
) -> dict[str, Any]:
    """Persist/replay one plain USER turn and consume its explicit one-attempt approval click.

    The endpoint itself performs no credential read, provider/model call, network
    request, Grant creation, or attempt claim.  Provider execution remains a
    separate streaming endpoint with JIT approval/currentness checks.
    """
    payload = _require_dict(await request.json())
    command_id = payload.get("command_id")
    content = payload.get("content")
    expected_chat_revision = _int_field(payload, "expected_chat_revision")
    requested_personal_context = payload.get("personal_context")
    if not isinstance(command_id, str) or not command_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_COMMAND_ID", "message": "command_id must be non-empty"},
        )
    if not isinstance(content, str) or not content:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_CONTENT", "message": "plain Chat content must be non-empty"},
        )

    formal = GeneralChatFormalPrepareService(runtime_home=ROOT, artifact_store=_service().store)
    try:
        personal_context, personal_context_sha256, project_context_policy = (
            _effective_personal_context_for_project(
                project_id=project_id,
                requested_personal_context=requested_personal_context,
            )
        )
        validate_non_authority_personal_context_snapshot(
            personal_context=personal_context,
            personal_context_sha256=personal_context_sha256,
        )
        appended = _service().append_user_message(
            command_id=command_id,
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=expected_chat_revision,
            content=content,
            related_source_ref_ids=[],
        )
        event = appended.get("event")
        chat = appended.get("chat")
        if (
            not isinstance(event, dict)
            or event.get("event_type") != "USER_MESSAGE"
            or event.get("actor_class") != "USER"
            or event.get("related_source_ref_ids") != []
            or not isinstance(chat, dict)
            or chat.get("head_event_id") != event.get("event_id")
        ):
            raise WebContinuityError(
                "PLAIN_USER_EVENT_CURRENTNESS",
                "plain USER event did not commit/replay as exact no-Source chat head",
                status_code=409,
            )

        prepared = _prepare_plain_formal_approval(
            command_id=command_id,
            project_id=project_id,
            chat_id=chat_id,
            event_id=event["event_id"],
            streaming=True,
            include_project_memory=True,
            personal_context=personal_context,
            personal_context_sha256=personal_context_sha256,
        )
        if prepared.get("chat", {}).get("chat_revision") != chat.get("chat_revision"):
            raise WebContinuityError(
                "PLAIN_CHAT_CHANGED_BEFORE_APPROVAL",
                "plain Chat changed after exact USER turn; approval not committed",
                status_code=409,
            )
        approved = formal.approve_active_plain_initial_live_attempt_v1(
            project_id=project_id,
            chat_id=chat_id,
            expected_job_id=prepared["job_id"],
            job_authority_event_id=prepared["job_authority_event_id"],
            expected_job_execution_authority_snapshot_id=prepared[
                "job_execution_authority_snapshot_id"
            ],
            decision_request_event_id=prepared["decision_request_event_id"],
        )
        if (
            approved.get("status") != "APPROVED_PLAIN_INITIAL_JOB"
            or approved.get("approval_terminal_current") is not True
            or approved.get("network_called") is not False
            or approved.get("model_called") is not False
            or approved.get("secret_read") is not False
            or approved.get("grant_created") is not False
            or approved.get("attempt_claim_created") is not False
        ):
            raise GeneralChatFormalPrepareError(
                "PLAIN_INITIAL_APPROVAL_CURRENTNESS",
                "plain initial approval result does not preserve pre-execution ceiling",
            )
        return {
            **prepared,
            **approved,
            "status": "APPROVED_PLAIN_INITIAL_JOB",
            "project_context_policy": project_context_policy,
            "chat": chat,
            "event": event,
            "operation": appended.get("operation"),
            "operation_binding": appended.get("operation_binding"),
            "human_action_trigger": "EXPLICIT_SEND_AND_APPROVE_ONE_GENERATION_CLICK",
            "provider_called": False,
            "network_called": False,
            "model_called": False,
            "source_context": None,
            "source_context_sha256": None,
        }
    except WebContinuityError as exc:
        _raise_http(exc)
    except GeneralChatFormalPrepareError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc



@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/source/send-and-approve")
async def web_source_formal_send_and_approve(
    project_id: str,
    chat_id: str,
    request: Request,
) -> dict[str, Any]:
    """Persist/replay one source USER turn and consume its explicit one-attempt approval click.

    This endpoint stops after the existing HumanDecision terminal owner commits/replays
    APPROVED.  Provider execution remains the separate `/formal-model/stream` request.
    """
    payload = _require_dict(await request.json())
    command_id = payload.get("command_id")
    content = payload.get("content")
    source_ref_id = payload.get("source_ref_id")
    expected_chat_revision = _int_field(payload, "expected_chat_revision")
    requested_personal_context = payload.get("personal_context")
    if not isinstance(command_id, str) or not command_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_COMMAND_ID", "message": "command_id must be non-empty"},
        )
    if not isinstance(content, str) or not content:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_CONTENT", "message": "source Chat content must be non-empty"},
        )
    if not isinstance(source_ref_id, str) or not source_ref_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_SOURCE_REF", "message": "source_ref_id must be non-empty"},
        )

    formal = GeneralChatFormalPrepareService(runtime_home=ROOT, artifact_store=_service().store)
    try:
        personal_context, personal_context_sha256, project_context_policy = (
            _effective_personal_context_for_project(
                project_id=project_id,
                requested_personal_context=requested_personal_context,
            )
        )
        validate_non_authority_personal_context_snapshot(
            personal_context=personal_context,
            personal_context_sha256=personal_context_sha256,
        )
        source_prepared = _prepare_native_source_context(
            command_id=command_id,
            project_id=project_id,
            chat_id=chat_id,
            expected_chat_revision=expected_chat_revision,
            source_ref_id=source_ref_id,
            content=content,
        )
        if source_prepared.get("result") == "STOP_NATIVE_SOURCE_CONTEXT_POST_APPEND_RECOVERABLE_R002":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SOURCE_CONTEXT_POST_APPEND_RECOVERABLE",
                    "message": source_prepared["recovery"]["message"],
                    "recovery": source_prepared["recovery"],
                    "chat": source_prepared["chat"],
                    "event": source_prepared["event"],
                },
            )
        source_context = source_prepared.get("source_context")
        source_context_sha256 = source_prepared.get("source_context_sha256")
        if (
            source_prepared.get("result") != "PASS_NATIVE_SOURCE_CONTEXT_PREPARE_R001"
            or not isinstance(source_context, dict)
            or not isinstance(source_context_sha256, str)
            or source_context.get("source_ref_id") != source_ref_id
            or source_prepared.get("model_provider_call") is not False
            or source_prepared.get("network_call") is not False
        ):
            raise GeneralChatFormalPrepareError(
                "SOURCE_CONTEXT_CURRENTNESS",
                "source context preparation did not preserve the pre-execution ceiling",
            )

        formal_command_id = "source-formal-" + _canonical_sha256({
            "source_send_command_id": command_id,
            "project_id": project_id,
            "chat_id": chat_id,
            "source_ref_id": source_ref_id,
            "source_context_sha256": source_context_sha256,
        })
        prepared = _prepare_source_grounded_formal_approval(
            command_id=formal_command_id,
            project_id=project_id,
            chat_id=chat_id,
            source_context=source_context,
            source_context_sha256=source_context_sha256,
            streaming=True,
            include_project_memory=True,
            personal_context=personal_context,
            personal_context_sha256=personal_context_sha256,
        )
        approved = formal.approve_active_source_initial_live_attempt_v1(
            project_id=project_id,
            chat_id=chat_id,
            expected_job_id=prepared["job_id"],
            job_authority_event_id=prepared["job_authority_event_id"],
            expected_job_execution_authority_snapshot_id=prepared[
                "job_execution_authority_snapshot_id"
            ],
            decision_request_event_id=prepared["decision_request_event_id"],
        )
        event = source_prepared.get("event")
        chat = source_prepared.get("chat")
        if (
            approved.get("status") != "APPROVED_SOURCE_INITIAL_JOB"
            or approved.get("approval_terminal_current") is not True
            or approved.get("source_ref_id") != source_ref_id
            or approved.get("source_context_sha256") != source_context_sha256
            or approved.get("network_called") is not False
            or approved.get("model_called") is not False
            or approved.get("secret_read") is not False
            or approved.get("grant_created") is not False
            or approved.get("attempt_claim_created") is not False
            or not isinstance(event, dict)
            or event.get("event_type") != "USER_MESSAGE"
            or event.get("actor_class") != "USER"
            or event.get("content") != content
            or event.get("related_source_ref_ids") != [source_ref_id]
            or not isinstance(chat, dict)
            or chat.get("head_event_id") != event.get("event_id")
        ):
            raise GeneralChatFormalPrepareError(
                "SOURCE_INITIAL_APPROVAL_CURRENTNESS",
                "source initial approval result differs from exact explicit Send scope",
            )
        return {
            **prepared,
            **approved,
            "status": "APPROVED_SOURCE_INITIAL_JOB",
            "project_context_policy": project_context_policy,
            "chat": chat,
            "event": event,
            "operation": source_prepared.get("operation"),
            "operation_binding": source_prepared.get("operation_binding"),
            "source_context": source_context,
            "source_context_sha256": source_context_sha256,
            "human_action_trigger": "EXPLICIT_SOURCE_SEND_AND_APPROVE_ONE_GENERATION_CLICK",
            "provider_called": False,
            "network_called": False,
            "model_called": False,
        }
    except WebContinuityError as exc:
        _raise_http(exc)
    except GeneralChatFormalPrepareError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/prepare")
async def web_formal_model_prepare(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    source_context = payload.get("source_context")
    source_context_sha256 = payload.get("source_context_sha256")
    streaming = payload.get("streaming", False)
    if not isinstance(source_context, dict):
        raise HTTPException(status_code=400, detail={"code": "INVALID_SOURCE_CONTEXT", "message": "source_context object required"})
    if not isinstance(source_context_sha256, str):
        raise HTTPException(status_code=400, detail={"code": "INVALID_SOURCE_CONTEXT", "message": "source_context_sha256 required"})
    if not isinstance(streaming, bool):
        raise HTTPException(status_code=400, detail={"code": "INVALID_STREAMING_MODE", "message": "streaming must be boolean"})
    try:
        return _prepare_source_grounded_formal_approval(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            source_context=source_context,
            source_context_sha256=source_context_sha256,
            streaming=streaming,
        )
    except (WebContinuityError, GeneralChatFormalPrepareError) as exc:
        if isinstance(exc, WebContinuityError):
            _raise_http(exc)
        raise HTTPException(
            status_code=getattr(exc, "status_code", 409),
            detail={"code": getattr(exc, "code", "FORMAL_PREPARE_REJECTED"), "message": str(exc)},
        ) from exc


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/retry-after-confirmed-cancel")
async def web_formal_model_retry_after_confirmed_cancel(
    project_id: str,
    chat_id: str,
    request: Request,
) -> dict[str, Any]:
    """Fresh Retry from one exact consumed-cancel predecessor; no provider execution here."""
    payload = _require_dict(await request.json())
    source_context = payload.get("source_context")
    source_context_sha256 = payload.get("source_context_sha256")
    initiating_user_event_id = payload.get("initiating_user_event_id")
    predecessor_job_id = payload.get("predecessor_job_id")
    predecessor_job_bundle_binding = payload.get("predecessor_job_bundle_binding")
    predecessor_intake_binding = payload.get("predecessor_web_formal_job_intake_binding")
    cancellation_binding = payload.get("predecessor_cancellation_outcome_binding")

    source_mode = isinstance(source_context, dict)
    plain_mode = source_context is None and source_context_sha256 is None
    if source_mode:
        if not isinstance(source_context_sha256, str):
            raise HTTPException(status_code=400, detail={"code":"INVALID_RETRY_SOURCE_CONTEXT","message":"source_context_sha256 required"})
        event_id = source_context.get("initiating_user_event", {}).get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise HTTPException(status_code=400, detail={"code":"INVALID_RETRY_SOURCE_CONTEXT","message":"initiating USER_MESSAGE required"})
        active_context_snapshot_sha256 = None
    elif plain_mode:
        if not isinstance(initiating_user_event_id, str) or not initiating_user_event_id:
            raise HTTPException(status_code=400, detail={"code":"INVALID_RETRY_PLAIN_CONTEXT","message":"plain initiating_user_event_id required"})
        current_chat, current_event, _binding = _find_exact_event(project_id, chat_id, initiating_user_event_id)
        if (
            current_chat.get("head_event_id") != initiating_user_event_id
            or current_event.get("event_type") != "USER_MESSAGE"
            or current_event.get("actor_class") != "USER"
            or current_event.get("related_source_ref_ids") != []
        ):
            raise HTTPException(status_code=409, detail={"code":"RETRY_PLAIN_CONTEXT_CURRENTNESS","message":"plain Retry requires exact current zero-Source USER head"})
        active_context_snapshot = _current_active_context_snapshot(project_id, chat_id)
        if (
            active_context_snapshot.get("head_event_id") != initiating_user_event_id
            or active_context_snapshot.get("chat_revision") != current_chat.get("chat_revision")
        ):
            raise HTTPException(status_code=409, detail={"code":"RETRY_PLAIN_CONTEXT_CURRENTNESS","message":"plain Retry active context differs from current USER head"})
        event_id = initiating_user_event_id
        active_context_snapshot_sha256 = active_context_snapshot["active_context_snapshot_sha256"]
    else:
        raise HTTPException(status_code=400, detail={"code":"INVALID_RETRY_CONTEXT_MODE","message":"Retry requires exact Source or exact plain context"})

    formal = GeneralChatFormalPrepareService(runtime_home=ROOT, artifact_store=_service().store)
    try:
        retry_lineage = formal.validate_retry_after_confirmed_cancel_lineage_v1(
            project_id=project_id,
            chat_id=chat_id,
            initiating_user_event_id=event_id,
            source_context_sha256=(source_context_sha256 if source_mode else None),
            active_context_snapshot_sha256=(active_context_snapshot_sha256 if plain_mode else None),
            predecessor_job_id=predecessor_job_id,
            predecessor_job_bundle_binding=predecessor_job_bundle_binding,
            predecessor_web_formal_job_intake_binding=predecessor_intake_binding,
            predecessor_cancellation_outcome_binding=cancellation_binding,
        )
        retry_lineage_sha256 = _canonical_sha256(retry_lineage)
        if source_mode:
            result = _prepare_source_grounded_formal_approval(
                command_id="p1s4-retry:" + retry_lineage_sha256,
                project_id=project_id, chat_id=chat_id,
                source_context=source_context, source_context_sha256=source_context_sha256,
                streaming=True, retry_lineage=retry_lineage,
            )
        else:
            result = _prepare_plain_formal_approval(
                command_id="p1plain-retry:" + retry_lineage_sha256,
                project_id=project_id, chat_id=chat_id, event_id=event_id,
                streaming=True, retry_lineage=retry_lineage,
            )
        if result.get("job_id") == predecessor_job_id:
            raise GeneralChatFormalPrepareError("RETRY_FRESH_JOB_REQUIRED","Retry must create fresh Job identity instead of replaying predecessor Job")
        current_chat, _event, _binding = _find_exact_event(project_id, chat_id, event_id)
        if current_chat.get("head_event_id") != event_id or current_chat.get("chat_revision") != result.get("chat", {}).get("chat_revision"):
            raise GeneralChatFormalPrepareError("RETRY_CHAT_CHANGED_BEFORE_APPROVAL","chat changed after fresh Retry Job preparation; approval not committed")
        approved = formal.approve_active_initial_retry_live_attempt_v1(
            project_id=project_id, chat_id=chat_id, expected_job_id=result["job_id"],
            job_authority_event_id=result["job_authority_event_id"],
            expected_job_execution_authority_snapshot_id=result["job_execution_authority_snapshot_id"],
            decision_request_event_id=result["decision_request_event_id"],
        )
        return {**result, **approved, "status":"APPROVED_FRESH_RETRY_JOB",
            "retry_context_mode":("SOURCE" if source_mode else "PLAIN"),
            "retry_lineage_sha256":retry_lineage_sha256,
            "human_action_trigger":"EXPLICIT_RETRY_AND_APPROVE_ONE_GENERATION_CLICK",
            "predecessor_job_id":predecessor_job_id,
            "predecessor_claim_replayed":False,"predecessor_claim_refunded":False,
            "provider_called":False,"model_called":False,"network_called":False}
    except (WebContinuityError, GeneralChatFormalPrepareError) as exc:
        if isinstance(exc, WebContinuityError): _raise_http(exc)
        raise HTTPException(status_code=getattr(exc,"status_code",409),detail={"code":getattr(exc,"code","FORMAL_RETRY_REJECTED"),"message":str(exc)}) from exc


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/controlled-reopen/runtime-migration")
async def web_controlled_reopen_runtime_migration(
    project_id: str,
    chat_id: str,
    request: Request,
) -> dict[str, Any]:
    """Fresh explicit product interaction for one exact DRE-pending Runtime migration."""
    payload = _require_dict(await request.json())
    command_id = payload.get("command_id")
    if not isinstance(command_id, str) or not command_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_COMMAND_ID", "message": "command_id must be non-empty"},
        )
    formal = GeneralChatFormalPrepareService(
        runtime_home=ROOT,
        artifact_store=_service().store,
    )
    try:
        result = formal.consume_or_replay_dre_pending_runtime_migration_v1(
            project_id=project_id,
            chat_id=chat_id,
            decision_request_event_id=payload.get("decision_request_event_id"),
            expected_job_id=payload.get("job_id"),
            action_code=payload.get("action_code"),
        )
        return {
            **result,
            "command_id": command_id,
            "human_action_trigger": "FRESH_EXPLICIT_CONTROLLED_REOPEN_PRODUCT_INTERACTION",
        }
    except GeneralChatFormalPrepareError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/successor/approval-request")
async def web_successor_formal_approval_request(
    project_id: str,
    chat_id: str,
    request: Request,
) -> dict[str, Any]:
    """Issue/replay the one live-attempt approval request for an exact active controlled successor."""
    payload = _require_dict(await request.json())
    command_id = payload.get("command_id")
    if not isinstance(command_id, str) or not command_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_COMMAND_ID", "message": "command_id must be non-empty"},
        )
    formal = GeneralChatFormalPrepareService(
        runtime_home=ROOT,
        artifact_store=_service().store,
    )
    try:
        result = formal.issue_or_replay_active_successor_live_approval_request_v1(
            project_id=project_id,
            chat_id=chat_id,
            expected_job_id=payload.get("job_id"),
            successor_job_authority_event_id=payload.get(
                "successor_job_authority_event_id"
            ),
            expected_successor_job_execution_authority_snapshot_id=payload.get(
                "successor_job_execution_authority_snapshot_id"
            ),
        )
        return {
            **result,
            "command_id": command_id,
        }
    except GeneralChatFormalPrepareError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc



@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/successor/approve")
async def web_successor_formal_approve(
    project_id: str,
    chat_id: str,
    request: Request,
) -> dict[str, Any]:
    """Consume one fresh explicit APPROVE interaction for an exact active successor DRE."""
    payload = _require_dict(await request.json())
    command_id = payload.get("command_id")
    if not isinstance(command_id, str) or not command_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_COMMAND_ID", "message": "command_id must be non-empty"},
        )
    formal = GeneralChatFormalPrepareService(
        runtime_home=ROOT,
        artifact_store=_service().store,
    )
    try:
        result = formal.approve_active_successor_live_attempt_v1(
            project_id=project_id,
            chat_id=chat_id,
            expected_job_id=payload.get("job_id"),
            successor_job_authority_event_id=payload.get(
                "successor_job_authority_event_id"
            ),
            expected_successor_job_execution_authority_snapshot_id=payload.get(
                "successor_job_execution_authority_snapshot_id"
            ),
            decision_request_event_id=payload.get("decision_request_event_id"),
        )
        return {
            **result,
            "command_id": command_id,
            "human_action_trigger": "FRESH_EXPLICIT_SUCCESSOR_APPROVE_PRODUCT_INTERACTION",
        }
    except GeneralChatFormalPrepareError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/stream-approval-status")
async def web_formal_model_stream_approval_status(
    project_id: str,
    chat_id: str,
    request: Request,
) -> dict[str, Any]:
    """Read exact Runtime approval-terminal status without consuming execution authority."""
    payload = _require_dict(await request.json())
    command_id = payload.get("command_id")
    job_id = payload.get("job_id")
    decision_request_event_id = payload.get("decision_request_event_id")
    for value, label in (
        (command_id, "command_id"),
        (job_id, "job_id"),
        (decision_request_event_id, "decision_request_event_id"),
    ):
        if not isinstance(value, str) or not value:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_INPUT", "message": f"{label} must be non-empty"},
            )
    formal = GeneralChatFormalPrepareService(
        runtime_home=ROOT,
        artifact_store=_service().store,
    )
    try:
        result = formal.inspect_streaming_approval_terminal_v1(
            project_id=project_id,
            chat_id=chat_id,
            expected_job_id=job_id,
            decision_request_event_id=decision_request_event_id,
        )
        return {**result, "command_id": command_id}
    except GeneralChatFormalPrepareError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/stream")
async def web_formal_model_stream(project_id: str, chat_id: str, request: Request):
    """Stream one already-approved Runtime-owned formal attempt as provisional SSE deltas."""
    payload = _require_dict(await request.json())
    command_id = payload.get("command_id")
    job_id = payload.get("job_id")
    decision_request_event_id = payload.get("decision_request_event_id")
    project_context_policy = payload.get("project_context_policy")
    for value, label in (
        (command_id, "command_id"),
        (job_id, "job_id"),
        (decision_request_event_id, "decision_request_event_id"),
    ):
        if not isinstance(value, str) or not value:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_INPUT", "message": f"{label} must be non-empty"},
            )
    if project_context_policy not in PROJECT_CONTEXT_POLICIES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_PROJECT_CONTEXT_POLICY",
                "message": "project_context_policy must be one supported exact value",
            },
        )
    try:
        current_context_policy = _service().get_project_context_policy(project_id=project_id)
    except WebContinuityError as exc:
        _raise_http(exc)
    if current_context_policy.get("context_policy") != project_context_policy:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PROJECT_CONTEXT_POLICY_STALE",
                "message": "Project context policy changed after approval; start a new turn",
            },
        )

    execution_instance_id = _p1_s3_execution_instance_id(
        project_id=project_id,
        chat_id=chat_id,
        job_id=job_id,
        decision_request_event_id=decision_request_event_id,
        command_id=command_id,
    )
    try:
        stop_control = _register_p1_s3_execution_under_c5_fence(
            project_id=project_id,
            chat_id=chat_id,
            job_id=job_id,
            decision_request_event_id=decision_request_event_id,
            execution_instance_id=execution_instance_id,
        )
    except P1S3StopControlError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc

    delta_events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(
        maxsize=P1_S2_STREAM_QUEUE_MAX
    )
    terminal_events: queue.Queue[tuple[str, dict[str, Any]]] = queue.Queue(maxsize=1)
    presentation_closed = threading.Event()
    worker_done = threading.Event()

    def emit_event(event: str, data: dict[str, Any]) -> bool:
        if event in {"final", "error", "cancelled"}:
            try:
                terminal_events.put_nowait((event, data))
                return True
            except queue.Full:
                return False
        if event != "delta":
            return False
        if presentation_closed.is_set():
            return False
        try:
            delta_events.put_nowait((event, data))
            return True
        except queue.Full:
            # Lossy provisional presentation may close, but terminal delivery has its own slot.
            presentation_closed.set()
            return False

    def worker() -> None:
        formal = GeneralChatFormalPrepareService(
            runtime_home=ROOT,
            artifact_store=_service().store,
            )
        try:
            _p1_s2_stream_worker(
                formal_service=formal,
                project_formal_result=_service().project_formal_result,
                command_id=command_id,
                project_id=project_id,
                chat_id=chat_id,
                job_id=job_id,
                decision_request_event_id=decision_request_event_id,
                emit_event=emit_event,
                stop_control=stop_control,
            )
        except GeneralChatFormalPrepareError as exc:
            emit_event(
                "error",
                {
                    "code": exc.code,
                    "message": "Streaming attempt stopped at the Runtime formal boundary.",
                    "retry_allowed": False,
                },
            )
        except WebContinuityError as exc:
            emit_event(
                "error",
                {
                    "code": exc.code,
                    "message": "Formal result committed but Web projection was not accepted.",
                    "retry_allowed": False,
                },
            )
        except BaseException:
            emit_event(
                "error",
                {
                    "code": "STREAMING_ATTEMPT_FAILED",
                    "message": "Streaming attempt failed; inspect Runtime-owned receipts.",
                    "retry_allowed": False,
                },
            )
        finally:
            worker_done.set()
            _P1_S3_STOP_REGISTRY.release(
                project_id=project_id,
                chat_id=chat_id,
                job_id=job_id,
                decision_request_event_id=decision_request_event_id,
                execution_instance_id=execution_instance_id,
            )

    threading.Thread(target=worker, name="ur-p1-s3-stream", daemon=True).start()

    async def event_iterator():
        try:
            yield _p1_s2_sse_frame(
                "open",
                {
                    "project_id": project_id,
                    "chat_id": chat_id,
                    "job_id": job_id,
                    "decision_request_event_id": decision_request_event_id,
                    "execution_instance_id": execution_instance_id,
                    "authority": "PROVISIONAL_PRESENTATION_ONLY",
                },
            )
            while True:
                if await request.is_disconnected():
                    presentation_closed.set()
                    break
                try:
                    item = delta_events.get_nowait()
                except queue.Empty:
                    item = None
                if item is not None:
                    event, data = item
                    yield _p1_s2_sse_frame(event, data)
                    continue
                try:
                    terminal = terminal_events.get_nowait()
                except queue.Empty:
                    terminal = None
                if terminal is not None:
                    event, data = terminal
                    yield _p1_s2_sse_frame(event, data)
                    break
                if worker_done.is_set():
                    break
                await asyncio.sleep(0.01)
        finally:
            # Disconnect/backpressure closes only the provisional sink; provider attempt continues.
            presentation_closed.set()

    return StreamingResponse(
        event_iterator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-model/stop")
async def web_formal_model_stop(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    """Request STOP for one exact active process-local streaming execution; never persists Authority."""
    payload = _require_dict(await request.json())
    job_id = payload.get("job_id")
    decision_request_event_id = payload.get("decision_request_event_id")
    execution_instance_id = payload.get("execution_instance_id")
    for value, label in (
        (job_id, "job_id"),
        (decision_request_event_id, "decision_request_event_id"),
        (execution_instance_id, "execution_instance_id"),
    ):
        if not isinstance(value, str) or not value:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_INPUT", "message": f"{label} must be non-empty"},
            )
    control = _P1_S3_STOP_REGISTRY.lookup(
        project_id=project_id,
        chat_id=chat_id,
        job_id=job_id,
        decision_request_event_id=decision_request_event_id,
        execution_instance_id=execution_instance_id,
    )
    if control is None:
        return {
            "status": "NO_ACTIVE_EXECUTION",
            "stop_requested": False,
            "cancellation_confirmed": False,
        }
    return control.request_stop(execution_instance_id=execution_instance_id)


@app.post("/api/web/projects/{project_id}/chats/{chat_id}/formal-results/project")
async def web_formal_result_project(project_id: str, chat_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().project_formal_result(
            command_id=payload.get("command_id"),
            project_id=project_id,
            chat_id=chat_id,
            intake_binding=payload.get("intake_binding"),
            formal_result_commit_binding=payload.get("formal_result_commit_binding"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/sources/text")
async def web_text_ingest(
    project_id: str,
    request: Request,
    command_id: str,
    filename: str,
    expected_project_revision: int,
    chat_id: str | None = None,
) -> dict[str, Any]:
    raw = await request.body()
    try:
        return _service().ingest_text_source(
            command_id=command_id,
            project_id=project_id,
            expected_project_revision=expected_project_revision,
            filename=filename,
            raw_bytes=raw,
            chat_id=chat_id,
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/sources/chat-output")
async def web_chat_output_source_save(project_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    content = payload.get("content")
    if not isinstance(content, str) or not content:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_INPUT", "message": "content must be non-empty text"},
        )
    try:
        return _service().save_chat_output_source(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=payload.get("expected_project_revision"),
            filename=payload.get("filename"),
            raw_bytes=content.encode("utf-8"),
            provenance=payload.get("provenance"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/sources/{source_ref_id}/remove")
async def web_project_source_remove(
    project_id: str,
    source_ref_id: str,
    request: Request,
) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().remove_source_from_project(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=payload.get("expected_project_revision"),
            source_ref_id=source_ref_id,
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.get("/api/web/projects/{project_id}/source-retirement-candidates")
async def web_project_source_retirement_candidates(project_id: str) -> dict[str, Any]:
    try:
        return _service().read_project_source_retirement_candidates(project_id=project_id)
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/sources/{source_ref_id}/retire-content")
async def web_project_source_content_retire(
    project_id: str,
    source_ref_id: str,
    request: Request,
) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().retire_project_source_content(
            command_id=payload.get("command_id"),
            project_id=project_id,
            expected_project_revision=payload.get("expected_project_revision"),
            source_ref_id=source_ref_id,
            owner_id=payload.get("owner_id"),
            external_ref_counts=payload.get("external_ref_counts"),
            protected_asset_census_sha256=payload.get("protected_asset_census_sha256"),
            binding_class=payload.get("binding_class"),
            native_file_ids=payload.get("native_file_ids"),
            source_ref_ids=payload.get("source_ref_ids"),
            binding_evidence_sha256=payload.get("binding_evidence_sha256"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)
@app.post("/api/web/projects/{project_id}/sources/document")
async def web_document_ingest(
    project_id: str,
    request: Request,
    command_id: str,
    filename: str,
    expected_project_revision: int,
    chat_id: str | None = None,
) -> dict[str, Any]:
    raw = await request.body()
    try:
        return _ingest_document_upload_bytes(
            service=_service(),
            command_id=command_id,
            project_id=project_id,
            expected_project_revision=expected_project_revision,
            filename=filename,
            raw_bytes=raw,
            chat_id=chat_id,
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/sources/document-bundle")
async def web_native_document_bundle_ingest(
    project_id: str,
    request: Request,
    command_id: str,
    filename: str,
    expected_project_revision: int,
) -> dict[str, Any]:
    raw = await request.body()
    try:
        return _ingest_prebuilt_document_bundle_bytes(
            service=_service(),
            command_id=command_id,
            project_id=project_id,
            expected_project_revision=expected_project_revision,
            filename=filename,
            bundle_bytes=raw,
        )
    except WebContinuityError as exc:
        _raise_http(exc)

@app.post("/api/web/projects/{project_id}/sources/{source_ref_id}/verify")
async def web_text_verify(project_id: str, source_ref_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return _service().verify_text_source(
            command_id=payload.get("command_id"),
            project_id=project_id,
            source_ref_id=source_ref_id,
            chat_id=payload.get("chat_id"),
        )
    except WebContinuityError as exc:
        _raise_http(exc)


@app.post("/api/web/projects/{project_id}/semantic-search")
async def web_project_semantic_search(project_id: str, request: Request) -> dict[str, Any]:
    payload = _require_dict(await request.json())
    try:
        return ProjectSemanticSearchAdapter(
            runtime_root=ROOT,
            service=_service(),
            sidecar_root=_semantic_search_sidecar_root(),
        ).search(
            project_id=project_id,
            query=payload.get("query"),
            top_k=payload.get("top_k", 3),
        )
    except ProjectSemanticSearchError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@app.get("/assets/vendor/markdown-it-14.3.1.min.js", response_class=Response)
def markdown_it_vendor_asset() -> Response:
    try:
        payload = _MARKDOWN_IT_VENDOR_PATH.read_bytes()
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "MARKDOWN_RENDERER_ASSET_MISSING"},
        ) from exc
    if hashlib.sha256(payload).hexdigest() != _MARKDOWN_IT_VENDOR_SHA256:
        raise HTTPException(
            status_code=500,
            detail={"code": "MARKDOWN_RENDERER_ASSET_SHA_MISMATCH"},
        )
    return Response(
        content=payload,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local Universal Runtime</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ font-family: system-ui, sans-serif; margin:0; background:#f5f5f5; color:#222; }}
main {{ max-width:1100px; margin:0 auto; padding:24px; }}
header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; }}
.grid {{ display:grid; grid-template-columns:320px 1fr; gap:16px; }}
.card {{ background:white; border:1px solid #ddd; border-radius:12px; padding:16px; margin-bottom:16px; }}
input, textarea, button {{ font:inherit; }}
input, textarea {{ width:100%; box-sizing:border-box; padding:9px; margin:5px 0 10px; border:1px solid #bbb; border-radius:8px; background:white; color:#222; }}
textarea {{ min-height:90px; }}
button {{ padding:9px 12px; border:1px solid #aaa; border-radius:8px; cursor:pointer; background:#fff; }}
button.primary {{ background:#111; color:white; }}
button + button {{ margin-left:6px; }}
.small {{ font-size:12px; color:#666; }}
.item {{ border-top:1px solid #eee; padding:10px 0; }}
.project-toolbar {{ display:grid; grid-template-columns:minmax(0,1fr) 170px; gap:8px; margin:8px 0 10px; }}
.project-grid {{ display:grid; gap:8px; }}
.project-card {{ border:1px solid #d8dde6; border-radius:12px; padding:10px; background:#fafbfc; }}
.project-card.selected {{ outline:2px solid #111; outline-offset:1px; }}
.project-card-title {{ font-weight:700; overflow-wrap:anywhere; }}
.project-card-meta {{ margin-top:4px; color:#6a7280; }}
pre {{ white-space:pre-wrap; word-break:break-word; background:#f7f7f7; padding:12px; border-radius:8px; max-height:320px; overflow:auto; }}
.status {{ padding:8px 10px; background:#fff7d6; border-radius:8px; margin:10px 0; }}
.drop-zone {{ border:2px dashed #aaa; border-radius:10px; padding:18px; text-align:center; cursor:pointer; background:#fafafa; transition:border-color .15s ease, background .15s ease; }}
.drop-zone:hover, .drop-zone:focus {{ border-color:#555; background:#f2f2f2; outline:none; }}
.drop-zone.dragover {{ border-color:#111; background:#ececec; }}
.file-meta {{ margin:8px 0 10px; min-height:18px; }}
.chat-messages {{ display:flex; flex-direction:column; gap:10px; margin-top:14px; }}
.chat-message {{ border:1px solid #e2e2e2; border-radius:10px; padding:10px 12px; background:#fafafa; }}
.chat-message.assistant {{ background:#f4f7ff; }}
.chat-message.provisional {{ border-style:dashed; opacity:.92; }}
.chat-message .meta {{ font-size:11px; color:#777; margin-bottom:5px; }}
.chat-message .content {{ white-space:pre-wrap; word-break:break-word; }}
.chat-message.assistant .content.rich-markdown {{ white-space:normal; overflow-wrap:anywhere; }}
.chat-message.assistant .content.rich-markdown > :first-child {{ margin-top:0; }}
.chat-message.assistant .content.rich-markdown > :last-child {{ margin-bottom:0; }}
.chat-message.assistant .content.rich-markdown pre {{ white-space:pre; word-break:normal; overflow:auto; max-height:none; }}
.chat-message.assistant .content.rich-markdown code {{ font-family:ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace; }}
.chat-message.assistant .content.rich-markdown :not(pre) > code {{ background:#f1f1f1; border-radius:4px; padding:1px 4px; }}
.chat-message.assistant .content.rich-markdown blockquote {{ margin:10px 0; padding-left:12px; border-left:3px solid #bbb; }}
.chat-message.assistant .content.rich-markdown table {{ border-collapse:collapse; display:block; max-width:100%; overflow-x:auto; margin:10px 0; }}
.chat-message.assistant .content.rich-markdown th,
.chat-message.assistant .content.rich-markdown td {{ border:1px solid #ccc; padding:6px 8px; text-align:left; }}
.chat-message .actions {{ display:flex; gap:6px; margin-top:8px; }}
.chat-message .actions button {{ padding:5px 8px; font-size:12px; }}
.branch-controls {{ display:flex; align-items:center; gap:8px; margin:8px 0 10px; }}
.branch-controls button {{ padding:5px 9px; }}
.edit-panel {{ margin-top:8px; }}
.edit-panel textarea {{ min-height:64px; margin-bottom:6px; }}
.library-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:10px; margin-top:10px; }}
.library-item {{ border:1px solid #d8dee8; border-radius:10px; padding:10px; background:#fff; }}
.library-item.selected {{ border-color:#4f6bed; box-shadow:0 0 0 1px #4f6bed inset; }}
.library-item-title {{ font-weight:650; overflow-wrap:anywhere; }}
.library-item-meta {{ margin-top:4px; color:#5a6575; overflow-wrap:anywhere; }}
.library-actions {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }}
.library-empty {{ padding:12px; border:1px dashed #c6ccd6; border-radius:10px; color:#697386; }}
.semantic-search-grid {{ display:grid; grid-template-columns:minmax(0,1fr) 90px auto; gap:8px; align-items:end; }}
.semantic-search-results {{ display:grid; gap:8px; margin-top:10px; }}
.semantic-search-hit {{ border:1px solid #d8dde6; border-radius:10px; padding:10px; background:#fbfcfd; }}
.semantic-search-hit-title {{ font-weight:700; }}
.semantic-search-hit-meta {{ color:#6a7280; margin:3px 0 6px; }}
.semantic-search-hit-excerpt {{ white-space:pre-wrap; overflow-wrap:anywhere; }}
.message-citations {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
.message-citation {{ display:inline-flex; align-items:center; gap:6px; border:1px solid #cfd5df; border-radius:999px; padding:5px 8px; background:#f8fafc; }}
.message-citation button {{ padding:3px 7px; margin:0; }}
.message-citation.stale {{ border-style:dashed; color:#7b4650; }}
@media(max-width:800px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<main>
<header>
  <div>
    <h1>Local Universal Runtime v{__version__}</h1>
    <div class="small">Library source grounding · Project / Chat / exact TXT-MD source / Formal Job prepare / resume</div>
  </div>
  <a href="/api/health">Health</a>
</header>

<div class="status"><b>Authority：</b>Web 只是 Runtime command/projection surface；普通 Chat 可用“发送并批准一次生成”显式授权一个 exact Formal Job，Source-grounded 路径继续保持独立 Source binding。批准动作本身不读取凭据、不调用模型/网络；实际 streaming 前 Runtime 会再次 JIT 验证。</div>

<div class="grid">
<section>
  <div class="card">
    <h3>Projects</h3>
    <div class="project-toolbar">
      <input id="projectSearch" type="search" placeholder="搜索 Project 名称" autocomplete="off" oninput="renderProjects()">
      <select id="projectSort" onchange="renderProjects()">
        <option value="latest">最近更新</option>
        <option value="name_asc">名称 A→Z</option>
        <option value="name_desc">名称 Z→A</option>
      </select>
    </div>
    <button onclick="loadProjects()">刷新</button>
    <div id="projectListStatus" class="small status" aria-live="polite"></div>
    <div id="projects" class="project-grid"></div>
  </div>
  <div class="card">
    <h3>新建 Project</h3>
    <label>名称</label>
    <input id="newProjectName" value="Universal Runtime">
    <label>Project Instructions</label>
    <textarea id="newProjectInstructions">Continue Universal Runtime development with exact Runtime evidence.</textarea>
    <button class="primary" onclick="createProject()">创建</button>
  </div>
</section>

<section>
  <div class="card">
    <h3>当前 Project</h3>
    <div id="currentProject" class="small">尚未选择</div>
    <label for="currentProjectInstructions">Project Instructions</label>
    <textarea id="currentProjectInstructions" placeholder="当前 Project Instructions" disabled></textarea>
    <button id="saveProjectInstructionsButton" type="button" onclick="reviseCurrentProjectInstructions()" disabled>保存 Project Instructions</button>
    <div id="projectInstructionsStatus" class="small status" aria-live="polite"></div>
  </div>

  <div class="card">
    <h3>Project Memory · V1</h3>
    <div class="small">仅当前 Project。Memory 由用户显式创建/编辑/启用/停用/删除；模型不会自动写入。ACTIVE Memory 会 exact freeze 到下一次普通 Chat Job。请勿存放密码、API Key、token 或其他秘密。</div>
    <textarea id="projectMemoryInput" placeholder="例如：本 Project 的默认写作风格偏好是简洁、结构化。"></textarea>
    <button id="createProjectMemoryButton" type="button" onclick="createProjectMemory()" disabled>添加 Memory</button>
    <button id="refreshProjectMemoryButton" type="button" onclick="refreshProjectMemory(false)" disabled>刷新 Memory</button>
    <div id="projectMemoryStatus" class="small status" aria-live="polite"></div>
    <div id="projectMemoryContextStatus" class="small status" aria-live="polite"></div>
    <div id="projectMemoryList" class="library-grid"></div>
  </div>

  <div class="card">
    <h3>Chat</h3>
    <label for="chatHistorySearch" class="small">Chat History</label>
    <input id="chatHistorySearch" type="search" placeholder="搜索标题或消息" autocomplete="off" oninput="renderChatSwitcher()">
    <select id="chatSwitcher" aria-label="Chat History results" onchange="switchChat()" disabled>
      <option value="">暂无 Chat</option>
    </select>
    <label class="small" for="showArchivedChats"><input id="showArchivedChats" type="checkbox" onchange="renderChatSwitcher()"> 显示已归档 Chat</label>
    <div id="branchControls" class="branch-controls">
      <button id="branchPrevButton" type="button" onclick="selectRelativeBranch(-1)" disabled>‹</button>
      <span id="branchStatus" class="small">Branch 0 / 0</span>
      <button id="branchNextButton" type="button" onclick="selectRelativeBranch(1)" disabled>›</button>
    </div>
    <input id="chatTitle" value="Mainline">
    <button onclick="createChat()">新建 Chat</button>
    <input id="renameChatTitle" placeholder="新的 Chat 名称">
    <button id="renameChatButton" onclick="renameCurrentChat()" disabled>重命名当前 Chat</button>
    <button id="archiveChatButton" onclick="toggleArchiveCurrentChat()" disabled>归档当前 Chat</button>
    <button id="deleteChatButton" onclick="deleteCurrentChat()" disabled title="从普通 Chat History 移除；Runtime audit/history 保留">删除当前 Chat</button>
    <div id="chatDeleteSemantics" class="small status">删除仅从普通 Chat History / active product surface 移除；Runtime immutable audit/history 仍保留，不等同于隐私擦除或安全删除。</div>
    <textarea id="messageText" placeholder="输入一条用户消息"></textarea>
    <button id="appendMessageButton" onclick="appendMessage()">追加消息</button>
    <div id="messageRecoveryStatus" class="small status" aria-live="polite"></div>
    <button id="streamApprovedButton" onclick="streamApprovedFormalJob()" disabled>流式执行已批准 Job</button>
    <button id="stopStreamingButton" onclick="requestStopStreaming()" disabled>停止生成</button>
    <button id="retryCancelledButton" onclick="retryCancelledFormal()" disabled>重试并批准一次生成</button>
    <button id="recoverRegenerateButton" onclick="recoverRegeneratePrepare()" disabled>恢复 Regenerate 准备</button>
    <div id="chatView" class="small"></div>
    <div id="chatMessages" class="chat-messages" aria-live="polite"></div>
  </div>

  <div class="card">
    <h3>Project Library</h3>
    <div class="small">当前 Project 已读入的 Source。直接复用已有 Source，不会重新上传或创建新的 Source Artifact。</div>
    <div id="projectLibraryStatus" class="small status" aria-live="polite"></div>
    <div id="projectLibraryList" class="library-grid"></div>
  </div>

  <div class="card">
    <h3>Semantic Project Search · Local</h3>
    <div class="small">Source-level first slice：只搜索当前 Project 已有的 exact Runtime SourceRef。使用本地 FastEmbed；不调用外部 LLM，不访问外网。结果只是 retrieval proposal，Runtime 会再次验证 SourceRef / Artifact SHA。</div>
    <div class="semantic-search-grid">
      <div>
        <label for="semanticSearchQuery" class="small">Query</label>
        <input id="semanticSearchQuery" type="search" placeholder="例如：卒中后为什么总感觉疲劳？" autocomplete="off">
      </div>
      <div>
        <label for="semanticSearchTopK" class="small">Top K</label>
        <select id="semanticSearchTopK">
          <option value="3">3</option>
          <option value="5">5</option>
        </select>
      </div>
      <button id="semanticSearchButton" type="button" onclick="searchProjectSources()">语义搜索</button>
    </div>
    <div id="semanticSearchStatus" class="small status" aria-live="polite"></div>
    <div id="semanticSearchResults" class="semantic-search-results"></div>
  </div>

  <div class="card">
    <h3>Project Source · TXT / MD / PDF / DOCX</h3>
    <label for="projectSourceSwitcher" class="small">已读入 Project Sources</label>
    <select id="projectSourceSwitcher" aria-label="Project Sources" onchange="switchProjectSource()" disabled>
      <option value="">普通 Chat（不使用 Source）</option>
    </select>
    <input id="sourceFile" type="file" accept=".txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" hidden>
    <div id="sourceDropZone" class="drop-zone" tabindex="0" role="button" aria-controls="sourceFile">
      <div><b>拖入一个 TXT / MD / PDF / DOCX 文件</b></div>
      <div class="small">或点击这里选择文件。选择后不会自动上传。</div>
    </div>
    <div id="sourceSelection" class="small file-meta">尚未选择文件</div>
    <button id="sourceUploadButton" onclick="uploadSource()">读入 / 解析并采用 Source</button>
    <div id="sourceContextStatus" class="small status" aria-live="polite"></div>
    <div id="sourceView"></div>
  </div>

  <div class="card">
    <h3>Exact Resume Projection</h3>
    <button onclick="resumeProject()">重新读取 Runtime state</button>
    <pre id="resumeView"></pre>
  </div>
</section>
</div>
</main>

<script src="/assets/vendor/markdown-it-14.3.1.min.js"></script>
<script>
const assistantMarkdownRenderer = (() => {{
  try {{
    if(typeof window.markdownit !== "function") return null;
    return window.markdownit({{
      html:false,
      linkify:false,
      typographer:false
    }});
  }} catch(_e) {{
    return null;
  }}
}})();

function renderCanonicalMessageContent(node, actor, rawContent) {{
  const text=typeof rawContent === "string" ? rawContent : "[no text content]";
  if(actor !== "ASSISTANT") {{
    node.textContent=text;
    return;
  }}
  if(!assistantMarkdownRenderer) {{
    node.dataset.markdownFallback="renderer-unavailable";
    node.title="Markdown renderer unavailable; showing literal text";
    node.textContent=text;
    return;
  }}
  try {{
    node.classList.add("rich-markdown");
    node.innerHTML=assistantMarkdownRenderer.render(text);
    for(const link of node.querySelectorAll("a[href]")) {{
      const href=String(link.getAttribute("href") || "").trim();
      if(/^(?:javascript|vbscript|file|data):/i.test(href)) {{
        link.replaceWith(document.createTextNode(link.textContent || ""));
        continue;
      }}
      link.target="_blank";
      link.rel="noopener noreferrer";
    }}
  }} catch(_e) {{
    node.classList.remove("rich-markdown");
    node.dataset.markdownFallback="renderer-error";
    node.title="Markdown renderer error; showing literal text";
    node.textContent=text;
  }}
}}

let state = {{ project:null, chat:null, source:null, plainChatMode:false, resume:null, projects:[], branchState:null, projectMemory:[], projectMemoryContext:null, pendingSourceContextRetry:null, pendingPlainSend:null, pendingRegenerate:null, pendingFormal:null, retryFormal:null, retryInFlight:false, streaming:false, activeStreamExecutionId:null, stopRequested:false }};
let selectedSourceFile = null;
let sourceUploadInFlight = false;

function cmd(prefix) {{
  return prefix + "-" + Date.now().toString(36) + "-" + crypto.getRandomValues(new Uint32Array(1))[0].toString(16);
}}
async function api(url, options={{}}) {{
  const r = await fetch(url, options);
  const body = await r.json().catch(() => ({{}}));
  if (!r.ok) {{
    const err = new Error(JSON.stringify(body));
    err.body = body;
    throw err;
  }}
  return body;
}}
function showError(e) {{ alert(e.message || String(e)); }}

function errorDetail(e) {{
  const detail=e && e.body && e.body.detail;
  return detail && typeof detail === "object" ? detail : null;
}}


const CONFIRMED_CANCEL_RETRY_SESSION_KEY="UR_WEB_R004_P1_CONFIRMED_CANCEL_RETRY_SESSION_R001";

function confirmedCancelRetryBindingShapeOk(binding) {{
  return Boolean(
    binding &&
    typeof binding==="object" &&
    typeof binding.artifact_identity_sha256==="string" &&
    /^[0-9a-f]{{64}}$/.test(binding.artifact_identity_sha256) &&
    Number.isInteger(binding.artifact_revision) &&
    binding.artifact_revision>=1 &&
    typeof binding.artifact_sha256==="string" &&
    /^[0-9a-f]{{64}}$/.test(binding.artifact_sha256)
  );
}}

function confirmedCancelRetryHintFromState(retry) {{
  if(!retry) return null;
  return {{
    schema:"UR_WEB_R004_P1_CONFIRMED_CANCEL_RETRY_SESSION_HINT_R002",
    retry_mode:retry.retry_mode,
    project_id:retry.project_id,
    chat_id:retry.chat_id,
    predecessor_job_id:retry.predecessor_job_id,
    predecessor_job_bundle_binding:retry.predecessor_job_bundle_binding,
    predecessor_web_formal_job_intake_binding:retry.predecessor_web_formal_job_intake_binding,
    predecessor_cancellation_outcome_binding:retry.predecessor_cancellation_outcome_binding,
    source_context:retry.source_context,
    source_context_sha256:retry.source_context_sha256,
    initiating_user_event_id:retry.initiating_user_event_id,
    accepted_chat_revision:retry.accepted_chat_revision
  }};
}}

function clearConfirmedCancelRetryHint() {{
  try {{ sessionStorage.removeItem(CONFIRMED_CANCEL_RETRY_SESSION_KEY); }} catch(_e) {{}}
}}

function persistConfirmedCancelRetryHint(retry) {{
  const hint=confirmedCancelRetryHintFromState(retry);
  if(!hint) return clearConfirmedCancelRetryHint();
  try {{
    sessionStorage.setItem(CONFIRMED_CANCEL_RETRY_SESSION_KEY, JSON.stringify(hint));
  }} catch(_e) {{}}
}}

function readConfirmedCancelRetryHint() {{
  let raw=null;
  try {{ raw=sessionStorage.getItem(CONFIRMED_CANCEL_RETRY_SESSION_KEY); }} catch(_e) {{ return null; }}
  if(!raw) return null;
  try {{
    const hint=JSON.parse(raw);
    const legacySource=hint && hint.schema==="UR_WEB_R004_P1_CONFIRMED_CANCEL_RETRY_SESSION_HINT_R001";
    const current=hint && hint.schema==="UR_WEB_R004_P1_CONFIRMED_CANCEL_RETRY_SESSION_HINT_R002";
    const mode=legacySource ? "SOURCE" : hint && hint.retry_mode;
    const common=Boolean(
      hint && (legacySource || current) && (mode==="SOURCE" || mode==="PLAIN") &&
      typeof hint.project_id==="string" && hint.project_id &&
      typeof hint.chat_id==="string" && hint.chat_id &&
      typeof hint.predecessor_job_id==="string" && hint.predecessor_job_id &&
      confirmedCancelRetryBindingShapeOk(hint.predecessor_job_bundle_binding) &&
      confirmedCancelRetryBindingShapeOk(hint.predecessor_web_formal_job_intake_binding) &&
      confirmedCancelRetryBindingShapeOk(hint.predecessor_cancellation_outcome_binding) &&
      typeof hint.initiating_user_event_id==="string" && hint.initiating_user_event_id &&
      Number.isInteger(hint.accepted_chat_revision) && hint.accepted_chat_revision>=1
    );
    const eventId=hint && hint.source_context && hint.source_context.initiating_user_event && hint.source_context.initiating_user_event.event_id;
    const provenanceOk=mode==="SOURCE"
      ? Boolean(hint.source_context && typeof hint.source_context==="object" && typeof hint.source_context_sha256==="string" && /^[0-9a-f]{{64}}$/.test(hint.source_context_sha256) && eventId===hint.initiating_user_event_id)
      : Boolean(hint.source_context===null && hint.source_context_sha256===null);
    if(!common || !provenanceOk) {{ clearConfirmedCancelRetryHint(); return null; }}
    return {{...hint,retry_mode:mode}};
  }} catch(_e) {{ clearConfirmedCancelRetryHint(); return null; }}
}}

function rehydrateConfirmedCancelRetryHint(body) {{
  if(state.retryFormal) return state.retryFormal;
  const hint=readConfirmedCancelRetryHint();
  if(!hint || !body || !body.project || body.project.project_id!==hint.project_id) return null;
  const rows=body.chats || [];
  const row=rows.find(item => item.chat && item.chat.chat_id===hint.chat_id);
  const chat=row && row.chat;
  const eventRow=row && (row.events || []).find(item => item.event && item.event.event_id===hint.initiating_user_event_id);
  const event=eventRow && eventRow.event;
  if(
    !chat ||
    chat.head_event_id!==hint.initiating_user_event_id ||
    chat.chat_revision!==hint.accepted_chat_revision ||
    !event ||
    event.event_type!=="USER_MESSAGE" ||
    event.actor_class!=="USER"
  ) {{
    clearConfirmedCancelRetryHint();
    return null;
  }}
  state.retryFormal={{
    retry_mode:hint.retry_mode,
    project_id:hint.project_id,
    chat_id:hint.chat_id,
    predecessor_job_id:hint.predecessor_job_id,
    predecessor_job_bundle_binding:hint.predecessor_job_bundle_binding,
    predecessor_web_formal_job_intake_binding:hint.predecessor_web_formal_job_intake_binding,
    predecessor_cancellation_outcome_binding:hint.predecessor_cancellation_outcome_binding,
    source_context:hint.source_context,
    source_context_sha256:hint.source_context_sha256,
    initiating_user_event_id:hint.initiating_user_event_id,
    accepted_chat_revision:hint.accepted_chat_revision
  }};
  return state.retryFormal;
}}

const SOURCE_CONTEXT_RETRY_SESSION_KEY="UR_WEB_R004_G7B_SOURCE_CONTEXT_RETRY_R001";

function sourceContextRetryHintFromPending(pending) {{
  if(!pending) return null;
  return {{
    schema:"UR_WEB_R004_G7B_SOURCE_CONTEXT_RETRY_SESSION_HINT_R001",
    project_id:pending.project_id,
    chat_id:pending.chat_id,
    source_ref_id:pending.source_ref_id,
    command_id:pending.command_id,
    expected_chat_revision:pending.expected_chat_revision,
    initiating_user_event_id:pending.initiating_user_event_id,
    question_sha256:pending.question_sha256
  }};
}}

function clearPendingSourceContextRetryHint() {{
  try {{ sessionStorage.removeItem(SOURCE_CONTEXT_RETRY_SESSION_KEY); }} catch(_e) {{}}
}}

function persistPendingSourceContextRetryHint(pending) {{
  const hint=sourceContextRetryHintFromPending(pending);
  if(!hint) return clearPendingSourceContextRetryHint();
  try {{
    sessionStorage.setItem(SOURCE_CONTEXT_RETRY_SESSION_KEY, JSON.stringify(hint));
  }} catch(_e) {{}}
}}

function readPendingSourceContextRetryHint() {{
  let raw=null;
  try {{ raw=sessionStorage.getItem(SOURCE_CONTEXT_RETRY_SESSION_KEY); }} catch(_e) {{ return null; }}
  if(!raw) return null;
  try {{
    const hint=JSON.parse(raw);
    const valid=Boolean(
      hint &&
      hint.schema==="UR_WEB_R004_G7B_SOURCE_CONTEXT_RETRY_SESSION_HINT_R001" &&
      typeof hint.project_id==="string" && hint.project_id &&
      typeof hint.chat_id==="string" && hint.chat_id &&
      typeof hint.source_ref_id==="string" && hint.source_ref_id &&
      typeof hint.command_id==="string" && hint.command_id &&
      Number.isInteger(hint.expected_chat_revision) && hint.expected_chat_revision>=0 &&
      typeof hint.initiating_user_event_id==="string" && hint.initiating_user_event_id &&
      typeof hint.question_sha256==="string" && /^[0-9a-f]{{64}}$/.test(hint.question_sha256)
    );
    if(!valid) {{
      clearPendingSourceContextRetryHint();
      return null;
    }}
    return hint;
  }} catch(_e) {{
    clearPendingSourceContextRetryHint();
    return null;
  }}
}}

function rehydratePendingSourceContextRetry(body) {{
  if(state.pendingSourceContextRetry) return state.pendingSourceContextRetry;
  const hint=readPendingSourceContextRetryHint();
  if(!hint || !body || !body.project || hint.project_id!==body.project.project_id) return null;

  const chatRow=(body.chats || []).find(item => item.chat && item.chat.chat_id===hint.chat_id);
  const sourceRow=(body.sources || []).find(item => item.source_ref && item.source_ref.source_ref_id===hint.source_ref_id);
  const eventRow=chatRow && (chatRow.events || []).find(item => item.event && item.event.event_id===hint.initiating_user_event_id);
  const chat=chatRow && chatRow.chat;
  const event=eventRow && eventRow.event;

  const exactCurrent=Boolean(
    chat &&
    sourceRow &&
    event &&
    event.event_type==="USER_MESSAGE" &&
    event.chat_id===hint.chat_id &&
    event.content_sha256===hint.question_sha256 &&
    typeof event.content==="string" &&
    chat.head_event_id===hint.initiating_user_event_id &&
    chat.chat_revision===hint.expected_chat_revision+1
  );
  if(!exactCurrent) {{
    clearPendingSourceContextRetryHint();
    const status=document.getElementById("sourceContextStatus");
    if(status) status.textContent="source context reload recovery STOP · exact pending Chat/Source/event binding is no longer current；未自动重试，已丢弃 browser-local recovery hint。";
    return null;
  }}

  const pending={{
    project_id:hint.project_id,
    chat_id:hint.chat_id,
    source_ref_id:hint.source_ref_id,
    content:event.content,
    command_id:hint.command_id,
    expected_chat_revision:hint.expected_chat_revision,
    initiating_user_event_id:hint.initiating_user_event_id,
    question_sha256:hint.question_sha256
  }};
  state.pendingSourceContextRetry=pending;
  const input=document.getElementById("messageText");
  if(input && !input.value) input.value=event.content;
  const status=document.getElementById("sourceContextStatus");
  if(status) status.textContent="source context reload recovery 已恢复 · USER_MESSAGE 已存在；再次点击追加将复用 exact command，不会重复 USER_MESSAGE。";
  return pending;
}}

function setMessageRecoveryStatus(message) {{
  const status=document.getElementById("messageRecoveryStatus");
  if(status) status.textContent=message || "";
}}

function isStaleChatRevisionError(e) {{
  const detail=errorDetail(e);
  return Boolean(detail && detail.code==="STALE_CHAT_REVISION");
}}

async function recoverStaleMessageSend(e, attemptedChatId, attemptedChatRevision) {{
  if(!isStaleChatRevisionError(e)) return false;
  const input=document.getElementById("messageText");
  await resumeProject();
  const sameChat=Boolean(state.chat && state.chat.chat_id===attemptedChatId);
  const refreshedRevision=sameChat ? state.chat.chat_revision : null;
  if(!sameChat) {{
    setMessageRecoveryStatus("发送未执行 · STALE_CHAT_REVISION · Runtime state 已重新读取，但原 Chat 不再是当前 Chat；草稿保留，请先重新选择原 Chat。 ");
    if(input) input.focus();
    return true;
  }}
  if(refreshedRevision===attemptedChatRevision) {{
    setMessageRecoveryStatus("发送未执行 · STALE_CHAT_REVISION · Runtime state 尚未刷新到新的 Chat revision；草稿保留，请使用‘重新读取 Runtime state’后再确认。 ");
    if(input) input.focus();
    return true;
  }}
  setMessageRecoveryStatus(`发送未执行 · STALE_CHAT_REVISION · Runtime state 已刷新：R${{attemptedChatRevision}} → R${{refreshedRevision}}；草稿保留，请确认最新 Chat 后再次点击“追加消息”。`);
  if(input) input.focus();
  return true;
}}

function projectRowsForView(rows, query, sortMode) {{
  const normalized=(query || "").trim().toLocaleLowerCase();
  const filtered=(rows || []).filter(p => {{
    const name=String(p && p.display_name || "").toLocaleLowerCase();
    return !normalized || name.includes(normalized);
  }});
  const sorted=[...filtered];
  if(sortMode==="name_asc") {{
    sorted.sort((a,b) => String(a.display_name || "").localeCompare(String(b.display_name || ""), undefined, {{sensitivity:"base"}}));
  }} else if(sortMode==="name_desc") {{
    sorted.sort((a,b) => String(b.display_name || "").localeCompare(String(a.display_name || ""), undefined, {{sensitivity:"base"}}));
  }} else {{
    sorted.sort((a,b) => {{
      const at=Date.parse(a.updated_at_utc || "") || 0;
      const bt=Date.parse(b.updated_at_utc || "") || 0;
      if(bt!==at) return bt-at;
      return String(a.display_name || "").localeCompare(String(b.display_name || ""), undefined, {{sensitivity:"base"}});
    }});
  }}
  return sorted;
}}

function projectUpdatedLabel(value) {{
  const parsed=Date.parse(value || "");
  if(!Number.isFinite(parsed)) return "更新时间未知";
  return new Date(parsed).toLocaleString();
}}

function renderProjects() {{
  const container=document.getElementById("projects");
  const status=document.getElementById("projectListStatus");
  if(!container) return;
  const query=document.getElementById("projectSearch")?.value || "";
  const sortMode=document.getElementById("projectSort")?.value || "latest";
  const rows=projectRowsForView(state.projects || [], query, sortMode);
  container.replaceChildren();

  if(!rows.length) {{
    const empty=document.createElement("div");
    empty.className="small";
    empty.textContent=(state.projects || []).length ? "没有匹配的 Project" : "暂无 Project";
    container.appendChild(empty);
    if(status) status.textContent=`显示 ${{rows.length}} / ${{(state.projects || []).length}} 个 Project`;
    return;
  }}

  for(const p of rows) {{
    const selected=Boolean(state.project && state.project.project_id===p.project_id);
    const item=document.createElement("div");
    item.className="project-card" + (selected ? " selected" : "");
    item.dataset.projectId=p.project_id;

    const title=document.createElement("div");
    title.className="project-card-title";
    title.textContent=p.display_name;

    const meta=document.createElement("div");
    meta.className="small project-card-meta";
    meta.textContent=`R${{p.project_revision}} · ${{projectUpdatedLabel(p.updated_at_utc)}}`;

    const open=document.createElement("button");
    open.type="button";
    open.textContent=selected ? "当前 Project" : "打开";
    open.disabled=
      selected ||
      state.streaming ||
      state.retryInFlight ||
      Boolean(state.pendingSourceContextRetry) ||
      Boolean(state.pendingPlainSend);
    open.addEventListener("click", () => openProject(p.project_id));

    item.append(title, meta, open);
    container.appendChild(item);
  }}
  if(status) status.textContent=`显示 ${{rows.length}} / ${{(state.projects || []).length}} 个 Project`;
}}

async function loadProjects() {{
  try {{
    const rows = await api("/api/web/projects");
    state.projects=Array.isArray(rows) ? rows : [];
    renderProjects();

    if(!state.project) {{
      const sourceHint=readPendingSourceContextRetryHint();
      const cancelRetryHint=readConfirmedCancelRetryHint();
      const hint=sourceHint || cancelRetryHint;
      if(hint && state.projects.some(p => p.project_id===hint.project_id)) await openProject(hint.project_id);
    }}
  }} catch(e) {{ showError(e); }}
}}

async function createProject() {{
  try {{
    const body = await api("/api/web/projects", {{
      method:"POST", headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:cmd("project"),
        display_name:document.getElementById("newProjectName").value,
        instructions:document.getElementById("newProjectInstructions").value
      }})
    }});
    state.project = body.project;
    state.chat = null; state.source = null; state.plainChatMode = true; state.resume = null;
    resetChatHistorySearch();
    renderCurrent(); renderChatMessages(); await loadProjects(); await resumeProject();
  }} catch(e) {{ showError(e); }}
}}

async function openProject(projectId) {{
  try {{
    const body = await api(`/api/web/projects/${{projectId}}`);
    state.resume = body;
    state.project = body.project;
    resetChatHistorySearch();
    const pending=rehydratePendingSourceContextRetry(body);
    const plainPending=state.pendingPlainSend && state.pendingPlainSend.project_id===body.project.project_id
      ? state.pendingPlainSend
      : null;
    const cancelRetryHint=!pending && !plainPending ? readConfirmedCancelRetryHint() : null;
    const chats = body.chats || [];
    const desiredChatId=pending ? pending.chat_id : (plainPending ? plainPending.chat_id : (cancelRetryHint ? cancelRetryHint.chat_id : null));
    const chatMatch=desiredChatId ? chats.find(item => item.chat && item.chat.chat_id===desiredChatId) : null;
    state.chat = chatMatch ? chatMatch.chat : firstVisibleChat(chats);
    const sources = body.sources || [];
    const sourceMatch=pending ? sources.find(item => item.source_ref && item.source_ref.source_ref_id===pending.source_ref_id) : null;
    if(pending) {{
      state.source=sourceMatch ? sourceMatch.source_ref : null;
      state.plainChatMode=false;
    }} else if(plainPending) {{
      state.source=null;
      state.plainChatMode=true;
    }} else {{
      state.source=sources.length ? sources[0].source_ref : null;
      state.plainChatMode=!state.source;
    }}
    if(!pending && !plainPending) rehydrateConfirmedCancelRetryHint(body);
    await refreshBranchState(true);
    renderCurrent(); renderChatMessages(); renderResume(body);
    if(state.retryFormal && retryFormalMatchesCurrent()) {{
      const status=document.getElementById("sourceContextStatus");
      if(status) status.textContent="confirmed-cancel Retry 已从 browser-local session hint 恢复；不会自动重试，点击时 Runtime 仍会重新验证 exact predecessor/currentness。";
    }}
    await refreshStreamingApprovalStatus(true);
  }} catch(e) {{ showError(e); }}
}}

function chatLifecycleState(chat) {{
  if(chat && chat.lifecycle_state === "DELETED") return "DELETED";
  return chat && chat.lifecycle_state === "ARCHIVED" ? "ARCHIVED" : "ACTIVE";
}}

function showArchivedChatsEnabled() {{
  const input=document.getElementById("showArchivedChats");
  return Boolean(input && input.checked);
}}

function firstVisibleChat(rows) {{
  const chats=(rows || []).filter(item => item.chat && chatLifecycleState(item.chat) !== "DELETED");
  const active=chats.find(item => chatLifecycleState(item.chat) === "ACTIVE");
  if(active) return active.chat;
  if(showArchivedChatsEnabled()) {{
    const first=chats.find(item => chatLifecycleState(item.chat) === "ARCHIVED");
    return first ? first.chat : null;
  }}
  return null;
}}

function normalizeChatHistorySearch(value) {{
  return String(value || "").trim().toLocaleLowerCase();
}}

function chatHistorySearchText(item) {{
  const chat=item && item.chat;
  if(!chat) return "";
  const parts=[chat.title || ""];
  for(const row of (item.events || [])) {{
    const event=row && row.event;
    if(event && typeof event.content === "string") parts.push(event.content);
  }}
  return normalizeChatHistorySearch(parts.join("\\n"));
}}

function chatMatchesHistoryQuery(item, query) {{
  const normalized=normalizeChatHistorySearch(query);
  if(!normalized) return true;
  const terms=normalized.split(/\\s+/).filter(Boolean);
  const searchText=chatHistorySearchText(item);
  return terms.every(term => searchText.includes(term));
}}

function resetChatHistorySearch() {{
  const input=document.getElementById("chatHistorySearch");
  if(input) input.value="";
}}

function renderChatSwitcher() {{
  const select=document.getElementById("chatSwitcher");
  if(!select) return;
  select.replaceChildren();

  const allChats=(state.resume && state.resume.chats) || [];
  const searchInput=document.getElementById("chatHistorySearch");
  const query=searchInput ? searchInput.value : "";
  const showArchived=showArchivedChatsEnabled();
  const chats=allChats
    .filter(item => item.chat && chatLifecycleState(item.chat) !== "DELETED")
    .filter(item => showArchived || chatLifecycleState(item.chat) === "ACTIVE")
    .filter(item => chatMatchesHistoryQuery(item, query));
  if(!chats.length) {{
    const empty=document.createElement("option");
    empty.value="";
    empty.textContent=normalizeChatHistorySearch(query) ? "无匹配 Chat" : "暂无 Chat";
    select.appendChild(empty);
    select.disabled=true;
    return;
  }}

  const currentVisible=Boolean(
    state.chat && chats.some(item => item.chat && item.chat.chat_id===state.chat.chat_id)
  );
  if(normalizeChatHistorySearch(query) && !currentVisible) {{
    const prompt=document.createElement("option");
    prompt.value="";
    prompt.textContent=`${{chats.length}} 个匹配 Chat · 请选择`;
    prompt.selected=true;
    select.appendChild(prompt);
  }}

  for(const item of chats) {{
    const chat=item && item.chat;
    if(!chat || !chat.chat_id) continue;
    const option=document.createElement("option");
    option.value=chat.chat_id;
    const archived=chatLifecycleState(chat) === "ARCHIVED";
    option.textContent=`${{archived ? "[已归档] " : ""}}${{chat.title || chat.chat_id}}`;
    option.selected=Boolean(state.chat && state.chat.chat_id===chat.chat_id);
    select.appendChild(option);
  }}

  select.disabled=
    state.streaming ||
    state.retryInFlight ||
    Boolean(state.pendingSourceContextRetry);
}}

async function switchChat() {{
  const select=document.getElementById("chatSwitcher");
  if(!select || !select.value) return;
  if(state.streaming || state.retryInFlight || state.pendingSourceContextRetry) {{
    renderChatSwitcher();
    return alert("当前执行/恢复状态下禁止切换 Chat");
  }}

  const chats=(state.resume && state.resume.chats) || [];
  const match=chats.find(item => item.chat && item.chat.chat_id===select.value);
  if(!match) {{
    renderChatSwitcher();
    return alert("目标 Chat 已不可用；请重新读取当前 Project 状态");
  }}

  state.chat=match.chat;
  await refreshBranchState(true);
  renderCurrent();
  renderChatMessages();
  renderChatSwitcher();
  await refreshStreamingApprovalStatus(true);
}}

function branchActionBlocked() {{
  return Boolean(state.streaming || state.retryInFlight || state.pendingSourceContextRetry || state.pendingRegenerate);
}}

async function refreshBranchState(silent=true) {{
  if(!state.project || !state.chat) {{
    state.branchState=null;
    return null;
  }}
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{state.chat.chat_id}}/branch-state`);
    if(!state.chat || body.chat.chat_id!==state.chat.chat_id) return null;
    state.branchState=body;
    state.chat=body.chat;
    return body;
  }} catch(e) {{
    state.branchState=null;
    if(!silent) showError(e);
    return null;
  }}
}}

function renderBranchControls() {{
  const prev=document.getElementById("branchPrevButton");
  const next=document.getElementById("branchNextButton");
  const status=document.getElementById("branchStatus");
  const leaves=(state.branchState && state.branchState.leaf_heads) || [];
  const head=state.chat && state.chat.head_event_id;
  let index=leaves.findIndex(item => item.event_id===head);
  if(index<0 && leaves.length) index=0;
  status.textContent=leaves.length ? `Branch ${{index+1}} / ${{leaves.length}}` : "Branch 0 / 0";
  const disabled=branchActionBlocked() || leaves.length<2;
  prev.disabled=disabled;
  next.disabled=disabled;
}}

async function selectRelativeBranch(delta) {{
  if(!state.project || !state.chat || branchActionBlocked()) return;
  const leaves=(state.branchState && state.branchState.leaf_heads) || [];
  if(leaves.length<2) return;
  const current=leaves.findIndex(item => item.event_id===state.chat.head_event_id);
  if(current<0) return alert("当前 branch head 已不可用；请重新读取 Runtime state");
  const target=leaves[(current+delta+leaves.length)%leaves.length];
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{state.chat.chat_id}}/active-head`, {{
      method:"POST", headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:cmd("branch-head"),
        expected_chat_revision:state.chat.chat_revision,
        target_head_event_id:target.event_id
      }})
    }});
    state.chat=body.chat;
    state.pendingFormal=null;
    state.pendingRegenerate=null;
    state.retryFormal=null; clearConfirmedCancelRetryHint();
    await resumeProject();
  }} catch(e) {{ showError(e); }}
}}

function beginEditUserMessage(wrapper, event) {{
  if(branchActionBlocked()) return alert("当前执行/恢复状态下禁止编辑 branch");
  const old=wrapper.querySelector(".edit-panel");
  if(old) old.remove();
  const panel=document.createElement("div");
  panel.className="edit-panel";
  const input=document.createElement("textarea");
  input.value=typeof event.content==="string" ? event.content : "";
  const save=document.createElement("button");
  save.type="button";
  save.textContent="保存并从这里继续";
  const cancel=document.createElement("button");
  cancel.type="button";
  cancel.textContent="取消";
  cancel.addEventListener("click", () => panel.remove());
  save.addEventListener("click", async () => {{
    const content=input.value;
    if(!content) return alert("编辑后的消息不能为空");
    save.disabled=true; cancel.disabled=true;
    try {{
      const body=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{state.chat.chat_id}}/messages/${{event.event_id}}/edit-branch`, {{
        method:"POST", headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{
          command_id:cmd("edit-branch"),
          expected_chat_revision:state.chat.chat_revision,
          content
        }})
      }});
      state.chat=body.chat;
      state.pendingFormal=null;
    state.pendingRegenerate=null;
      state.retryFormal=null; clearConfirmedCancelRetryHint();
      document.getElementById("messageText").value=content;
      await resumeProject();
      document.getElementById("messageText").focus();
    }} catch(e) {{
      showError(e);
      save.disabled=false; cancel.disabled=false;
    }}
  }});
  panel.append(input, save, cancel);
  wrapper.appendChild(panel);
}}

function sourceRowByRefId(sourceRefId) {{
  return currentProjectSourceRows().find(item =>
    item.source_ref && item.source_ref.source_ref_id===sourceRefId
  ) || null;
}}

function regenerateSourceBindingForAssistant(assistantEvent) {{
  const activeEvents=(state.branchState && state.branchState.active_events) || [];
  const parentId=assistantEvent && assistantEvent.parent_event_id;
  if(!parentId) return {{ok:false, code:"REGENERATE_PARENT_USER_MISSING"}};

  const parent=activeEvents.find(event => event && event.event_id===parentId);
  if(
    !parent ||
    String(parent.actor_class || "").toUpperCase()!=="USER" ||
    parent.event_type!=="USER_MESSAGE"
  ) {{
    return {{ok:false, code:"REGENERATE_PARENT_USER_INVALID"}};
  }}

  const ids=Array.isArray(parent.related_source_ref_ids)
    ? [...new Set(parent.related_source_ref_ids.filter(x => typeof x==="string" && x))]
    : [];
  if(ids.length!==1) {{
    return {{ok:false, code:"REGENERATE_ORIGINAL_SOURCE_CARDINALITY_STOP", source_ref_ids:ids}};
  }}

  const sourceRefId=ids[0];
  const row=sourceRowByRefId(sourceRefId);
  if(!row || !row.source_ref || row.source_ref.source_ref_id!==sourceRefId) {{
    return {{ok:false, code:"REGENERATE_ORIGINAL_SOURCE_STALE", source_ref_id:sourceRefId}};
  }}

  return {{
    ok:true,
    source_ref_id:sourceRefId,
    source_ref:row.source_ref,
    parent_user_event_id:parent.event_id
  }};
}}

function renderAssistantSourceCitations(wrapper, assistantEvent, activeEvents) {{
  const parentId=assistantEvent && assistantEvent.parent_event_id;
  if(!parentId) return;
  const parent=activeEvents.find(event => event && event.event_id===parentId);
  const ids=parent && Array.isArray(parent.related_source_ref_ids)
    ? [...new Set(parent.related_source_ref_ids.filter(x => typeof x==="string" && x))]
    : [];
  if(!ids.length) return;

  const citations=document.createElement("div");
  citations.className="message-citations";
  citations.setAttribute("aria-label","Answer sources");

  ids.forEach((sourceRefId, index) => {{
    const row=sourceRowByRefId(sourceRefId);
    const chip=document.createElement("span");
    chip.className="message-citation";
    chip.dataset.sourceRefId=sourceRefId;

    if(!row || !row.source_ref || !row.source_ref.source_artifact_binding) {{
      chip.classList.add("stale");
      chip.textContent=`[${{index+1}}] Source unavailable/stale · ${{sourceRefId}}`;
      citations.appendChild(chip);
      return;
    }}

    const ref=row.source_ref;
    const binding=ref.source_artifact_binding;
    const sha=String(binding.sha256 || "");
    const label=document.createElement("span");
    label.textContent=`[${{index+1}}] ${{ref.filename || "Source"}} · SHA ${{sha.slice(0,12)}}`;

    const open=document.createElement("button");
    open.type="button";
    open.textContent="打开 Source";
    open.addEventListener("click", () => useLibrarySource(sourceRefId));

    chip.append(label, open);
    citations.appendChild(chip);
  }});

  wrapper.appendChild(citations);
}}

function renderChatMessages() {{
  const container=document.getElementById("chatMessages");
  container.replaceChildren();

  const activeEvents=(state.branchState && state.branchState.active_events) || [];
  const events=activeEvents.map(event => ({{event}}));

  if(!events.length) {{
    const empty=document.createElement("div");
    empty.className="small";
    empty.textContent=state.chat ? "当前 Chat 暂无消息" : "请选择或新建 Chat";
    container.appendChild(empty);
    renderBranchControls();
    return;
  }}

  for(const item of events) {{
    const event=item.event || {{}};
    const actor=String(event.actor_class || "UNKNOWN").toUpperCase();

    const wrapper=document.createElement("div");
    wrapper.className=`chat-message ${{actor === "ASSISTANT" ? "assistant" : "user"}}`;

    const meta=document.createElement("div");
    meta.className="meta";
    meta.textContent=`${{actor}} · #${{event.event_sequence_1_based || "?"}} · ${{event.event_type || "EVENT"}}`;

    const content=document.createElement("div");
    content.className="content";
    renderCanonicalMessageContent(content, actor, event.content);

    wrapper.append(meta, content);
    if(actor === "ASSISTANT") {{
      renderAssistantSourceCitations(wrapper, event, activeEvents);
    }}
    if(actor === "USER") {{
      const actions=document.createElement("div");
      actions.className="actions";
      const editButton=document.createElement("button");
      editButton.type="button";
      editButton.textContent="编辑";
      editButton.disabled=branchActionBlocked();
      editButton.addEventListener("click", () => beginEditUserMessage(wrapper, event));
      actions.appendChild(editButton);
      wrapper.appendChild(actions);
    }} else if(
      actor === "ASSISTANT" &&
      state.chat &&
      event.event_id===state.chat.head_event_id &&
      typeof event.related_job_id==="string" && event.related_job_id
    ) {{
      const actions=document.createElement("div");
      actions.className="actions";
      const regenerateButton=document.createElement("button");
      regenerateButton.type="button";
      const regenerateBinding=regenerateSourceBindingForAssistant(event);
      const plainRegenerate=plainRegenerateEligible(regenerateBinding);
      regenerateButton.textContent=regenerateBinding.ok
        ? `Regenerate（原 Source：${{regenerateBinding.source_ref.filename || regenerateBinding.source_ref_id}}）`
        : (plainRegenerate ? "Regenerate（普通 Chat · 无 Source）" : "Regenerate（原 Source unavailable/stale）");
      regenerateButton.disabled=branchActionBlocked() || (!regenerateBinding.ok && !plainRegenerate) || Boolean(state.pendingFormal);
      regenerateButton.addEventListener("click", () => regenerateSuccessfulAssistant(event));
      actions.appendChild(regenerateButton);
      wrapper.appendChild(actions);
    }}
    container.appendChild(wrapper);
  }}
  renderBranchControls();
}}

function pendingFormalMatchesCurrent() {{
  return Boolean(
    state.pendingFormal &&
    state.project &&
    state.chat &&
    state.pendingFormal.project_id===state.project.project_id &&
    state.pendingFormal.chat_id===state.chat.chat_id
  );
}}

function currentPendingFormalSnapshot() {{
  if(!pendingFormalMatchesCurrent()) return null;
  return Object.freeze({{
    project_id:state.pendingFormal.project_id,
    chat_id:state.pendingFormal.chat_id,
    job_id:state.pendingFormal.job_id,
    decision_request_event_id:state.pendingFormal.decision_request_event_id,
    job_bundle_binding:state.pendingFormal.job_bundle_binding,
    web_formal_job_intake_binding:state.pendingFormal.web_formal_job_intake_binding,
    source_context:state.pendingFormal.source_context,
    source_context_sha256:state.pendingFormal.source_context_sha256,
    initiating_user_event_id:state.pendingFormal.initiating_user_event_id,
    accepted_chat_revision:state.pendingFormal.accepted_chat_revision
  }});
}}

function pendingFormalSnapshotStillPending(snapshot) {{
  return Boolean(
    snapshot &&
    state.pendingFormal &&
    state.pendingFormal.project_id===snapshot.project_id &&
    state.pendingFormal.chat_id===snapshot.chat_id &&
    state.pendingFormal.job_id===snapshot.job_id &&
    state.pendingFormal.decision_request_event_id===snapshot.decision_request_event_id
  );
}}

function pendingFormalSnapshotStillCurrent(snapshot) {{
  return Boolean(
    pendingFormalSnapshotStillPending(snapshot) &&
    state.project &&
    state.chat &&
    state.project.project_id===snapshot.project_id &&
    state.chat.chat_id===snapshot.chat_id
  );
}}

function retryFormalMatchesCurrent() {{
  return Boolean(
    state.retryFormal &&
    state.project &&
    state.chat &&
    state.retryFormal.project_id===state.project.project_id &&
    state.retryFormal.chat_id===state.chat.chat_id &&
    state.retryFormal.initiating_user_event_id===state.chat.head_event_id &&
    state.retryFormal.accepted_chat_revision===state.chat.chat_revision
  );
}}

function currentRetryFormalSnapshot() {{
  if(!retryFormalMatchesCurrent()) return null;
  return Object.freeze({{...state.retryFormal}});
}}

function renderProjectInstructions() {{
  const input=document.getElementById("currentProjectInstructions");
  const save=document.getElementById("saveProjectInstructionsButton");
  const status=document.getElementById("projectInstructionsStatus");
  if(!input || !save) return;
  const projectId=state.project && state.project.project_id;
  if(!projectId) {{
    input.value="";
    input.disabled=true;
    save.disabled=true;
    input.dataset.projectId="";
    if(status) status.textContent="";
    return;
  }}
  input.disabled=false;
  save.disabled=false;
  const authoritative=state.resume && typeof state.resume.project_instructions==="string"
    ? state.resume.project_instructions
    : "";
  const projectChanged=input.dataset.projectId!==projectId;
  if(projectChanged || document.activeElement!==input) input.value=authoritative;
  input.dataset.projectId=projectId;
}}

async function reviseCurrentProjectInstructions() {{
  if(!state.project) return alert("先选择 Project");
  const input=document.getElementById("currentProjectInstructions");
  const save=document.getElementById("saveProjectInstructionsButton");
  const status=document.getElementById("projectInstructionsStatus");
  const instructions=String(input && input.value || "");
  if(save) save.disabled=true;
  if(status) status.textContent="Project Instructions 保存中...";
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}/instructions`, {{
      method:"PUT",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:cmd("project-instructions"),
        expected_project_revision:state.project.project_revision,
        instructions
      }})
    }});
    state.project=body.project;
    if(status) status.textContent=`Project Instructions 已保存 · Project R${{body.project.project_revision}}`;
    await resumeProject();
  }} catch(e) {{
    if(status) {{
      const detail=errorDetail(e);
      status.textContent=`Project Instructions STOP · ${{detail && detail.code ? detail.code : "ERROR"}}`;
    }}
    showError(e);
  }} finally {{
    renderProjectInstructions();
  }}
}}

function currentProjectSourceRows() {{
  return state.resume && Array.isArray(state.resume.sources) ? state.resume.sources : [];
}}

function projectLibraryTypeLabel(ref) {{
  const name=String(ref && ref.filename || "").toLowerCase();
  if(name.endsWith(".pdf")) return "PDF";
  if(name.endsWith(".docx")) return "DOCX";
  if(name.endsWith(".md")) return "Markdown";
  if(name.endsWith(".txt")) return "Text";
  return "Source";
}}

function projectLibraryOriginLabel(ref) {{
  if(ref && ref.origin_class === "PROJECT_DOCUMENT_BUNDLE") return "Document Bundle";
  if(ref && ref.origin_class === "PROJECT_UPLOAD") return "Project Upload";
  return String(ref && ref.origin_class || "Runtime Source");
}}

function useLibrarySource(sourceRefId) {{
  if(!state.project) return;
  const match=currentProjectSourceRows().find(item =>
    item.source_ref && item.source_ref.source_ref_id===sourceRefId
  );
  if(!match) return;
  state.source=match.source_ref;
  state.plainChatMode=false;
  const select=document.getElementById("projectSourceSwitcher");
  if(select) select.value=sourceRefId;
  const status=document.getElementById("projectLibraryStatus");
  if(status) status.textContent=`当前 Chat 已采用 Library Source：${{match.source_ref.filename}}。复用了既有 Runtime SourceRef，没有重新上传。`;
  renderCurrent();
}}

async function verifyLibrarySource(sourceRefId) {{
  if(!state.project) return;
  const match=currentProjectSourceRows().find(item =>
    item.source_ref && item.source_ref.source_ref_id===sourceRefId
  );
  if(!match) return;
  const status=document.getElementById("projectLibraryStatus");
  if(status) status.textContent=`正在验证：${{match.source_ref.filename}}`;
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}/sources/${{sourceRefId}}/verify`, {{
      method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{command_id:cmd("library-verify"), chat_id:state.chat ? state.chat.chat_id : null}})
    }});
    if(status) status.textContent=`PASS · ${{match.source_ref.filename}} · lines ${{body.line_count}} · exact source current`;
    await resumeProject();
  }} catch(e) {{
    if(status) status.textContent=`STOP · ${{match.source_ref.filename}} · Runtime currentness 未通过`;
    showError(e);
  }}
}}

function renderSemanticSearchResults(body) {{
  const root=document.getElementById("semanticSearchResults");
  if(!root) return;
  root.replaceChildren();
  const rows=body && Array.isArray(body.results) ? body.results : [];
  if(rows.length===0) {{
    const empty=document.createElement("div");
    empty.className="small";
    empty.textContent="没有可显示的语义搜索结果。";
    root.appendChild(empty);
    return;
  }}
  rows.forEach(row => {{
    const card=document.createElement("article");
    card.className="semantic-search-hit";
    card.dataset.sourceRefId=row.source_ref_id;
    const title=document.createElement("div");
    title.className="semantic-search-hit-title";
    title.textContent=`#${{row.rank}} · ${{row.filename}}`;
    const meta=document.createElement("div");
    meta.className="small semantic-search-hit-meta";
    meta.textContent=`score ${{Number(row.score).toFixed(4)}} · SHA ${{String(row.source_artifact_sha256 || "").slice(0,12)}} · Runtime current`;
    const excerpt=document.createElement("div");
    excerpt.className="small semantic-search-hit-excerpt";
    excerpt.textContent=row.excerpt || "";
    const use=document.createElement("button");
    use.type="button";
    use.textContent="用于当前 Chat";
    use.disabled=state.streaming || state.retryInFlight || Boolean(state.pendingPlainSend);
    use.addEventListener("click", () => useLibrarySource(row.source_ref_id));
    card.append(title, meta, excerpt, use);
    root.appendChild(card);
  }});
}}

async function searchProjectSources() {{
  const status=document.getElementById("semanticSearchStatus");
  const button=document.getElementById("semanticSearchButton");
  if(!state.project) {{
    if(status) status.textContent="请先打开一个 Project。";
    return;
  }}
  const query=(document.getElementById("semanticSearchQuery")?.value || "").trim();
  if(!query) {{
    if(status) status.textContent="请输入 Query。";
    return;
  }}
  const topK=Number(document.getElementById("semanticSearchTopK")?.value || "3");
  if(button) button.disabled=true;
  if(status) status.textContent="本地语义搜索中…";
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}/semantic-search`, {{
      method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{query, top_k:topK}})
    }});
    renderSemanticSearchResults(body);
    const count=Array.isArray(body.results) ? body.results.length : 0;
    if(status) status.textContent=`PASS · ${{count}} results · source-level · local FastEmbed · Runtime currentness revalidated`;
  }} catch(e) {{
    renderSemanticSearchResults({{results:[]}});
    if(status) status.textContent="STOP · semantic search 未通过 currentness / local component gate";
    showError(e);
  }} finally {{
    if(button) button.disabled=false;
  }}
}}

function renderProjectLibrary() {{
  const root=document.getElementById("projectLibraryList");
  if(!root) return;
  root.replaceChildren();
  const rows=currentProjectSourceRows();
  if(!state.project || rows.length===0) {{
    const empty=document.createElement("div");
    empty.className="library-empty";
    empty.textContent="当前 Project 还没有 Library Source。读入 TXT / MD / PDF / DOCX 后会出现在这里。";
    root.appendChild(empty);
    return;
  }}
  rows.forEach(item => {{
    const ref=item && item.source_ref;
    if(!ref || !ref.source_ref_id) return;
    const card=document.createElement("article");
    card.className="library-item";
    if(state.source && state.source.source_ref_id===ref.source_ref_id) card.classList.add("selected");

    const title=document.createElement("div");
    title.className="library-item-title";
    title.textContent=ref.filename || "Unnamed Source";

    const meta=document.createElement("div");
    meta.className="library-item-meta small";
    const sourceSha=ref.source_artifact_binding && ref.source_artifact_binding.sha256
      ? ref.source_artifact_binding.sha256.slice(0,12)
      : "unknown";
    const lines=item.text_derivation && Number.isInteger(item.text_derivation.line_count)
      ? ` · ${{item.text_derivation.line_count}} lines`
      : "";
    meta.textContent=`${{projectLibraryTypeLabel(ref)}} · ${{projectLibraryOriginLabel(ref)}} · SHA ${{sourceSha}}${{lines}}`;

    const actions=document.createElement("div");
    actions.className="library-actions";

    const useButton=document.createElement("button");
    useButton.type="button";
    useButton.textContent=state.source && state.source.source_ref_id===ref.source_ref_id ? "当前使用" : "用于当前 Chat";
    useButton.disabled=
      state.streaming ||
      state.retryInFlight ||
      Boolean(state.pendingSourceContextRetry) ||
      Boolean(state.pendingPlainSend);
    useButton.addEventListener("click", () => useLibrarySource(ref.source_ref_id));

    const verifyButton=document.createElement("button");
    verifyButton.type="button";
    verifyButton.textContent="Verify";
    verifyButton.disabled=state.streaming || state.retryInFlight;
    verifyButton.addEventListener("click", () => verifyLibrarySource(ref.source_ref_id));

    actions.append(useButton, verifyButton);
    card.append(title, meta, actions);
    root.appendChild(card);
  }});
}}

function renderProjectSourceSwitcher() {{
  const select=document.getElementById("projectSourceSwitcher");
  if(!select) return;
  const rows=currentProjectSourceRows();
  select.replaceChildren();
  if(!state.project) {{
    const option=document.createElement("option");
    option.value="";
    option.textContent="暂无 Project";
    select.appendChild(option);
    select.disabled=true;
    return;
  }}
  const plain=document.createElement("option");
  plain.value="";
  plain.textContent="普通 Chat（不使用 Source）";
  select.appendChild(plain);
  rows.forEach(item => {{
    const ref=item && item.source_ref;
    if(!ref || !ref.source_ref_id) return;
    const option=document.createElement("option");
    option.value=ref.source_ref_id;
    const sha=ref.source_artifact_binding && ref.source_artifact_binding.sha256
      ? ref.source_artifact_binding.sha256.slice(0,12)
      : "unknown-sha";
    option.textContent=`${{ref.filename}} · ${{sha}}`;
    select.appendChild(option);
  }});
  const currentId=state.source && state.source.source_ref_id;
  const match=currentId && rows.some(item => item.source_ref && item.source_ref.source_ref_id===currentId);
  if(state.plainChatMode || !match) select.value="";
  else select.value=currentId;
  select.disabled=
    state.streaming ||
    state.retryInFlight ||
    Boolean(state.pendingSourceContextRetry) ||
    Boolean(state.pendingPlainSend);
}}

function switchProjectSource() {{
  const select=document.getElementById("projectSourceSwitcher");
  if(!select || !state.project) return;
  const sourceRefId=select.value;
  if(sourceRefId==="") {{
    state.source=null;
    state.plainChatMode=true;
    const status=document.getElementById("projectLibraryStatus");
    if(status) status.textContent="当前 Chat 使用普通模式：不注入 Library Source；历史消息仍按 active branch context 读取。";
    renderCurrent();
    return;
  }}
  const match=currentProjectSourceRows().find(item =>
    item.source_ref && item.source_ref.source_ref_id===sourceRefId
  );
  if(!match) return;
  state.source=match.source_ref;
  state.plainChatMode=false;
  renderCurrent();
}}

function memoryMutationBlocked() {{
  return Boolean(
    !state.project ||
    state.streaming ||
    state.retryInFlight ||
    state.pendingPlainSend ||
    pendingFormalMatchesCurrent()
  );
}}

function renderProjectMemory() {{
  const root=document.getElementById("projectMemoryList");
  const status=document.getElementById("projectMemoryStatus");
  const contextStatus=document.getElementById("projectMemoryContextStatus");
  const createButton=document.getElementById("createProjectMemoryButton");
  const refreshButton=document.getElementById("refreshProjectMemoryButton");
  if(!root || !status || !contextStatus) return;
  root.replaceChildren();
  if(createButton) createButton.disabled=memoryMutationBlocked();
  if(refreshButton) refreshButton.disabled=!state.project;
  if(!state.project) {{
    status.textContent="选择 Project 后管理 Memory。";
    contextStatus.textContent="";
    return;
  }}
  const items=Array.isArray(state.projectMemory) ? state.projectMemory : [];
  status.textContent=items.length ? `Memory ${{items.length}} 条` : "当前 Project 尚无 Memory。";
  const ctx=state.projectMemoryContext || {{}};
  const stateBinding=ctx.state_binding || {{}};
  const stateArtifactId=stateBinding.artifact_id || "UNAVAILABLE";
  const stateRevision=Number.isInteger(stateBinding.revision) ? stateBinding.revision : "UNAVAILABLE";
  const stateSha=stateBinding.sha256 || "NONE_UNPERSISTED_R0";
  const guardSha=ctx.project_memory_state_guard_sha256 || "UNAVAILABLE";
  const contextSha=ctx.project_memory_context_sha256 || "NONE_ZERO_ACTIVE";
  contextStatus.textContent=
    `ACTIVE ${{Number(ctx.active_memory_count || 0)}} · ` +
    `State ${{stateArtifactId}} R${{stateRevision}} SHA ${{stateSha}} · ` +
    `State guard SHA ${{guardSha}} · Context SHA ${{contextSha}}`;
  for(const item of items) {{
    const card=document.createElement("article");
    card.className="library-item";
    const title=document.createElement("div");
    title.className="library-item-title";
    title.textContent=`${{item.lifecycle_state}} · ${{item.memory_id}}`;
    const meta=document.createElement("div");
    meta.className="small";
    meta.textContent=`Memory R${{item.memory_revision}} · item SHA ${{item.memory_item_sha256}} · ${{item.provenance && item.provenance.origin_class ? item.provenance.origin_class : "UNKNOWN"}}`;
    const edit=document.createElement("textarea");
    edit.id=`memory-edit-${{item.memory_id}}`;
    edit.value=item.content;
    edit.disabled=item.lifecycle_state==="DELETED" || memoryMutationBlocked();
    const actions=document.createElement("div");
    actions.className="library-actions";
    const save=document.createElement("button");
    save.type="button";save.textContent="保存";
    save.disabled=item.lifecycle_state==="DELETED" || memoryMutationBlocked();
    save.addEventListener("click",()=>saveProjectMemory(item.memory_id,item.memory_revision));
    const toggle=document.createElement("button");
    toggle.type="button";toggle.textContent=item.lifecycle_state==="ACTIVE" ? "停用" : "启用";
    toggle.disabled=item.lifecycle_state==="DELETED" || memoryMutationBlocked();
    toggle.addEventListener("click",()=>setProjectMemoryEnabled(item.memory_id,item.memory_revision,item.lifecycle_state!=="ACTIVE"));
    const del=document.createElement("button");
    del.type="button";del.textContent="删除";
    del.disabled=item.lifecycle_state==="DELETED" || memoryMutationBlocked();
    del.addEventListener("click",()=>deleteProjectMemory(item.memory_id,item.memory_revision));
    actions.append(save,toggle,del);
    card.append(title,meta,edit,actions);
    root.appendChild(card);
  }}
}}

async function refreshProjectMemory(silent=true) {{
  if(!state.project) {{
    state.projectMemory=[];state.projectMemoryContext=null;renderProjectMemory();return;
  }}
  try {{
    const [list,context]=await Promise.all([
      api(`/api/web/projects/${{state.project.project_id}}/memory`),
      api(`/api/web/projects/${{state.project.project_id}}/memory/context`)
    ]);
    state.projectMemory=Array.isArray(list.memories) ? list.memories : [];
    state.projectMemoryContext=context;
    renderProjectMemory();
  }} catch(e) {{
    if(!silent) showError(e);
    const status=document.getElementById("projectMemoryStatus");
    if(status) status.textContent=`Memory STOP · ${{errorDetail(e) && errorDetail(e).code ? errorDetail(e).code : "ERROR"}}`;
  }}
}}

async function createProjectMemory() {{
  if(memoryMutationBlocked()) return;
  const input=document.getElementById("projectMemoryInput");
  const content=input ? input.value.trim() : "";
  if(!content) return alert("Memory 内容不能为空");
  try {{
    await api(`/api/web/projects/${{state.project.project_id}}/memory`,{{
      method:"POST",headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{command_id:cmd("memory-create"),expected_project_revision:state.project.project_revision,content}})
    }});
    if(input) input.value="";
    await refreshProjectMemory(false);
  }} catch(e) {{ showError(e); }}
}}

async function saveProjectMemory(memoryId,memoryRevision) {{
  if(memoryMutationBlocked()) return;
  const edit=document.getElementById(`memory-edit-${{memoryId}}`);
  const content=edit ? edit.value.trim() : "";
  if(!content) return alert("Memory 内容不能为空");
  try {{
    await api(`/api/web/projects/${{state.project.project_id}}/memory/${{memoryId}}`,{{
      method:"PUT",headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{command_id:cmd("memory-revise"),expected_memory_revision:memoryRevision,content}})
    }});
    await refreshProjectMemory(false);
  }} catch(e) {{ showError(e); }}
}}

async function setProjectMemoryEnabled(memoryId,memoryRevision,enabled) {{
  if(memoryMutationBlocked()) return;
  try {{
    await api(`/api/web/projects/${{state.project.project_id}}/memory/${{memoryId}}/enabled`,{{
      method:"POST",headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{command_id:cmd(enabled ? "memory-enable" : "memory-disable"),expected_memory_revision:memoryRevision,enabled}})
    }});
    await refreshProjectMemory(false);
  }} catch(e) {{ showError(e); }}
}}

async function deleteProjectMemory(memoryId,memoryRevision) {{
  if(memoryMutationBlocked()) return;
  if(!window.confirm("删除会从当前 Project Memory active surface 移除该项；历史 Artifact revisions 仍保留，不等同于安全擦除。继续？")) return;
  try {{
    await api(`/api/web/projects/${{state.project.project_id}}/memory/${{memoryId}}`,{{
      method:"DELETE",headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{command_id:cmd("memory-delete"),expected_memory_revision:memoryRevision}})
    }});
    await refreshProjectMemory(false);
  }} catch(e) {{ showError(e); }}
}}

function renderCurrent() {{
  const p=state.project, c=state.chat, s=state.source;
  renderProjectInstructions();
  renderProjectMemory();
  renderProjectSourceSwitcher();
  renderProjectLibrary();
  document.getElementById("currentProject").textContent = p ? `${{p.display_name}} · ${{p.project_id}} · R${{p.project_revision}}` : "尚未选择";
  document.getElementById("chatView").textContent = c ? `${{c.title}} · ${{c.chat_id}} · R${{c.chat_revision}}` : "暂无 Chat";
  const streamButton=document.getElementById("streamApprovedButton");
  const pendingCurrent=pendingFormalMatchesCurrent();
  if(streamButton) streamButton.disabled=
    !pendingCurrent ||
    state.pendingFormal.approval_terminal_current!==true ||
    state.streaming;
  const stopButton=document.getElementById("stopStreamingButton");
  if(stopButton) stopButton.disabled=
    !state.streaming ||
    !state.activeStreamExecutionId ||
    state.stopRequested;
  const retryButton=document.getElementById("retryCancelledButton");
  if(retryButton) retryButton.disabled=
    !retryFormalMatchesCurrent() ||
    state.retryInFlight ||
    state.streaming ||
    pendingCurrent;
  const recoverRegenerateButton=document.getElementById("recoverRegenerateButton");
  if(recoverRegenerateButton) recoverRegenerateButton.disabled=
    !state.pendingRegenerate ||
    !c ||
    c.head_event_id!==state.pendingRegenerate.post_branch_head_event_id ||
    c.chat_revision!==state.pendingRegenerate.post_branch_chat_revision ||
    state.streaming ||
    state.retryInFlight ||
    pendingCurrent;
  const appendButton=document.getElementById("appendMessageButton");
  if(appendButton) {{
    appendButton.textContent=state.pendingPlainSend
      ? "恢复同一次批准并生成"
      : (!s ? "发送并批准一次生成" : "追加消息");
    appendButton.disabled=state.streaming || state.retryInFlight;
  }}
  const messageInput=document.getElementById("messageText");
  if(messageInput) messageInput.readOnly=Boolean(state.pendingPlainSend);
  const chatSwitcher=document.getElementById("chatSwitcher");
  if(chatSwitcher) chatSwitcher.disabled=
    state.streaming ||
    state.retryInFlight ||
    Boolean(state.pendingSourceContextRetry) ||
    Boolean(state.pendingPlainSend);
  const renameButton=document.getElementById("renameChatButton");
  if(renameButton) renameButton.disabled=
    !c ||
    state.streaming ||
    state.retryInFlight ||
    Boolean(state.pendingSourceContextRetry) ||
    Boolean(state.pendingPlainSend);
  const archiveButton=document.getElementById("archiveChatButton");
  if(archiveButton) {{
    archiveButton.textContent=c && chatLifecycleState(c) === "ARCHIVED" ? "取消归档当前 Chat" : "归档当前 Chat";
    archiveButton.disabled=
      !c ||
      state.streaming ||
      state.retryInFlight ||
      Boolean(state.pendingSourceContextRetry) ||
      Boolean(state.pendingPlainSend);
  }}
  const deleteButton=document.getElementById("deleteChatButton");
  if(deleteButton) deleteButton.disabled=
    !c ||
    state.streaming ||
    state.retryInFlight ||
    Boolean(state.pendingSourceContextRetry) ||
    Boolean(state.pendingPlainSend);

  const sourceUploadButton=document.getElementById("sourceUploadButton");
  if(sourceUploadButton) sourceUploadButton.disabled=
    !p ||
    !selectedSourceFile ||
    sourceUploadInFlight ||
    state.streaming ||
    state.retryInFlight ||
    Boolean(state.pendingPlainSend);

  // Project selection is independent of whether this Project currently has a Source.
  // Refresh the dashboard before the source-less early return.
  renderProjects();
  const semanticButton=document.getElementById("semanticSearchButton");
  if(semanticButton) semanticButton.disabled=(!state.project || currentProjectSourceRows().length===0);

  const sourceView = document.getElementById("sourceView");
  sourceView.replaceChildren();

  if (!s) {{
    const empty = document.createElement("span");
    empty.className = "small";
    empty.textContent = state.plainChatMode ? "普通 Chat · 不使用 Source" : "暂无 Source";
    sourceView.appendChild(empty);
    return;
  }}

  const sourceName = document.createElement("span");
  sourceName.textContent = s.filename;

  const lineBreak1 = document.createElement("br");

  const meta = document.createElement("span");
  meta.className = "small";
  const originLabel=s.origin_class==="PROJECT_DOCUMENT_BUNDLE" ? " · PDF/DOCX projection" : "";
  meta.textContent = `${{s.source_ref_id}} · SHA ${{s.source_artifact_binding.sha256}}${{originLabel}}`;

  const lineBreak2 = document.createElement("br");

  const verifyButton = document.createElement("button");
  verifyButton.type = "button";
  verifyButton.textContent = "确定性 Verify";
  verifyButton.addEventListener("click", verifySource);

  sourceView.append(sourceName, lineBreak1, meta, lineBreak2, verifyButton);
}}

async function createChat() {{
  if(!state.project) return alert("先选择 Project");
  if(state.pendingPlainSend) return alert("先恢复当前未完成的普通生成命令，避免切换 Chat scope。");
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}/chats`, {{
      method:"POST", headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:cmd("chat"),
        expected_project_revision:state.project.project_revision,
        title:document.getElementById("chatTitle").value
      }})
    }});
    state.project=body.project; state.chat=body.chat; resetChatHistorySearch(); await resumeProject();
  }} catch(e) {{ showError(e); }}
}}

async function renameCurrentChat() {{
  if(!state.project || !state.chat) return alert("先选择 Chat");
  if(state.streaming || state.retryInFlight || state.pendingSourceContextRetry || state.pendingPlainSend) {{
    return alert("当前执行/恢复状态下禁止重命名 Chat");
  }}
  const input=document.getElementById("renameChatTitle");
  const title=String(input && input.value || "").trim();
  if(!title) return alert("请输入新的 Chat 名称");
  try {{
    const chatId=state.chat.chat_id;
    const body=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{chatId}}/title`, {{
      method:"PUT",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:cmd("chat-rename"),
        expected_chat_revision:state.chat.chat_revision,
        title
      }})
    }});
    state.chat=body.chat;
    if(input) input.value="";
    await resumeProject();
  }} catch(e) {{ showError(e); }}
}}

async function toggleArchiveCurrentChat() {{
  if(!state.project || !state.chat) return alert("先选择 Chat");
  if(state.streaming || state.retryInFlight || state.pendingSourceContextRetry || state.pendingPlainSend) {{
    return alert("当前执行/恢复状态下禁止归档或取消归档 Chat");
  }}
  const archived=chatLifecycleState(state.chat) === "ARCHIVED";
  const action=archived ? "unarchive" : "archive";
  try {{
    const chatId=state.chat.chat_id;
    const body=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{chatId}}/${{action}}`, {{
      method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:cmd(archived ? "chat-unarchive" : "chat-archive"),
        expected_chat_revision:state.chat.chat_revision
      }})
    }});
    if(archived) state.chat=body.chat;
    else state.chat=null;
    await resumeProject();
  }} catch(e) {{ showError(e); }}
}}


async function deleteCurrentChat() {{
  if(!state.project || !state.chat) return alert("先选择 Chat");
  if(state.streaming || state.retryInFlight || state.pendingSourceContextRetry || state.pendingPlainSend) {{
    return alert("当前执行/恢复状态下禁止删除 Chat");
  }}
  const confirmed=window.confirm(
    "删除会把当前 Chat 从普通 Chat History / active product surface 移除。\\n" +
    "Runtime immutable audit/history 仍保留；这不是隐私擦除或安全删除。\\n\\n" +
    "确认删除当前 Chat？"
  );
  if(!confirmed) return;
  try {{
    const chatId=state.chat.chat_id;
    await api(`/api/web/projects/${{state.project.project_id}}/chats/${{chatId}}/delete`, {{
      method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:cmd("chat-delete"),
        expected_chat_revision:state.chat.chat_revision
      }})
    }});
    state.chat=null;
    state.branchState=null;
    state.pendingFormal=null;
    state.pendingRegenerate=null;
    state.retryFormal=null;
    clearConfirmedCancelRetryHint();
    await resumeProject();
  }} catch(e) {{ showError(e); }}
}}



function plainRegenerateEligible(binding) {{
  return Boolean(
    binding &&
    binding.ok===false &&
    binding.code==="REGENERATE_ORIGINAL_SOURCE_CARDINALITY_STOP" &&
    Array.isArray(binding.source_ref_ids) &&
    binding.source_ref_ids.length===0
  );
}}

function applyPlainRegeneratePrepared(body) {{
  const formal=body.formal || {{}};
  state.chat=body.chat || (body.branch && body.branch.chat) || state.chat;
  state.pendingRegenerate=null;
  state.pendingFormal={{
    project_id:state.project.project_id,
    chat_id:state.chat.chat_id,
    job_id:formal.job_id,
    decision_request_event_id:formal.decision_request_event_id,
    provider_execution_config_sha256:formal.provider_execution_config_sha256,
    job_bundle_binding:formal.job_bundle_binding,
    web_formal_job_intake_binding:formal.web_formal_job_intake_binding,
    source_context:null,
    source_context_sha256:null,
    initiating_user_event_id:body.event.event_id,
    accepted_chat_revision:state.chat.chat_revision,
    approval_terminal_current:true
  }};
  state.retryFormal=null; clearConfirmedCancelRetryHint();
  const status=document.getElementById("sourceContextStatus");
  if(status) status.textContent=`Plain Regenerate branch PASS · fresh job ${{formal.job_id}} · no Source provenance · APPROVED · starting one governed streaming attempt`;
}}

async function performPlainRegenerate(commandId, assistantEventId, expectedChatRevision) {{
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{state.chat.chat_id}}/messages/${{assistantEventId}}/regenerate-plain/send-and-approve`, {{
      method:"POST", headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:commandId,
        expected_chat_revision:expectedChatRevision
      }})
    }});
    if(
      body.result!=="PASS_PLAIN_REGENERATE_PREPARE_R001" ||
      body.predecessor_job_id===body.fresh_job_id ||
      body.source_context!==null ||
      body.source_context_sha256!==null ||
      !body.event ||
      body.event.related_source_ref_ids.length!==0 ||
      !body.formal ||
      body.formal.status!=="APPROVED_PLAIN_INITIAL_JOB" ||
      body.formal.approval_terminal_current!==true ||
      body.formal.human_action_trigger!=="EXPLICIT_PLAIN_REGENERATE_AND_APPROVE_ONE_GENERATION_CONFIRM" ||
      body.formal.provider_called!==false ||
      body.formal.network_called!==false ||
      body.formal.model_called!==false ||
      body.formal.secret_read!==false ||
      body.formal.grant_created!==false ||
      body.formal.attempt_claim_created!==false
    ) throw new Error("plain Regenerate prepare/approval identity mismatch");
    applyPlainRegeneratePrepared(body);
    await resumeProject();
    renderCurrent();
    await streamApprovedFormalJob();
    return true;
  }} catch(e) {{
    const detail=e.body && e.body.detail;
    if(detail && detail.code==="PLAIN_REGENERATE_POST_BRANCH_RECOVERABLE") {{
      const recovery=detail.recovery || {{}};
      if(detail.chat) state.chat=detail.chat;
      state.pendingRegenerate={{
        plain:true,
        command_id:recovery.retry_command_id,
        original_expected_chat_revision:recovery.original_expected_chat_revision,
        target_assistant_event_id:recovery.target_assistant_event_id,
        new_user_event_id:recovery.new_user_event_id,
        post_branch_chat_revision:recovery.post_branch_chat_revision,
        post_branch_head_event_id:recovery.post_branch_head_event_id
      }};
      const status=document.getElementById("sourceContextStatus");
      if(status) status.textContent=`Plain Regenerate prepare STOP · branch 已保留 · event ${{recovery.new_user_event_id}} · 恢复会复用 exact command，不会复制 USER_MESSAGE`;
      await resumeProject();
      renderCurrent();
      return false;
    }}
    throw e;
  }}
}}


function applyRegeneratePrepared(body) {{\n  const formal=body.formal || {{}};\n  state.chat=body.chat || (body.branch && body.branch.chat) || state.chat;\n  state.pendingRegenerate=null;\n  state.pendingFormal={{\n    project_id:state.project.project_id,\n    chat_id:state.chat.chat_id,\n    job_id:formal.job_id,\n    decision_request_event_id:formal.decision_request_event_id,\n    provider_execution_config_sha256:formal.provider_execution_config_sha256,\n    job_bundle_binding:formal.job_bundle_binding,\n    web_formal_job_intake_binding:formal.web_formal_job_intake_binding,\n    source_context:body.source_context,\n    source_context_sha256:body.source_context_sha256,\n    initiating_user_event_id:body.event.event_id,\n    accepted_chat_revision:state.chat.chat_revision,\n    approval_terminal_current:false\n  }};\n  state.retryFormal=null; clearConfirmedCancelRetryHint();\n  const status=document.getElementById("sourceContextStatus");\n  if(status) status.textContent=`Regenerate branch PASS · fresh job ${{formal.job_id}} · original USER Source provenance/current model policy pinned · 先显式批准，再执行`;\n}}\n\nasync function performRegeneratePrepare(commandId, assistantEventId, expectedChatRevision, sourceRefId) {{\n  try {{\n    const body=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{state.chat.chat_id}}/messages/${{assistantEventId}}/regenerate-source-grounded/prepare`, {{\n      method:"POST", headers:{{"Content-Type":"application/json"}},\n      body:JSON.stringify({{\n        command_id:commandId,\n        expected_chat_revision:expectedChatRevision,\n        source_ref_id:sourceRefId,\n        streaming:true\n      }})\n    }});\n    applyRegeneratePrepared(body);\n    await resumeProject();\n    renderCurrent();\n    return true;\n  }} catch(e) {{\n    const detail=e.body && e.body.detail;\n    if(detail && detail.code==="REGENERATE_POST_BRANCH_RECOVERABLE") {{\n      const recovery=detail.recovery || {{}};\n      if(detail.chat) state.chat=detail.chat;\n      state.pendingRegenerate={{\n        command_id:recovery.retry_command_id,\n        original_expected_chat_revision:recovery.original_expected_chat_revision,\n        target_assistant_event_id:recovery.target_assistant_event_id,\n        source_ref_id:recovery.source_ref_id,\n        new_user_event_id:recovery.new_user_event_id,\n        post_branch_chat_revision:recovery.post_branch_chat_revision,\n        post_branch_head_event_id:recovery.post_branch_head_event_id\n      }};\n      const status=document.getElementById("sourceContextStatus");\n      if(status) status.textContent=`Regenerate prepare STOP · branch 已保留 · event ${{recovery.new_user_event_id}} · 点击“恢复 Regenerate 准备”会复用 exact command，不会复制 USER_MESSAGE`;\n      await resumeProject();\n      renderCurrent();\n      return false;\n    }}\n    throw e;\n  }}\n}}\n\nasync function regenerateSuccessfulAssistant(event) {{\n  if(!state.project || !state.chat) return alert("Regenerate first slice 需要当前 Project/Chat");\n  if(branchActionBlocked() || state.pendingFormal) return alert("当前执行/恢复/待批准状态下禁止开始 Regenerate");\n  if(!event || event.event_id!==state.chat.head_event_id) return alert("只能 Regenerate 当前 successful Assistant leaf");\n\n  const originalBinding=regenerateSourceBindingForAssistant(event);\n  if(plainRegenerateEligible(originalBinding)) {{\n    const currentSelection=state.source;\n    const selectionNotice=currentSelection\n      ? `\\n当前 Library 选中的是：${{currentSelection.filename || currentSelection.source_ref_id}}；它不会用于本次 plain Regenerate。`\n      : "";\n    const disclosed=window.confirm(\n      `Regenerate 会创建一个新的 USER sibling branch，并显式批准一次 fresh generation。\\n` +\n      `原 USER provenance 是普通 Chat：0 个 SourceRef；本次不会注入当前 Library Source，也不会伪造 citation。${{selectionNotice}}\\n` +\n      `旧 Assistant branch / predecessor Job 会保留；这不是重放旧 Job。\\n\\n继续并批准一次生成？`\n    );\n    if(!disclosed) return;\n    const commandId=cmd("regenerate-plain");\n    try {{\n      await performPlainRegenerate(\n        commandId,\n        event.event_id,\n        state.chat.chat_revision\n      );\n    }} catch(e) {{ showError(e); }}\n    return;\n  }}\n  if(!originalBinding.ok) {{\n    return alert(`Regenerate STOP · original USER Source provenance unavailable/stale · ${{originalBinding.code}}`);\n  }}\n\n  const currentSelection=state.source;\n  const selectionChanged=Boolean(\n    currentSelection &&\n    currentSelection.source_ref_id!==originalBinding.source_ref_id\n  );\n  const selectionNotice=selectionChanged\n    ? `\\n当前 Library 选中的是：${{currentSelection.filename || currentSelection.source_ref_id}}；它不会用于本次 Regenerate。`\n    : "";\n\n  const disclosed=window.confirm(\n    `Regenerate 会创建一个新的 USER branch，并发起一个 fresh Job。\\n` +\n    `它严格复用原 USER provenance Source：${{originalBinding.source_ref.filename || originalBinding.source_ref_id}}。\\n` +\n    `当前 Library selection 不改变这个 Source 身份。${{selectionNotice}}\\n` +\n    `它使用当前 General Chat model policy；这不是重放旧 Job，旧 Assistant branch 会保留。\\n\\n继续？`\n  );\n  if(!disclosed) return;\n\n  const commandId=cmd("regenerate-source-grounded");\n  try {{\n    await performRegeneratePrepare(\n      commandId,\n      event.event_id,\n      state.chat.chat_revision,\n      originalBinding.source_ref_id\n    );\n  }} catch(e) {{ showError(e); }}\n}}\n\nasync function recoverRegeneratePrepare() {{\n  const pending=state.pendingRegenerate;\n  if(!pending || !state.project || !state.chat) return;\n  if(state.chat.head_event_id!==pending.post_branch_head_event_id || state.chat.chat_revision!==pending.post_branch_chat_revision) {{\n    state.pendingRegenerate=null;\n    renderCurrent();\n    return alert("Regenerate recovery 已 stale；当前 Chat/head/revision 已改变，禁止继续");\n  }}\n  try {{\n    if(pending.plain===true) {{\n      await performPlainRegenerate(\n        pending.command_id,\n        pending.target_assistant_event_id,\n        pending.original_expected_chat_revision\n      );\n    }} else {{\n      await performRegeneratePrepare(\n        pending.command_id,\n        pending.target_assistant_event_id,\n        pending.original_expected_chat_revision,\n        pending.source_ref_id\n      );\n    }}\n  }} catch(e) {{ showError(e); }}\n}}\n\nasync function refreshStreamingApprovalStatus(silent=true, expectedSnapshot=null) {{
  const snapshot=expectedSnapshot || currentPendingFormalSnapshot();
  if(!snapshot) {{
    renderCurrent();
    return false;
  }}

  const status=document.getElementById("sourceContextStatus");
  try {{
    const body=await api(
      `/api/web/projects/${{snapshot.project_id}}/chats/${{snapshot.chat_id}}/formal-model/stream-approval-status`,
      {{
        method:"POST",
        headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{
          command_id:cmd("formal-approval-status"),
          job_id:snapshot.job_id,
          decision_request_event_id:snapshot.decision_request_event_id
        }})
      }}
    );

    if(!pendingFormalSnapshotStillCurrent(snapshot)) {{
      renderCurrent();
      return false;
    }}

    const responseMatches=Boolean(
      body &&
      body.job_id===snapshot.job_id &&
      body.decision_request_event_id===snapshot.decision_request_event_id
    );
    const approved=Boolean(
      responseMatches &&
      body.approval_terminal_current===true
    );

    state.pendingFormal.approval_terminal_current=approved;
    if(status) {{
      status.textContent=approved
        ? `APPROVED exact terminal · job ${{snapshot.job_id}} · Runtime execution will revalidate currentness`
        : `${{responseMatches ? (body.status || "AWAITING_EXPLICIT_HUMAN_APPROVAL") : "APPROVAL_IDENTITY_MISMATCH"}} · job ${{snapshot.job_id}} · stream control remains disabled`;
    }}
    renderCurrent();
    return approved;
  }} catch(e) {{
    if(pendingFormalSnapshotStillCurrent(snapshot)) {{
      state.pendingFormal.approval_terminal_current=false;
      if(status) {{
        const detail=e.body && e.body.detail;
        const code=detail && detail.code ? detail.code : "APPROVAL_STATUS_UNAVAILABLE";
        status.textContent=`approval status STOP · ${{code}} · stream control remains disabled`;
      }}
    }}
    renderCurrent();
    if(!silent) showError(e);
    return false;
  }}
}}

async function appendMessage() {{
  if(!state.project || !state.chat) return alert("先创建 Chat");
  if(state.streaming) return alert("流式执行期间禁止修改当前 Chat；等待 final/error 终态后再继续。");
  const messageInput=document.getElementById("messageText");
  const content=messageInput.value;
  const attemptedChatId=state.chat.chat_id;
  const attemptedChatRevision=state.chat.chat_revision;
  const plainChatSend=!state.source;
  setMessageRecoveryStatus("");
  try {{
    let body;
    if(state.source) {{
      const pending=state.pendingSourceContextRetry;
      const exactRetry=Boolean(
        pending &&
        pending.project_id===state.project.project_id &&
        pending.chat_id===state.chat.chat_id &&
        pending.source_ref_id===state.source.source_ref_id &&
        pending.content===content
      );
      const contextCommandId=exactRetry ? pending.command_id : cmd("source-context");
      const contextExpectedRevision=exactRetry ? pending.expected_chat_revision : state.chat.chat_revision;
      let contextBody;
      try {{
        contextBody=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{state.chat.chat_id}}/source-context/prepare`, {{
          method:"POST", headers:{{"Content-Type":"application/json"}},
          body:JSON.stringify({{
            command_id:contextCommandId,
            expected_chat_revision:contextExpectedRevision,
            source_ref_id:state.source.source_ref_id,
            content:content
          }})
        }});
      }} catch(e) {{
        const detail=e.body && e.body.detail;
        if(detail && detail.code==="SOURCE_CONTEXT_POST_APPEND_RECOVERABLE") {{
          const recovery=detail.recovery || {{}};
          if(detail.chat) state.chat=detail.chat;
          state.pendingSourceContextRetry={{
            project_id:state.project.project_id,
            chat_id:state.chat.chat_id,
            source_ref_id:state.source.source_ref_id,
            content:content,
            command_id:recovery.retry_command_id,
            expected_chat_revision:recovery.original_expected_chat_revision,
            initiating_user_event_id:recovery.initiating_user_event_id,
            question_sha256:recovery.question_sha256
          }};
          persistPendingSourceContextRetryHint(state.pendingSourceContextRetry);
          document.getElementById("sourceContextStatus").textContent=`source context STOP · ${{recovery.reason_code}} · 用户消息已保留；reload 后也会按 exact Chat/Source/event 重新验证，同一 command 重试不会重复消息。`;
          renderCurrent(); await resumeProject();
          return;
        }}
        throw e;
      }}
      state.pendingSourceContextRetry=null;
      clearPendingSourceContextRetryHint();
      state.chat=contextBody.chat;
      document.getElementById("sourceContextStatus").textContent=`source context PASS · ${{contextBody.source_context_sha256}} · formal prepare...`;
      body=await api(`/api/web/projects/${{state.project.project_id}}/chats/${{state.chat.chat_id}}/formal-model/prepare`, {{
        method:"POST", headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{
          command_id:cmd("formal-prepare"),
          source_context:contextBody.source_context,
          source_context_sha256:contextBody.source_context_sha256,
          streaming:true
        }})
      }});
      state.pendingFormal={{
        project_id:state.project.project_id,
        chat_id:state.chat.chat_id,
        job_id:body.job_id,
        decision_request_event_id:body.decision_request_event_id,
        provider_execution_config_sha256:body.provider_execution_config_sha256,
        job_bundle_binding:body.job_bundle_binding,
        web_formal_job_intake_binding:body.web_formal_job_intake_binding,
        source_context:contextBody.source_context,
        source_context_sha256:contextBody.source_context_sha256,
        initiating_user_event_id:contextBody.source_context.initiating_user_event.event_id,
        accepted_chat_revision:state.chat.chat_revision,
        approval_terminal_current:false
      }};
      state.retryFormal=null; clearConfirmedCancelRetryHint();
      document.getElementById("sourceContextStatus").textContent=`${{body.status}} · streaming requested · job ${{body.job_id}} · 先完成显式批准，再点击“流式执行已批准 Job”`;
    }} else {{
      state.pendingSourceContextRetry=null;
      clearPendingSourceContextRetryHint();
      const existing=state.pendingPlainSend;
      if(existing && (
        existing.project_id!==state.project.project_id ||
        existing.chat_id!==state.chat.chat_id
      )) {{
        return alert("存在另一个 Chat 的未完成普通生成命令；先回到原 Chat 恢复，避免重复 USER turn。");
      }}
      const plainCommand=existing || {{
        project_id:state.project.project_id,
        chat_id:state.chat.chat_id,
        command_id:cmd("plain-send-approve"),
        expected_chat_revision:state.chat.chat_revision,
        content:content
      }};
      if(existing && content!==existing.content) {{
        return alert("当前 USER turn 已进入未完成恢复状态；请保持原文本并恢复同一次命令，避免创建第二条消息。");
      }}
      state.pendingPlainSend=plainCommand;
      renderCurrent();
      document.getElementById("sourceContextStatus").textContent="普通 Chat · 正在提交 exact USER turn + 显式批准一次生成；provider/network 尚未调用。";
      body=await api(`/api/web/projects/${{plainCommand.project_id}}/chats/${{plainCommand.chat_id}}/formal-model/plain/send-and-approve`, {{
        method:"POST", headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{
          command_id:plainCommand.command_id,
          expected_chat_revision:plainCommand.expected_chat_revision,
          content:plainCommand.content
        }})
      }});
      if(
        body.status!=="APPROVED_PLAIN_INITIAL_JOB" ||
        body.approval_terminal_current!==true ||
        body.human_action_trigger!=="EXPLICIT_SEND_AND_APPROVE_ONE_GENERATION_CLICK" ||
        body.provider_called!==false ||
        body.network_called!==false ||
        body.model_called!==false ||
        body.source_context!==null ||
        body.source_context_sha256!==null ||
        !Number.isInteger(body.project_memory_active_count) ||
        body.project_memory_active_count<0 ||
        (body.project_memory_active_count===0 && body.project_memory_context_sha256!==null) ||
        (body.project_memory_active_count>0 && !/^[0-9a-f]{{64}}$/.test(body.project_memory_context_sha256 || "")) ||
        !Array.isArray(body.project_memory_ids) ||
        body.project_memory_ids.length!==body.project_memory_active_count ||
        !body.event ||
        body.event.related_source_ref_ids.length!==0 ||
        !body.job_bundle_binding ||
        !body.web_formal_job_intake_binding
      ) throw new Error("plain Chat prepare/approval identity mismatch");
      state.pendingPlainSend=null;
      state.chat=body.chat;
      state.pendingFormal={{
        project_id:state.project.project_id,
        chat_id:state.chat.chat_id,
        job_id:body.job_id,
        decision_request_event_id:body.decision_request_event_id,
        provider_execution_config_sha256:body.provider_execution_config_sha256,
        job_bundle_binding:body.job_bundle_binding,
        web_formal_job_intake_binding:body.web_formal_job_intake_binding,
        source_context:null,
        source_context_sha256:null,
        project_memory_context_sha256:body.project_memory_context_sha256,
        project_memory_active_count:body.project_memory_active_count,
        project_memory_ids:body.project_memory_ids,
        initiating_user_event_id:body.event.event_id,
        accepted_chat_revision:state.chat.chat_revision,
        approval_terminal_current:true
      }};
      state.retryFormal=null; clearConfirmedCancelRetryHint();
      document.getElementById("sourceContextStatus").textContent=`APPROVED plain Job · ${{body.job_id}} · Memory ${{body.project_memory_active_count}} · ${{body.project_memory_context_sha256 ? body.project_memory_context_sha256.slice(0,12) : "none"}} · starting one governed streaming attempt`;
    }}
    if(body.chat) state.chat=body.chat;
    renderCurrent(); await resumeProject();
    if(plainChatSend && state.pendingFormal && state.pendingFormal.approval_terminal_current===true) {{
      await streamApprovedFormalJob();
    }}
  }} catch(e) {{
    if(plainChatSend && isStaleChatRevisionError(e)) {{
      state.pendingPlainSend=null;
      renderCurrent();
      if(await recoverStaleMessageSend(e, attemptedChatId, attemptedChatRevision)) return;
    }}
    if(plainChatSend && state.pendingPlainSend) {{
      setMessageRecoveryStatus("普通 Chat 未完成 · exact command 已在本页保留；再次点击“恢复同一次批准并生成”会 replay/validate 同一 USER turn，不会创建第二条消息。");
      renderCurrent();
    }}
    showError(e);
  }}
}}

function appendProvisionalAssistant() {{
  const container=document.getElementById("chatMessages");
  const wrapper=document.createElement("div");
  wrapper.className="chat-message assistant provisional";
  wrapper.dataset.provisionalStream="true";
  const meta=document.createElement("div");
  meta.className="meta";
  meta.textContent="ASSISTANT · streaming · PROVISIONAL / NON-AUTHORITY";
  const content=document.createElement("div");
  content.className="content";
  wrapper.append(meta,content);
  container.appendChild(wrapper);
  return {{wrapper,meta,content}};
}}

async function requestStopStreaming() {{
  const snapshot=currentPendingFormalSnapshot();
  if(!snapshot || !state.streaming || !state.activeStreamExecutionId) return;
  const executionId=state.activeStreamExecutionId;
  state.stopRequested=true;
  renderCurrent();
  try {{
    const body=await api(`/api/web/projects/${{snapshot.project_id}}/chats/${{snapshot.chat_id}}/formal-model/stop`, {{
      method:"POST", headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        job_id:snapshot.job_id,
        decision_request_event_id:snapshot.decision_request_event_id,
        execution_instance_id:executionId
      }})
    }});
    if(
      pendingFormalSnapshotStillCurrent(snapshot) &&
      state.activeStreamExecutionId===executionId
    ) {{
      const draft=document.querySelector('[data-provisional-stream="true"]');
      const meta=draft ? draft.querySelector('.meta') : null;
      if(meta) meta.textContent=`ASSISTANT · STOP requested · ${{body.status}} · awaiting Runtime confirmation`;
    }}
  }} catch(e) {{
    if(state.activeStreamExecutionId===executionId) state.stopRequested=false;
    renderCurrent();
    showError(e);
  }}
}}

async function retryCancelledFormal() {{
  const snapshot=currentRetryFormalSnapshot();
  if(!snapshot) return alert("没有与当前 Chat head 匹配的 confirmed-cancel Retry");
  if(state.retryInFlight || state.streaming || state.pendingFormal) return;
  state.retryInFlight=true;
  renderCurrent();
  try {{
    const body=await api(`/api/web/projects/${{snapshot.project_id}}/chats/${{snapshot.chat_id}}/formal-model/retry-after-confirmed-cancel`, {{
      method:"POST", headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        predecessor_job_id:snapshot.predecessor_job_id,
        predecessor_job_bundle_binding:snapshot.predecessor_job_bundle_binding,
        predecessor_web_formal_job_intake_binding:snapshot.predecessor_web_formal_job_intake_binding,
        predecessor_cancellation_outcome_binding:snapshot.predecessor_cancellation_outcome_binding,
        source_context:snapshot.source_context,
        source_context_sha256:snapshot.source_context_sha256,
        initiating_user_event_id:snapshot.initiating_user_event_id
      }})
    }});
    if(
      body.status!=="APPROVED_FRESH_RETRY_JOB" ||
      body.approval_terminal_current!==true ||
      body.predecessor_job_id!==snapshot.predecessor_job_id ||
      body.job_id===snapshot.predecessor_job_id ||
      body.predecessor_claim_replayed!==false ||
      body.predecessor_claim_refunded!==false ||
      body.provider_called!==false ||
      body.model_called!==false ||
      body.network_called!==false ||
      body.retry_context_mode!==snapshot.retry_mode ||
      !body.job_bundle_binding ||
      !body.web_formal_job_intake_binding
    ) throw new Error("fresh Retry preparation/approval identity mismatch");
    state.pendingFormal={{
      project_id:snapshot.project_id,
      chat_id:snapshot.chat_id,
      job_id:body.job_id,
      decision_request_event_id:body.decision_request_event_id,
      provider_execution_config_sha256:body.provider_execution_config_sha256,
      job_bundle_binding:body.job_bundle_binding,
      web_formal_job_intake_binding:body.web_formal_job_intake_binding,
      source_context:snapshot.source_context,
      source_context_sha256:snapshot.source_context_sha256,
      initiating_user_event_id:snapshot.initiating_user_event_id,
      accepted_chat_revision:snapshot.accepted_chat_revision,
      approval_terminal_current:true
    }};
    state.retryFormal=null; clearConfirmedCancelRetryHint();
    document.getElementById("sourceContextStatus").textContent=`APPROVED fresh ${{snapshot.retry_mode==="PLAIN" ? "plain " : ""}}Retry Job · ${{body.job_id}} · predecessor preserved · starting one governed streaming attempt`;
    renderCurrent();
    await streamApprovedFormalJob();
  }} catch(e) {{
    showError(e);
  }} finally {{
    state.retryInFlight=false;
    renderCurrent();
  }}
}}

async function streamApprovedFormalJob() {{
  if(!state.project || !state.chat || !state.pendingFormal) return alert("没有待执行的 Formal Job");
  const snapshot=currentPendingFormalSnapshot();
  if(!snapshot) return alert("待执行 Formal Job 不属于当前 Project/Chat");
  if(state.streaming) return;

  const approvalCurrent=await refreshStreamingApprovalStatus(true, snapshot);
  if(
    !approvalCurrent ||
    !pendingFormalSnapshotStillCurrent(snapshot)
  ) {{
    return alert("Approval JIT 检查期间当前 Project/Chat/Job/DRE 已变化或尚未 APPROVED；未调用 streaming endpoint。");
  }}

  const draft=appendProvisionalAssistant();
  state.streaming=true;
  state.activeStreamExecutionId=null;
  state.stopRequested=false;
  renderCurrent();
  let finalSeen=false;
  let terminalSeen=false;
  let cancelledSeen=false;
  let buffer="";
  let eventName="message";
  let dataLines=[];

  const dispatch=async () => {{
    if(!dataLines.length) {{ eventName="message"; return; }}
    const raw=dataLines.join("\\n");
    dataLines=[];
    const data=JSON.parse(raw);
    if(eventName==="open") {{
      if(
        data.project_id!==snapshot.project_id ||
        data.chat_id!==snapshot.chat_id ||
        data.job_id!==snapshot.job_id ||
        data.decision_request_event_id!==snapshot.decision_request_event_id ||
        typeof data.execution_instance_id!=="string" || !data.execution_instance_id
      ) throw new Error("stream open identity mismatch");
      state.activeStreamExecutionId=data.execution_instance_id;
      renderCurrent();
    }} else if(eventName==="delta") {{
      if(terminalSeen) {{ eventName="message"; return; }}
      if(typeof data.text!=="string" || !data.text) throw new Error("invalid streaming delta");
      draft.content.textContent+=data.text;
    }} else if(eventName==="final") {{
      terminalSeen=true;
      finalSeen=true;
      if(draft.content.textContent!==data.assistant_text) throw new Error("stream/final reconciliation mismatch");
      draft.meta.textContent="ASSISTANT · finalizing canonical Runtime projection";
      if(pendingFormalSnapshotStillPending(snapshot)) state.pendingFormal=null;
      draft.wrapper.remove();
      await resumeProject();
    }} else if(eventName==="cancelled") {{
      const cancelBinding=data.cancellation_receipt_binding;
      if(
        data.code!=="ATTEMPT_CLAIMED_CANCELLED_BY_USER" ||
        data.partial_output_persisted!==false ||
        data.retry_allowed!==false ||
        typeof data.cancellation_receipt_sha256!=="string" ||
        !cancelBinding ||
        typeof cancelBinding.artifact_identity_sha256!=="string" ||
        !Number.isInteger(cancelBinding.artifact_revision) || cancelBinding.artifact_revision<1 ||
        cancelBinding.artifact_sha256!==data.cancellation_receipt_sha256 ||
        !snapshot.job_bundle_binding ||
        !snapshot.web_formal_job_intake_binding ||
        typeof snapshot.initiating_user_event_id!=="string" ||
        !Number.isInteger(snapshot.accepted_chat_revision)
      ) throw new Error("invalid Runtime cancellation terminal");
      terminalSeen=true;
      cancelledSeen=true;
      const sourceRetry=Boolean(snapshot.source_context && typeof snapshot.source_context_sha256==="string");
      const plainRetry=Boolean(snapshot.source_context===null && snapshot.source_context_sha256===null);
      if(sourceRetry || plainRetry) {{
        state.retryFormal={{
          retry_mode:sourceRetry ? "SOURCE" : "PLAIN",
          project_id:snapshot.project_id,
          chat_id:snapshot.chat_id,
          predecessor_job_id:snapshot.job_id,
          predecessor_job_bundle_binding:snapshot.job_bundle_binding,
          predecessor_web_formal_job_intake_binding:snapshot.web_formal_job_intake_binding,
          predecessor_cancellation_outcome_binding:cancelBinding,
          source_context:snapshot.source_context,
          source_context_sha256:snapshot.source_context_sha256,
          initiating_user_event_id:snapshot.initiating_user_event_id,
          accepted_chat_revision:snapshot.accepted_chat_revision
        }};
        persistConfirmedCancelRetryHint(state.retryFormal);
      }} else {{
        state.retryFormal=null;
        clearConfirmedCancelRetryHint();
      }}
      if(pendingFormalSnapshotStillPending(snapshot)) state.pendingFormal=null;
      if(draft.wrapper.isConnected) draft.wrapper.remove();
      document.getElementById("sourceContextStatus").textContent=
        (sourceRetry || plainRetry)
          ? `STOPPED · Runtime cancellation confirmed · old attempt will not replay · 可点击『重试并批准一次生成』创建 fresh ${{plainRetry ? "plain " : ""}}Job`
          : "STOPPED · Runtime cancellation confirmed · old attempt will not replay";
      await resumeProject();
    }} else if(eventName==="error") {{
      terminalSeen=true;
      if(
        data.retry_allowed===false &&
        pendingFormalSnapshotStillPending(snapshot)
      ) state.pendingFormal=null;
      draft.meta.textContent=`STREAM STOP · ${{data.code || "UNKNOWN"}} · no automatic retry`;
      throw new Error(data.message || "streaming attempt stopped");
    }}
    eventName="message";
  }};

  try {{
    const response=await fetch(`/api/web/projects/${{snapshot.project_id}}/chats/${{snapshot.chat_id}}/formal-model/stream`, {{
      method:"POST",
      headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{
        command_id:cmd("formal-stream"),
        job_id:snapshot.job_id,
        decision_request_event_id:snapshot.decision_request_event_id
      }})
    }});
    if(!response.ok || !response.body) throw new Error(`stream HTTP ${{response.status}}`);
    const reader=response.body.getReader();
    const decoder=new TextDecoder("utf-8");
    while(true) {{
      const part=await reader.read();
      if(part.done) break;
      buffer+=decoder.decode(part.value,{{stream:true}});
      while(buffer.includes("\\n")) {{
        const idx=buffer.indexOf("\\n");
        const line=buffer.slice(0,idx).replace(/\\r$/,"");
        buffer=buffer.slice(idx+1);
        if(line.startsWith("event:")) eventName=line.slice(6).trim();
        else if(line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
        else if(line==="") await dispatch();
      }}
    }}
    buffer+=decoder.decode();
    if(buffer.trim()) {{
      for(const line of buffer.split(/\\r?\\n/)) {{
        if(line.startsWith("event:")) eventName=line.slice(6).trim();
        else if(line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }}
    }}
    await dispatch();
    if(!terminalSeen) throw new Error("stream ended without Runtime terminal event; do not retry automatically");
  }} catch(e) {{
    if(!finalSeen && !cancelledSeen) {{
      if(pendingFormalSnapshotStillPending(snapshot)) state.pendingFormal=null;
      if(draft.wrapper.isConnected) draft.wrapper.remove();
      try {{ await resumeProject(); }} catch(_resumeError) {{}}
    }}
    showError(e);
  }} finally {{
    state.streaming=false;
    state.activeStreamExecutionId=null;
    state.stopRequested=false;
    renderCurrent();
  }}
}}

function sourceFileKind(file) {{
  if(!file || !file.name) return null;
  const name=file.name.toLowerCase();
  if(name.endsWith(".txt") || name.endsWith(".md")) return "text";
  if(name.endsWith(".pdf") || name.endsWith(".docx")) return "document";
  return null;
}}

function isSupportedSourceFile(file) {{
  return sourceFileKind(file)!==null;
}}

function renderSourceSelection(message) {{
  document.getElementById("sourceSelection").textContent=message;
}}

function acceptSourceFiles(files) {{
  if(!files || files.length === 0) {{
    selectedSourceFile=null;
    renderSourceSelection("尚未选择文件");
    return false;
  }}
  if(files.length !== 1) {{
    selectedSourceFile=null;
    renderSourceSelection("一次只允许选择一个 TXT / MD / PDF / DOCX 文件");
    alert("一次只允许选择一个 TXT / MD / PDF / DOCX 文件");
    return false;
  }}
  const file=files[0];
  if(!isSupportedSourceFile(file)) {{
    selectedSourceFile=null;
    document.getElementById("sourceFile").value="";
    renderSourceSelection("仅支持 .txt / .md / .pdf / .docx");
    alert("仅支持 TXT / MD / PDF / DOCX 文件");
    return false;
  }}
  selectedSourceFile=file;
  const type=file.type || "unknown-type";
  renderSourceSelection(`${{file.name}} · ${{file.size}} bytes · ${{type}} · 等待点击“读入 exact bytes”`);
  return true;
}}

function configureSourceDropZone() {{
  const input=document.getElementById("sourceFile");
  const zone=document.getElementById("sourceDropZone");

  input.addEventListener("change", () => acceptSourceFiles(input.files));
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("keydown", (event) => {{
    if(event.key === "Enter" || event.key === " ") {{
      event.preventDefault();
      input.click();
    }}
  }});
  zone.addEventListener("dragover", (event) => {{
    event.preventDefault();
    zone.classList.add("dragover");
  }});
  zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone.addEventListener("drop", (event) => {{
    event.preventDefault();
    zone.classList.remove("dragover");
    acceptSourceFiles(event.dataTransfer ? event.dataTransfer.files : null);
  }});
}}

async function uploadSource() {{
  if(!state.project) return alert("先选择 Project");
  if(state.pendingPlainSend) return alert("先恢复当前未完成的普通生成命令，再改变 Source scope。");
  if(sourceUploadInFlight) return;
  const file=selectedSourceFile;
  if(!file) return alert("请先拖入或选择一个 TXT/MD/PDF/DOCX 文件");
  const kind=sourceFileKind(file);
  if(!kind) return alert("仅支持 TXT / MD / PDF / DOCX 文件");
  sourceUploadInFlight=true;
  renderCurrent();
  try {{
    const bytes=await file.arrayBuffer();
    const commandId=cmd(kind==="document" ? "ingest-document" : "ingest");
    const q=new URLSearchParams({{
      command_id:commandId,
      filename:file.name,
      expected_project_revision:String(state.project.project_revision)
    }});
    if(state.chat) q.set("chat_id", state.chat.chat_id);
    const endpoint=kind==="document"
      ? `/api/web/projects/${{state.project.project_id}}/sources/document?${{q}}`
      : `/api/web/projects/${{state.project.project_id}}/sources/text?${{q}}`;
    renderSourceSelection(
      kind==="document"
        ? `本地解析中：${{file.name}} · ${{file.size}} bytes · network/model 禁用`
        : `读入中：${{file.name}} · ${{file.size}} bytes`
    );
    const body=await api(endpoint, {{
      method:"POST",
      headers:{{"Content-Type":"application/octet-stream"}},
      body:bytes
    }});
    state.project=body.project; state.source=body.source_ref; state.plainChatMode=false;
    const origin=body.source_ref && body.source_ref.origin_class==="PROJECT_DOCUMENT_BUNDLE"
      ? " · Document Bundle provenance 已绑定"
      : "";
    renderSourceSelection(`已采用：${{file.name}} · ${{file.size}} bytes${{origin}}`);
    renderCurrent();
    await resumeProject();
  }} catch(e) {{
    renderSourceSelection(`未完成：${{file.name}} · 正在重新读取 Runtime state；不会自动重试`);
    showError(e);
    try {{ await resumeProject(); }} catch(_resumeError) {{}}
  }} finally {{
    sourceUploadInFlight=false;
    renderCurrent();
  }}
}}

async function verifySource() {{
  if(!state.project || !state.source) return;
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}/sources/${{state.source.source_ref_id}}/verify`, {{
      method:"POST", headers:{{"Content-Type":"application/json"}},
      body:JSON.stringify({{command_id:cmd("verify"), chat_id:state.chat ? state.chat.chat_id : null}})
    }});
    alert(`PASS · source ${{body.source_sha256}} · lines ${{body.line_count}} · formal_job=${{body.formal_job}}`);
    await resumeProject();
  }} catch(e) {{ showError(e); }}
}}

async function resumeProject() {{
  if(!state.project) return;
  try {{
    const body=await api(`/api/web/projects/${{state.project.project_id}}`);
    rehydratePendingSourceContextRetry(body);
    const pending=state.pendingSourceContextRetry;
    const plainPending=state.pendingPlainSend && state.pendingPlainSend.project_id===state.project.project_id
      ? state.pendingPlainSend
      : null;
    const desiredChatId=pending ? pending.chat_id : (plainPending ? plainPending.chat_id : (state.chat ? state.chat.chat_id : null));
    const desiredSourceRefId=pending ? pending.source_ref_id : (state.source ? state.source.source_ref_id : null);
    const preservePlain=Boolean(!pending && (plainPending || state.plainChatMode));
    state.resume=body;
    state.project=body.project;
    await refreshProjectMemory(true);

    const chatMatch=desiredChatId && body.chats ? body.chats.find(item => item.chat && item.chat.chat_id===desiredChatId) : null;
    const sourceMatch=desiredSourceRefId && body.sources ? body.sources.find(item => item.source_ref && item.source_ref.source_ref_id===desiredSourceRefId) : null;

    if(pending && (!chatMatch || !sourceMatch)) {{
      const status=document.getElementById("sourceContextStatus");
      if(status) status.textContent="source context STOP · pending retry exact Chat/Source is unavailable; keep the same command and recover currentness before retry.";
      renderCurrent(); renderChatMessages(); renderResume(body);
      return;
    }}

    if(chatMatch) state.chat=chatMatch.chat;
    else state.chat=firstVisibleChat(body.chats || []);

    if(preservePlain) {{
      state.source=null;
      state.plainChatMode=true;
    }} else if(sourceMatch) {{
      state.source=sourceMatch.source_ref;
      state.plainChatMode=false;
    }} else if(body.sources && body.sources.length) {{
      state.source=body.sources[0].source_ref;
      state.plainChatMode=false;
    }} else {{
      state.source=null;
      state.plainChatMode=true;
    }}

    if(!pending && !plainPending) rehydrateConfirmedCancelRetryHint(body);
    await refreshBranchState(true);
    renderCurrent(); renderChatMessages(); renderResume(body);
    if(state.retryFormal && retryFormalMatchesCurrent()) {{
      const status=document.getElementById("sourceContextStatus");
      if(status && !status.textContent.includes("STOPPED")) status.textContent="confirmed-cancel Retry 已恢复；不会自动重试，点击时 Runtime 仍会重新验证 exact predecessor/currentness。";
    }}
    await refreshStreamingApprovalStatus(true);
  }} catch(e) {{ showError(e); }}
}}
function renderResume(body) {{
  document.getElementById("resumeView").textContent=JSON.stringify(body,null,2);
  renderChatSwitcher();
}}
window.addEventListener("focus", () => {{
  void refreshStreamingApprovalStatus(true);
}});
document.addEventListener("visibilitychange", () => {{
  if(document.visibilityState==="visible") void refreshStreamingApprovalStatus(true);
}});
configureSourceDropZone();
loadProjects();
</script>
</body>
</html>"""
