"""Narrow one-claim/one-call/no-replay composition boundary for Web R004.

P1-S3 adds one bounded same-process STOP coordination object for the existing synchronous
streaming path.  It is deliberately not a generic lifecycle/cancellation subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import threading
from typing import Any, Callable

from universal_runtime.core.formal_model_job import FormalModelJobLedger, utc_now
from universal_runtime.core.model_catalog import ResolvedModelExecution
from universal_runtime.core.provider_execution_config import ProviderExecutionConfig


class FormalLiveCompositionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class P1S3CancellationSignal(RuntimeError):
    """Internal control signal only; Runtime Authority is the persisted cancellation receipt."""

    def __init__(self, winner: str):
        super().__init__(winner)
        self.winner = winner


class P1S3StopControlError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_P1S3_CANCEL_WINNERS = frozenset({"CANCEL_BEFORE_REQUEST", "CANCEL_ACTIVE_STREAM"})
_P1S3_PROVIDER_WINNERS = frozenset({"PROVIDER_SUCCESS", "PROVIDER_FAILURE"})
_P1S3_CLOSE_OBSERVATION_TIMEOUT_SECONDS = 0.25
_P1S3_PHASES = frozenset(
    {
        "PRE_CLAIM",
        "CLAIMED_REQUEST_NOT_STARTED",
        "REQUEST_INVOCATION_STARTED_STREAM_HANDLE_NOT_AVAILABLE",
        "STREAM_ACTIVE",
        "PROVIDER_TERMINAL_OBSERVED",
        "WORKER_TERMINAL",
    }
)


class P1S3StopControl:
    """One process-local control for exactly one Project/Chat/Job/DRE execution instance.

    The object stores only coordination state and an exact close hook.  It stores no credential,
    request/response bytes, visible partial text, reasoning text, or canonical Assistant content.
    """

    def __init__(
        self,
        *,
        project_id: str,
        chat_id: str,
        job_id: str,
        decision_request_event_id: str,
        execution_instance_id: str,
    ) -> None:
        for value, label in (
            (project_id, "project_id"),
            (chat_id, "chat_id"),
            (job_id, "job_id"),
            (decision_request_event_id, "decision_request_event_id"),
            (execution_instance_id, "execution_instance_id"),
        ):
            if not isinstance(value, str) or not value:
                raise P1S3StopControlError("INVALID_STOP_CONTROL_IDENTITY", f"{label} must be non-empty")
        self.project_id = project_id
        self.chat_id = chat_id
        self.job_id = job_id
        self.decision_request_event_id = decision_request_event_id
        self.execution_instance_id = execution_instance_id
        self._state_lock = threading.RLock()
        self._claim_gate = threading.Lock()
        self._claim_gate_held_by_worker = False
        self._phase = "PRE_CLAIM"
        self._stop_requested = False
        self._terminal_winner: str | None = None
        self._stream_handle: Any | None = None
        self._close_hook: Callable[[], Any] | None = None
        self._close_started = False
        self._close_observation = "NOT_INVOKED"
        self._close_observation_timeout_seconds = _P1S3_CLOSE_OBSERVATION_TIMEOUT_SECONDS
        self._close_done = threading.Event()
        self._execution_binding_sha256: str | None = None
        self._claim_binding_sha256: str | None = None

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (
            self.project_id,
            self.chat_id,
            self.job_id,
            self.decision_request_event_id,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "project_id": self.project_id,
                "chat_id": self.chat_id,
                "job_id": self.job_id,
                "decision_request_event_id": self.decision_request_event_id,
                "execution_instance_id": self.execution_instance_id,
                "phase": self._phase,
                "stop_requested": self._stop_requested,
                "terminal_winner": self._terminal_winner,
                "close_started": self._close_started,
                "close_observation": self._close_observation,
                "close_observation_timeout_seconds": self._close_observation_timeout_seconds,
                "execution_binding_sha256": self._execution_binding_sha256,
                "claim_binding_sha256": self._claim_binding_sha256,
            }

    def begin_claim_gate(self) -> bool:
        """Linearize pre-claim STOP against Grant/Execution/Claim creation."""
        self._claim_gate.acquire()
        with self._state_lock:
            self._claim_gate_held_by_worker = True
            if self._phase != "PRE_CLAIM":
                self._claim_gate_held_by_worker = False
                self._claim_gate.release()
                raise P1S3StopControlError(
                    "STOP_CONTROL_PHASE_INVALID",
                    "claim gate may start only in PRE_CLAIM",
                )
            if self._stop_requested:
                self._claim_gate_held_by_worker = False
                self._claim_gate.release()
                return False
            return True

    def finish_claim_gate(
        self,
        *,
        execution_binding_sha256: str,
        claim_binding_sha256: str,
    ) -> None:
        with self._state_lock:
            if not self._claim_gate_held_by_worker:
                raise P1S3StopControlError("STOP_CONTROL_CLAIM_GATE", "claim gate is not held")
            self._execution_binding_sha256 = execution_binding_sha256
            self._claim_binding_sha256 = claim_binding_sha256
            self._phase = "CLAIMED_REQUEST_NOT_STARTED"
            self._claim_gate_held_by_worker = False
        self._claim_gate.release()

    def abort_claim_gate(self) -> None:
        release = False
        with self._state_lock:
            if self._claim_gate_held_by_worker:
                self._claim_gate_held_by_worker = False
                release = True
        if release:
            self._claim_gate.release()

    def request_stop(self, *, execution_instance_id: str) -> dict[str, Any]:
        """Accept one non-authoritative STOP command for the exact execution instance."""
        if execution_instance_id != self.execution_instance_id:
            return {
                "status": "STOP_EXECUTION_INSTANCE_MISMATCH",
                "stop_requested": False,
                "cancellation_confirmed": False,
            }

        # The same gate linearizes STOP-before-claim versus successful claim commit.
        with self._claim_gate:
            dispatch_close = False
            with self._state_lock:
                if self._phase == "WORKER_TERMINAL":
                    return {
                        "status": "NO_ACTIVE_EXECUTION",
                        "stop_requested": False,
                        "cancellation_confirmed": False,
                    }
                if self._terminal_winner in _P1S3_PROVIDER_WINNERS or self._phase == "PROVIDER_TERMINAL_OBSERVED":
                    return {
                        "status": "STOP_TOO_LATE",
                        "stop_requested": False,
                        "cancellation_confirmed": False,
                    }

                self._stop_requested = True
                if self._phase == "PRE_CLAIM":
                    status = "STOP_REQUEST_ACCEPTED_PRECLAIM"
                elif self._phase == "CLAIMED_REQUEST_NOT_STARTED":
                    if self._terminal_winner is None:
                        self._terminal_winner = "CANCEL_BEFORE_REQUEST"
                    status = "STOP_REQUEST_ACCEPTED_PENDING_CONFIRMATION"
                elif self._phase == "REQUEST_INVOCATION_STARTED_STREAM_HANDLE_NOT_AVAILABLE":
                    status = "STOP_REQUEST_ACCEPTED_PENDING_CONFIRMATION"
                elif self._phase == "STREAM_ACTIVE":
                    dispatch_close = self._close_hook is not None and not self._close_started
                    status = "STOP_REQUEST_ACCEPTED_PENDING_CONFIRMATION"
                else:
                    status = "STOP_REQUEST_ACCEPTED_PENDING_CONFIRMATION"

            if dispatch_close:
                self._dispatch_close()

        return {
            "status": status,
            "stop_requested": True,
            "cancellation_confirmed": False,
        }

    def cancellation_winner(self) -> str | None:
        with self._state_lock:
            if self._terminal_winner in _P1S3_CANCEL_WINNERS:
                return self._terminal_winner
            return None

    def provider_winner(self) -> str | None:
        with self._state_lock:
            if self._terminal_winner in _P1S3_PROVIDER_WINNERS:
                return self._terminal_winner
            return None

    def mark_request_invocation_started(self) -> bool:
        with self._state_lock:
            if self._terminal_winner in _P1S3_CANCEL_WINNERS:
                return False
            if self._phase != "CLAIMED_REQUEST_NOT_STARTED":
                raise P1S3StopControlError(
                    "STOP_CONTROL_PHASE_INVALID",
                    "provider request may start only after claimed request-not-started phase",
                )
            self._phase = "REQUEST_INVOCATION_STARTED_STREAM_HANDLE_NOT_AVAILABLE"
            return True

    def register_stream_handle(
        self,
        *,
        execution_instance_id: str,
        stream_handle: Any,
        close_hook: Callable[[], Any],
    ) -> None:
        if execution_instance_id != self.execution_instance_id:
            raise P1S3StopControlError(
                "STOP_EXECUTION_INSTANCE_MISMATCH",
                "stream hook registration execution instance mismatch",
            )
        if stream_handle is None or not callable(close_hook):
            raise P1S3StopControlError("STOP_STREAM_HOOK_INVALID", "exact stream handle/close hook required")
        dispatch_close = False
        with self._state_lock:
            if self._phase != "REQUEST_INVOCATION_STARTED_STREAM_HANDLE_NOT_AVAILABLE":
                raise P1S3StopControlError(
                    "STOP_CONTROL_PHASE_INVALID",
                    "stream handle may register only after provider invocation starts",
                )
            if self._stream_handle is not None or self._close_hook is not None:
                raise P1S3StopControlError(
                    "STOP_STREAM_HOOK_ALREADY_REGISTERED",
                    "active stream hook cannot be overwritten",
                )
            self._stream_handle = stream_handle
            self._close_hook = close_hook
            self._phase = "STREAM_ACTIVE"
            dispatch_close = self._stop_requested and self._terminal_winner is None
        if dispatch_close:
            self._dispatch_close()

    def _dispatch_close(self) -> bool:
        with self._state_lock:
            if self._close_started or self._close_hook is None:
                return False
            if self._phase != "STREAM_ACTIVE" or self._terminal_winner in _P1S3_PROVIDER_WINNERS:
                return False
            self._close_started = True
            self._close_observation = "INVOKED_PENDING"
            hook = self._close_hook

        def run_close() -> None:
            try:
                hook()
            except BaseException:
                with self._state_lock:
                    if self._close_observation == "INVOKED_PENDING":
                        self._close_observation = "RAISED_FIXED_LOCAL_CLASSIFICATION"
                self._close_done.set()
                return
            with self._state_lock:
                if self._close_observation == "INVOKED_PENDING":
                    self._close_observation = "RETURNED"
                    if self._terminal_winner is None:
                        self._terminal_winner = "CANCEL_ACTIVE_STREAM"
            self._close_done.set()

        def observe_close_bound() -> None:
            if self._close_done.wait(self._close_observation_timeout_seconds):
                return
            with self._state_lock:
                if self._close_observation == "INVOKED_PENDING":
                    self._close_observation = "TIMED_OUT_UNCONFIRMED"
                    self._close_done.set()

        threading.Thread(
            target=run_close,
            name="ur-p1-s3-stop-close",
            daemon=True,
        ).start()
        threading.Thread(
            target=observe_close_bound,
            name="ur-p1-s3-stop-close-observer",
            daemon=True,
        ).start()
        return True

    def mark_provider_success(self) -> bool:
        with self._state_lock:
            if self._terminal_winner is None:
                self._terminal_winner = "PROVIDER_SUCCESS"
                self._phase = "PROVIDER_TERMINAL_OBSERVED"
                return True
            return self._terminal_winner == "PROVIDER_SUCCESS"

    def mark_provider_failure(self) -> bool:
        with self._state_lock:
            if self._terminal_winner is None:
                self._terminal_winner = "PROVIDER_FAILURE"
                self._phase = "PROVIDER_TERMINAL_OBSERVED"
                return True
            return self._terminal_winner == "PROVIDER_FAILURE"

    def close_observation(self) -> str:
        with self._state_lock:
            return self._close_observation

    def mark_worker_terminal(self) -> None:
        with self._state_lock:
            self._phase = "WORKER_TERMINAL"
            self._stream_handle = None
            self._close_hook = None


class P1S3StopControlRegistry:
    """One narrow in-process registry for the P1-S3 synchronous Web streaming execution."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[tuple[str, str, str, str], P1S3StopControl] = {}

    def register(
        self,
        *,
        project_id: str,
        chat_id: str,
        job_id: str,
        decision_request_event_id: str,
        execution_instance_id: str,
    ) -> P1S3StopControl:
        control = P1S3StopControl(
            project_id=project_id,
            chat_id=chat_id,
            job_id=job_id,
            decision_request_event_id=decision_request_event_id,
            execution_instance_id=execution_instance_id,
        )
        with self._lock:
            existing = self._items.get(control.key)
            if existing is not None and existing.snapshot()["phase"] != "WORKER_TERMINAL":
                raise P1S3StopControlError(
                    "STREAM_EXECUTION_ALREADY_ACTIVE",
                    "exact Project/Chat/Job/DRE already has an active owner",
                )
            self._items[control.key] = control
        return control

    def lookup(
        self,
        *,
        project_id: str,
        chat_id: str,
        job_id: str,
        decision_request_event_id: str,
        execution_instance_id: str,
    ) -> P1S3StopControl | None:
        key = (project_id, chat_id, job_id, decision_request_event_id)
        with self._lock:
            control = self._items.get(key)
            if control is None or control.execution_instance_id != execution_instance_id:
                return None
            return control

    def release(
        self,
        *,
        project_id: str,
        chat_id: str,
        job_id: str,
        decision_request_event_id: str,
        execution_instance_id: str,
    ) -> bool:
        key = (project_id, chat_id, job_id, decision_request_event_id)
        with self._lock:
            control = self._items.get(key)
            if control is None or control.execution_instance_id != execution_instance_id:
                return False
            control.mark_worker_terminal()
            del self._items[key]
            return True

    def active_count(self) -> int:
        with self._lock:
            return len(self._items)


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise FormalLiveCompositionError("INVALID_SHA", f"{name} must be lowercase 64-hex")
    return value


@dataclass(frozen=True)
class ProviderAttemptResult:
    assistant_text: str
    request_payload_sha256: str
    response_payload_sha256: str
    transport_status: str
    transport_evidence_sha256: str
    transport_retries_observed: int = 0
    fallback_observed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.assistant_text, str) or not self.assistant_text:
            raise FormalLiveCompositionError(
                "INVALID_PROVIDER_RESULT", "assistant_text must be non-empty"
            )
        for name in (
            "request_payload_sha256",
            "response_payload_sha256",
            "transport_evidence_sha256",
        ):
            _sha(getattr(self, name), name)
        if self.transport_status != "LIVE_SUCCESS":
            raise FormalLiveCompositionError(
                "INVALID_TRANSPORT_STATUS", "first live path requires LIVE_SUCCESS"
            )
        if self.transport_retries_observed != 0:
            raise FormalLiveCompositionError("RETRY_FORBIDDEN", "transport retries must be 0")
        if self.fallback_observed is not False:
            raise FormalLiveCompositionError("FALLBACK_FORBIDDEN", "fallback must be false")
        expected = hashlib.sha256(self.assistant_text.encode("utf-8")).hexdigest()
        if self.response_payload_sha256 != expected:
            raise FormalLiveCompositionError(
                "RESPONSE_OUTPUT_MISMATCH",
                "response_payload_sha256 must bind exact assistant projection bytes",
            )


def execute_one_formal_model_attempt(
    ledger: FormalModelJobLedger,
    *,
    job_id: str,
    job_bundle_sha256: str,
    execution_binding: dict | None,
    grant_binding: dict | None,
    authority_binding: dict,
    model_resolution: ResolvedModelExecution,
    provider_execution_config: ProviderExecutionConfig,
    assert_job_authority_current: Callable[[], None],
    assert_human_approval_current: Callable[[], None],
    assert_provider_config_current: Callable[[ProviderExecutionConfig], None],
    resolve_credential: Callable[[str, str], str],
    issue_provider_request: Callable[[ProviderExecutionConfig, ResolvedModelExecution, str], ProviderAttemptResult],
    now: Callable[[], str] = utc_now,
    stop_control: P1S3StopControl | None = None,
    prepare_execution_bindings: Callable[[], tuple[dict[str, Any], dict[str, Any]]] | None = None,
) -> dict:
    """Issue at most one provider call, only after a newly committed attempt claim.

    When ``stop_control`` is supplied, Grant/Execution/Claim creation may be linearized through
    ``prepare_execution_bindings`` so a pre-claim STOP does not fabricate a Grant or Claim.
    """

    if not isinstance(model_resolution, ResolvedModelExecution):
        raise FormalLiveCompositionError(
            "INVALID_MODEL_RESOLUTION", "formal live composition requires ResolvedModelExecution"
        )
    if not isinstance(provider_execution_config, ProviderExecutionConfig):
        raise FormalLiveCompositionError("INVALID_PROVIDER_CONFIG", "invalid provider config type")
    try:
        provider_execution_config.assert_matches_resolution(
            provider=model_resolution.provider,
            resolved_model_entry_id=model_resolution.model_entry_id,
            model_resolution_sha256=model_resolution.resolution_sha256,
        )
    except BaseException as exc:
        raise FormalLiveCompositionError(
            "MODEL_RESOLUTION_MISMATCH",
            "provider config does not bind the exact current ResolvedModelExecution",
        ) from exc

    model_resolution_sha256 = model_resolution.resolution_sha256
    config_sha = provider_execution_config.semantic_sha256

    claim_gate_started = False
    try:
        if stop_control is not None:
            if prepare_execution_bindings is None:
                raise FormalLiveCompositionError(
                    "STOP_EXECUTION_BINDING_PREPARER_REQUIRED",
                    "P1-S3 STOP path requires claim-gated execution binding preparation",
                )
            if execution_binding is not None or grant_binding is not None:
                raise FormalLiveCompositionError(
                    "STOP_EXECUTION_BINDING_CONFLICT",
                    "P1-S3 STOP path must create Grant/Execution inside the claim gate",
                )
            if not stop_control.begin_claim_gate():
                return {
                    "status": "STOPPED_BEFORE_CLAIM_NO_ATTEMPT",
                    "may_issue_provider_request": False,
                    "claim_binding": None,
                }
            claim_gate_started = True
            grant_binding, execution_binding = prepare_execution_bindings()
        elif execution_binding is None or grant_binding is None:
            raise FormalLiveCompositionError(
                "EXECUTION_BINDING_REQUIRED",
                "formal live composition requires exact Grant/Execution bindings",
            )

        claim_result = ledger.claim_attempt(
            job_id=job_id,
            job_bundle_sha256=job_bundle_sha256,
            execution_binding=execution_binding,
            grant_binding=grant_binding,
            authority_binding=authority_binding,
            model_resolution_sha256=model_resolution_sha256,
            provider_execution_config_sha256=config_sha,
        )
        if claim_result["status"] != "NEWLY_COMMITTED_CLAIM":
            if stop_control is not None:
                stop_control.abort_claim_gate()
                claim_gate_started = False
            return {
                "status": claim_result["status"],
                "may_issue_provider_request": False,
                "claim_binding": claim_result["claim_binding"],
            }
        claim_binding = claim_result["claim_binding"]
        if stop_control is not None:
            stop_control.finish_claim_gate(
                execution_binding_sha256=execution_binding["artifact_sha256"],
                claim_binding_sha256=claim_binding["artifact_sha256"],
            )
            claim_gate_started = False
    except BaseException:
        if stop_control is not None and claim_gate_started:
            stop_control.abort_claim_gate()
        raise

    def persist_failure(stage: str, code: str, provider_request_started: bool) -> None:
        try:
            ledger.persist_claimed_attempt_failure_outcome(
                job_id=job_id,
                job_bundle_sha256=job_bundle_sha256,
                execution_binding=execution_binding,
                grant_binding=grant_binding,
                claim_binding=claim_binding,
                model_resolution_sha256=model_resolution_sha256,
                provider_execution_config_sha256=config_sha,
                failure_stage=stage,
                failure_code=code,
                provider_request_invocation_started=provider_request_started,
                failure_observed_at_utc=now(),
            )
        except BaseException as receipt_exc:
            raise FormalLiveCompositionError(
                "ATTEMPT_FAILURE_OUTCOME_PERSIST_FAILED",
                "claim remains consumed; failure outcome receipt could not be persisted",
            ) from receipt_exc

    def persist_cancellation(winner: str, provider_request_started: bool) -> dict[str, Any]:
        if stop_control is None or winner not in _P1S3_CANCEL_WINNERS:
            raise FormalLiveCompositionError(
                "CANCELLATION_CONTROL_INVALID",
                "confirmed cancellation requires exact P1-S3 StopControl winner",
            )
        observation = stop_control.close_observation()
        # One bounded deterministic replay is Artifact create-once recovery only; never a provider retry.
        last_exc: BaseException | None = None
        for _attempt in range(2):
            try:
                receipt, binding = ledger.persist_claimed_attempt_cancellation_outcome(
                    job_id=job_id,
                    job_bundle_sha256=job_bundle_sha256,
                    execution_binding=execution_binding,
                    grant_binding=grant_binding,
                    claim_binding=claim_binding,
                    model_resolution_sha256=model_resolution_sha256,
                    provider_execution_config_sha256=config_sha,
                    cancellation_winner=winner,
                    provider_request_invocation_started=provider_request_started,
                    stream_close_observation=(
                        "NOT_REQUIRED_BEFORE_REQUEST"
                        if winner == "CANCEL_BEFORE_REQUEST"
                        else observation
                    ),
                    cancellation_observed_at_utc=now(),
                )
                return {
                    "status": "ATTEMPT_CLAIMED_CANCELLED_BY_USER",
                    "may_issue_provider_request": False,
                    "claim_binding": claim_binding,
                    "cancellation_outcome": receipt,
                    "cancellation_outcome_binding": binding,
                }
            except BaseException as exc:
                last_exc = exc
        raise FormalLiveCompositionError(
            "ATTEMPT_CANCELLATION_OUTCOME_PERSIST_FAILED",
            "claim remains consumed; confirmed cancellation receipt could not be proven",
        ) from last_exc

    try:
        assert_job_authority_current()
        assert_human_approval_current()
        assert_provider_config_current(provider_execution_config)
    except BaseException as exc:
        winner = stop_control.cancellation_winner() if stop_control is not None else None
        if winner is not None:
            return persist_cancellation(winner, False)
        persist_failure(
            "CURRENTNESS_REVALIDATION",
            "CLAIM_CONSUMED_REQUEST_BLOCKED_STALE",
            False,
        )
        raise FormalLiveCompositionError(
            "CLAIM_CONSUMED_REQUEST_BLOCKED_STALE",
            "claim remains consumed; final authority/approval/config currentness failed",
        ) from exc

    winner = stop_control.cancellation_winner() if stop_control is not None else None
    if winner is not None:
        return persist_cancellation(winner, False)

    started_at = now()
    secret: str | None = None
    failure_stage = "CREDENTIAL_RESOLUTION"
    provider_request_started = False
    try:
        secret = resolve_credential(
            provider_execution_config.credential_ref_id,
            provider_execution_config.credential_ref_class,
        )
        if not isinstance(secret, str) or not secret:
            raise FormalLiveCompositionError(
                "ATTEMPT_CLAIMED_OUTCOME_UNKNOWN",
                "credential resolution failed after claim commit",
            )

        failure_stage = "PROVIDER_REQUEST"
        if stop_control is not None:
            if not stop_control.mark_request_invocation_started():
                winner = stop_control.cancellation_winner()
                if winner is None:
                    raise FormalLiveCompositionError(
                        "STOP_ARBITRATION_INVALID",
                        "provider request was blocked without a cancellation winner",
                    )
                return persist_cancellation(winner, False)
        provider_request_started = True
        attempt_result = issue_provider_request(provider_execution_config, model_resolution, secret)

        failure_stage = "PROVIDER_RESULT_VALIDATION"
        if not isinstance(attempt_result, ProviderAttemptResult):
            raise FormalLiveCompositionError(
                "INVALID_PROVIDER_RESULT",
                "provider request must return ProviderAttemptResult",
            )
    except P1S3CancellationSignal as exc:
        winner = stop_control.cancellation_winner() if stop_control is not None else None
        if winner != exc.winner or winner not in _P1S3_CANCEL_WINNERS:
            raise FormalLiveCompositionError(
                "STOP_ARBITRATION_INVALID",
                "provider adapter cancellation signal lacks the exact StopControl winner",
            ) from exc
        return persist_cancellation(winner, provider_request_started)
    except BaseException as exc:
        winner = stop_control.cancellation_winner() if stop_control is not None else None
        if winner is not None:
            return persist_cancellation(winner, provider_request_started)
        fixed_failure_code = {
            "CREDENTIAL_RESOLUTION": "ATTEMPT_CLAIMED_CREDENTIAL_RESOLUTION_FAILED",
            "PROVIDER_REQUEST": "ATTEMPT_CLAIMED_PROVIDER_REQUEST_FAILED",
            "PROVIDER_RESULT_VALIDATION": "ATTEMPT_CLAIMED_PROVIDER_RESULT_VALIDATION_FAILED",
        }[failure_stage]
        persist_failure(
            failure_stage,
            fixed_failure_code,
            provider_request_started,
        )
        if isinstance(exc, FormalLiveCompositionError):
            raise
        raise FormalLiveCompositionError(
            "ATTEMPT_CLAIMED_OUTCOME_UNKNOWN",
            "provider attempt failed after claim commit; automatic replay is forbidden",
        ) from exc
    finally:
        secret = None

    if stop_control is not None and stop_control.cancellation_winner() is not None:
        return persist_cancellation(stop_control.cancellation_winner(), provider_request_started)

    finished_at = now()
    try:
        output_record, output_binding = ledger.persist_assistant_output(
            job_id=job_id,
            text=attempt_result.assistant_text,
        )
        if output_binding["artifact_sha256"] != attempt_result.response_payload_sha256:
            raise FormalLiveCompositionError(
                "RESPONSE_OUTPUT_MISMATCH", "persisted output differs from response payload SHA"
            )

        attempt_record, attempt_binding = ledger.persist_model_attempt_receipt(
            job_id=job_id,
            job_bundle_sha256=job_bundle_sha256,
            execution_binding=execution_binding,
            grant_binding=grant_binding,
            claim_binding=claim_binding,
            request_payload_sha256=attempt_result.request_payload_sha256,
            response_payload_sha256=attempt_result.response_payload_sha256,
            started_at_utc=started_at,
            finished_at_utc=finished_at,
            transport_status=attempt_result.transport_status,
            transport_evidence_sha256=attempt_result.transport_evidence_sha256,
            transport_retries_observed=attempt_result.transport_retries_observed,
            fallback_observed=attempt_result.fallback_observed,
        )
        consumption_record, consumption_binding = ledger.persist_consumption_receipt(
            job_id=job_id,
            job_bundle_sha256=job_bundle_sha256,
            grant_binding=grant_binding,
            claim_binding=claim_binding,
            attempt_binding=attempt_binding,
        )
        formal_result, formal_result_binding = ledger.persist_formal_result_commit(
            job_id=job_id,
            job_bundle_sha256=job_bundle_sha256,
            execution_binding=execution_binding,
            grant_binding=grant_binding,
            claim_binding=claim_binding,
            attempt_binding=attempt_binding,
            consumption_binding=consumption_binding,
            assistant_output_binding=output_binding,
            authority_binding=authority_binding,
            model_resolution_sha256=model_resolution_sha256,
            provider_execution_config_sha256=config_sha,
        )
    except BaseException as exc:
        persist_failure(
            "RESULT_PERSISTENCE",
            "ATTEMPT_CLAIMED_RESULT_PERSISTENCE_FAILED",
            True,
        )
        if isinstance(exc, FormalLiveCompositionError):
            raise
        raise FormalLiveCompositionError(
            "ATTEMPT_CLAIMED_OUTCOME_UNKNOWN",
            "formal result persistence failed after claim commit; automatic replay is forbidden",
        ) from exc

    return {
        "status": "FORMAL_MODEL_RESULT_COMMITTED",
        "may_issue_provider_request": False,
        "claim_binding": claim_binding,
        "assistant_output": output_record,
        "attempt_receipt": attempt_record,
        "attempt_binding": attempt_binding,
        "consumption_receipt": consumption_record,
        "formal_result_commit": formal_result,
        "formal_result_commit_binding": formal_result_binding,
    }
