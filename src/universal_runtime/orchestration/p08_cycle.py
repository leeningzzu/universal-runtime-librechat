"""Runtime-owned P08 -> P08A -> P08B shadow orchestration.

The module deliberately keeps the frozen Core and Schema contracts untouched.
It adapts the local helper models at this boundary, validates the frozen JSON
shapes deterministically, persists P08A bytes before review, authorizes every
P08B input through D03, and lets D02 (never a model verdict) select the route.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.core.enums import GateVerdict, PersistenceClass
from universal_runtime.core.fresh_context import (
    FreshContextInput,
    FreshContextRequest,
    ProvenanceClass,
    authorize_fresh_context,
)
from universal_runtime.core.hashing import sha256_text
from universal_runtime.core.load_plan import LoadInput, LoadPlan, ParseMode
from universal_runtime.core.models import (
    ArtifactManifest,
    P08GateResult,
    P08StructureDraft,
    P08WorkflowInput,
    P08WorkflowResult,
    PersistedDraft,
)
from universal_runtime.core.routing import RoutingContext, RouteDecision, route_review
from universal_runtime.core.file_resolver import FileResolver, FileResolutionError
from universal_runtime.core.fresh_context import _secret_path
from universal_runtime.models.deepseek import DeepSeekAgentFactory
from universal_runtime.models.profiles import load_model_profile
from universal_runtime.prompts.reference_loader import PromptReferenceLoader


FORMAL_PROMPT_BINDINGS: dict[str, tuple[str, str]] = {
    "P08": (
        "P08_V01_MAP_MACRO_TO_UNITS_CHAT.md",
        "aabee3a93875762a0c5999ddecce8b2f35d7f1c0f5d6a16ed5807be65f3f0c65",
    ),
    "P08B": (
        "P08B_V01_STRUCTURE_GATE_CHAT.md",
        "edc84a9373af8cd1d309d354cac15e4d04246d5abf958f01cdd7a102688cd298",
    ),
}
RUNTIME_SCHEMA_BINDINGS: dict[str, str] = {
    "P08": "p08_structure_draft.schema.json",
    "P08B": "p08_gate_result.schema.json",
}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REVISE_ACTION = "P08 / ACTION_ID = P08_MAP_CURRENT_PARENT"
_FORMAL_DIR_NAMES = frozenset({"current", "canon", "ledger", "status", "publish", "published"})


def load_runtime_schema(project_root: Path, contract_name: str) -> dict[str, Any]:
    """Load one frozen D01 schema as the sole execution-contract authority."""
    try:
        filename = RUNTIME_SCHEMA_BINDINGS[contract_name]
    except KeyError as exc:
        raise ValueError(f"unknown Runtime schema contract: {contract_name}") from exc
    path = (project_root / "schemas" / filename).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Runtime schema is missing: {path}")
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Runtime schema is not valid JSON: {path}") from exc
    if not isinstance(schema, dict):
        raise ValueError(f"Runtime schema must be a JSON object: {path}")
    return schema


def build_structured_agent_instructions(
    formal_prompt: str,
    schema: Mapping[str, Any],
    contract_name: str,
) -> str:
    """Append provider-neutral JSON execution wiring to exact formal prompt text.

    The formal prompt remains the first, byte-for-byte-identifiable portion.  The
    appended envelope is Runtime-owned wiring only; its contract text is a stable
    serialization of the frozen D01 schema supplied by the caller.
    """
    if not isinstance(formal_prompt, str) or not formal_prompt:
        raise ValueError("formal prompt content is required")
    if not isinstance(schema, Mapping):
        raise ValueError("Runtime schema must be a mapping")
    stable_schema = json.dumps(dict(schema), ensure_ascii=False, sort_keys=True, indent=2)
    semantic_mapping = ""
    if contract_name == "P08":
        semantic_mapping = (
            "Historical MAP_DRAFT_KEEP/SPLIT semantics map to the schema decision KEEP/SPLIT; "
            "place the complete MAP_DRAFT content inside draft_markdown.\n"
        )
    elif contract_name == "P08B":
        semantic_mapping = (
            "Historical STRUCTURE_GATE_PASS, REVISE, and HISTORY_BOUNDARY_BLOCKER semantics map "
            "to verdict PASS, REVISE, and HISTORY_BOUNDARY_BLOCKER respectively; reviewed_sha256 "
            "must echo the supplied persisted Candidate SHA exactly. return_action is model metadata; "
            "routing remains outside this response.\n"
        )
    envelope = (
        "[RUNTIME EXECUTION FORMAT - NON-AUTHORITY]\n"
        "Return only one valid json object.\n"
        "Do not return Markdown fences.\n"
        "Do not add prose before or after the json object.\n"
        f"The json object must satisfy the frozen Runtime-owned {contract_name} contract below.\n"
        f"{semantic_mapping}"
        "The Runtime schema below is the D01 source of truth for this execution; do not add, omit, or rename fields.\n"
        f"Runtime schema ({contract_name}):\n"
        f"{stable_schema}\n"
    )
    return f"{formal_prompt}\n\n{envelope}"


@dataclass(frozen=True)
class P08DraftCandidate:
    parent_id: str
    decision: str
    draft_markdown: str
    source_coverage_summary: str
    unit_boundaries: tuple[dict[str, str], ...]
    history_boundary_blocker: str | None

    def model_dump(self) -> dict[str, Any]:
        return {
            "parent_id": self.parent_id,
            "decision": self.decision,
            "draft_markdown": self.draft_markdown,
            "source_coverage_summary": self.source_coverage_summary,
            "unit_boundaries": [dict(item) for item in self.unit_boundaries],
            "history_boundary_blocker": self.history_boundary_blocker,
        }

    def model_dump_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class P08BGateCandidate:
    verdict: str
    reviewed_sha256: str
    summary: str
    revision_targets: tuple[str, ...]
    blocker_details: dict[str, str] | None
    return_action: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reviewed_sha256": self.reviewed_sha256,
            "summary": self.summary,
            "revision_targets": list(self.revision_targets),
            "blocker_details": self.blocker_details,
            "return_action": self.return_action,
        }

    def model_dump_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, separators=(",", ":"))


def _payload(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, Mapping):
        raise ValueError("structured model output must be a JSON object")
    return value


def validate_p08_output(value: Any) -> P08DraftCandidate:
    """Validate the frozen D01 P08 schema without adding a dependency."""
    data = dict(_payload(value))
    required = {
        "parent_id", "decision", "draft_markdown", "source_coverage_summary",
        "unit_boundaries", "history_boundary_blocker",
    }
    if set(data) != required:
        raise ValueError("P08 output does not match the frozen schema")
    if not isinstance(data["parent_id"], str) or not data["parent_id"]:
        raise ValueError("P08 parent_id is required")
    if data["decision"] not in {"KEEP", "SPLIT"}:
        raise ValueError("P08 decision must be KEEP or SPLIT")
    if not isinstance(data["draft_markdown"], str) or not data["draft_markdown"]:
        raise ValueError("P08 draft_markdown is required")
    if not isinstance(data["source_coverage_summary"], str) or not data["source_coverage_summary"]:
        raise ValueError("P08 source_coverage_summary is required")
    units = data["unit_boundaries"]
    if not isinstance(units, list) or not units:
        raise ValueError("P08 unit_boundaries is required")
    normalized: list[dict[str, str]] = []
    for unit in units:
        if not isinstance(unit, Mapping) or set(unit) != {"unit_id", "source_start_anchor", "source_end_anchor"}:
            raise ValueError("P08 unit boundary is malformed")
        if any(not isinstance(unit[key], str) or not unit[key] for key in unit):
            raise ValueError("P08 unit boundary values are required")
        normalized.append({key: unit[key] for key in ("unit_id", "source_start_anchor", "source_end_anchor")})
    blocker = data["history_boundary_blocker"]
    if blocker is not None and (not isinstance(blocker, str) or not blocker):
        raise ValueError("P08 history_boundary_blocker is malformed")
    return P08DraftCandidate(data["parent_id"], data["decision"], data["draft_markdown"], data["source_coverage_summary"], tuple(normalized), blocker)


def validate_p08b_output(value: Any) -> P08BGateCandidate:
    """Validate the frozen D01 P08B schema, including verdict branches."""
    data = dict(_payload(value))
    required = {"verdict", "reviewed_sha256", "summary", "revision_targets", "blocker_details", "return_action"}
    if set(data) != required:
        raise ValueError("P08B output does not match the frozen schema")
    verdict = data["verdict"]
    if verdict not in {"PASS", "REVISE", "HISTORY_BOUNDARY_BLOCKER"}:
        raise ValueError("unknown P08B verdict")
    sha = data["reviewed_sha256"]
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ValueError("reviewed_sha256 must be lowercase 64-hex")
    if not isinstance(data["summary"], str) or not data["summary"]:
        raise ValueError("P08B summary is required")
    targets = data["revision_targets"]
    if not isinstance(targets, list) or any(not isinstance(item, str) or not item for item in targets):
        raise ValueError("P08B revision_targets is malformed")
    blocker = data["blocker_details"]
    if blocker is not None and (
        not isinstance(blocker, Mapping)
        or set(blocker) != {"missing_input", "reason", "required_return_interface"}
        or any(not isinstance(blocker[key], str) or not blocker[key] for key in blocker)
    ):
        raise ValueError("P08B blocker_details is malformed")
    action = data["return_action"]
    if not isinstance(action, str) or not action:
        raise ValueError("P08B return_action is required")
    if verdict == "PASS" and (targets or blocker is not None):
        raise ValueError("PASS cannot carry revision targets or blocker details")
    if verdict == "REVISE" and (not targets or blocker is not None or action != _REVISE_ACTION):
        raise ValueError("REVISE contract is malformed")
    if verdict == "HISTORY_BOUNDARY_BLOCKER" and (targets or not isinstance(blocker, Mapping) or action != "STOP / REQUIRED_RETURN_INTERFACE"):
        raise ValueError("HISTORY_BOUNDARY_BLOCKER contract is malformed")
    return P08BGateCandidate(verdict, sha, data["summary"], tuple(targets), blocker, action)


def _as_public_gate(candidate: P08BGateCandidate) -> P08GateResult:
    gate = P08GateResult(
        verdict=GateVerdict(candidate.verdict),
        reviewed_sha256=candidate.reviewed_sha256,
        summary=candidate.summary,
        revision_targets=list(candidate.revision_targets),
        blocker_details=None,
    )
    # Preserve the frozen-schema field for callers without changing the public Core model.
    if candidate.blocker_details is not None:
        object.__setattr__(gate, "blocker_details", dict(candidate.blocker_details))
    object.__setattr__(gate, "return_action", candidate.return_action)
    return gate


def load_formal_prompts(project_root: Path, *, prompt_root: Path | None = None) -> dict[str, Any]:
    """Load P08/P08B only through the Phase-B imported prompt authority."""
    root = (prompt_root or (project_root / "workspace" / "imports" / "tianxiabo_prompts")).resolve()
    resolver = FileResolver([root], allowed_extensions=(".md",))
    refs = [
        LoadInput(reference=str(root / name), role=f"formal_{key.lower()}_prompt", expected_sha256=sha, parse_mode=ParseMode.MARKDOWN, persistence_class=PersistenceClass.AUDIT)
        for key, (name, sha) in FORMAL_PROMPT_BINDINGS.items()
    ]
    plan = LoadPlan.from_inputs(plan_id="e01-formal-p08-prompts", project_root=str(project_root.resolve()), allowed_roots=(str(root),), required_inputs=refs)
    loader = PromptReferenceLoader(resolver)
    return {key: loader.load(root / name, sha, parse_mode=ParseMode.MARKDOWN, plan=plan, provenance=f"FORMAL_{key}_PROMPT") for key, (name, sha) in FORMAL_PROMPT_BINDINGS.items()}


def enforce_shadow_output_root(job: P08WorkflowInput, authorized_shadow_root: Path | None) -> Path:
    """Fail closed unless this is an explicitly authorized Runtime Shadow root."""
    if job.shadow_only is not True:
        raise PermissionError("P08 E01 jobs must set shadow_only=true")
    if authorized_shadow_root is None:
        raise PermissionError("an explicitly authorized Runtime Shadow output root is required")
    root = Path(authorized_shadow_root).resolve()
    output = Path(job.output_dir).resolve()
    if output != root and root not in output.parents:
        raise PermissionError("output root is outside the authorized Runtime Shadow root")
    forbidden = {part.lower() for part in output.parts} & _FORMAL_DIR_NAMES
    if forbidden:
        raise PermissionError("formal Runtime directories are not valid Shadow output targets")
    if "tianxiabo" in {part.lower() for part in output.parts} and "shadow" not in {part.lower() for part in output.parts}:
        raise PermissionError("TianxiaBo formal roots are not valid Shadow output targets")
    return output


def persist_p08a(
    store: ArtifactStore,
    job: P08WorkflowInput,
    draft: P08StructureDraft | P08DraftCandidate | Mapping[str, Any],
    *,
    authorized_shadow_root: Path | None = None,
) -> tuple[PersistedDraft, ArtifactManifest]:
    """Deterministically persist the exact P08 draft bytes and create a revision."""
    if job.shadow_only is not True:
        raise PermissionError("P08A requires shadow_only=true")
    if authorized_shadow_root is not None:
        enforce_shadow_output_root(job, authorized_shadow_root)
    # Even the legacy helper model is re-validated against the frozen schema;
    # its missing ``unit_boundaries`` field must not silently widen authority.
    candidate = validate_p08_output(draft)
    artifact_id = f"{job.parent_id}_STRUCTURE_DRAFT"
    relative = f"tianxiabo_shadow/structure_drafts/{job.parent_id}_STRUCTURE_DRAFT.md"
    fingerprint = sha256_text(job.model_dump_json(exclude={"output_dir"}))
    manifest = store.persist_exact_text(
        artifact_id=artifact_id,
        relative_path=relative,
        text=candidate.draft_markdown,
        job_id=job.job_id,
        persistence_class=PersistenceClass.WORKING,
        input_fingerprint=fingerprint,
        metadata={"parent_id": job.parent_id, "shadow_only": True, "action": "P08A"},
    )
    persisted = PersistedDraft(
        parent_id=job.parent_id,
        artifact_path=manifest.path,
        manifest_path=str(store.manifest_path(artifact_id, manifest.revision)),
        revision=manifest.revision,
        sha256=manifest.sha256,
        draft_markdown=candidate.draft_markdown,
    )
    return persisted, manifest


def _source_bundle(
    job: P08WorkflowInput,
    project_root: Path,
    *,
    authorized_roots: tuple[Path, ...] = (),
) -> tuple[list[FreshContextInput], dict[str, dict[str, str]]]:
    """Resolve and load source authorities only after all boundary checks pass.

    Resolution is deliberately performed for every supplied descriptor before any
    bytes are read.  Required descriptors and explicitly supplied optional
    descriptors therefore fail closed instead of silently disappearing.
    """
    required_roles = {"source_mother", "next_parent_constraint"}
    values = (
        ("source_mother", job.source_mother),
        ("next_parent_constraint", job.next_parent_constraint),
        ("previous_canon", job.previous_canon),
        ("ledger_open_context", job.ledger_open_context),
        ("approved_dossier", job.approved_dossier),
    )
    roots = tuple(dict.fromkeys((project_root.resolve(), *(Path(root).resolve() for root in authorized_roots))))
    resolver = FileResolver(roots)
    # Build and validate the LoadPlan using resolved metadata before reading bytes.
    resolved_entries: list[tuple[str, Path, bool]] = []
    declarations: list[LoadInput] = []
    for role, value in values:
        required = role in required_roles
        if not value:
            if required:
                raise FileNotFoundError(f"Required source authority is missing: {role}")
            continue
        reference = Path(value)
        candidate = reference if reference.is_absolute() else project_root / reference
        if _secret_path(candidate):
            raise FileResolutionError("Secret-bearing source path is forbidden.")
        resolved = resolver.resolve(candidate, required=True)
        assert resolved is not None
        if _secret_path(resolved.path):
            raise FileResolutionError("Secret-bearing source path is forbidden.")
        resolved_entries.append((role, resolved.path, required))
        declarations.append(
            LoadInput(
                reference=str(resolved.path),
                role=role,
                parse_mode=ParseMode.BYTES,
                persistence_class=PersistenceClass.WORKING,
                required=required,
            )
        )
    plan = LoadPlan.from_inputs(
        plan_id=f"{job.job_id}-source-load",
        project_root=str(project_root.resolve()),
        allowed_roots=tuple(str(root) for root in roots),
        required_inputs=tuple(declarations),
        execution_budget=32,
        load_budget=8_000_000,
    )
    plan.validate()

    items: list[FreshContextInput] = []
    bundle: dict[str, dict[str, str]] = {}
    for role, path, required in resolved_entries:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        items.append(
            FreshContextInput(
                reference=path,
                role=role,
                provenance=ProvenanceClass.PERSISTED_SOURCE,
                expected_sha256=digest,
                parse_mode=ParseMode.BYTES,
                persistence_class=PersistenceClass.WORKING,
                required=required,
            )
        )
        bundle[role] = {
            "content": raw.decode("utf-8"),
            "sha256": digest,
        }
    return items, bundle


def _source_inputs(
    job: P08WorkflowInput,
    project_root: Path,
    *,
    authorized_roots: tuple[Path, ...] = (),
) -> list[FreshContextInput]:
    """Return explicitly file-backed source authorities, failing closed."""
    items, _ = _source_bundle(job, project_root, authorized_roots=authorized_roots)
    return items


def authorize_p08b_context(job: P08WorkflowInput, manifest: ArtifactManifest, prompts: Mapping[str, Any], *, authorized_shadow_root: Path) -> Any:
    """Construct and authorize the execution-specific D03 P08B input bundle."""
    project_root = Path(__file__).resolve().parents[3]
    p08b = prompts["P08B"]
    inputs = [
        FreshContextInput(reference=manifest.path, role="persisted_p08a_candidate", provenance=ProvenanceClass.PERSISTED_REVIEW_TARGET, expected_sha256=manifest.sha256, parse_mode=ParseMode.MARKDOWN, persistence_class=PersistenceClass.WORKING, artifact_id=manifest.artifact_id, revision=manifest.revision),
        FreshContextInput(reference=p08b.path, role="formal_p08b_prompt", provenance=ProvenanceClass.FORMAL_AUTHORITY, expected_sha256=p08b.sha256, parse_mode=ParseMode.MARKDOWN, persistence_class=PersistenceClass.AUDIT),
    ]
    source_roots = (Path(authorized_shadow_root).resolve(),)
    inputs.extend(_source_inputs(job, project_root, authorized_roots=source_roots))
    roots = (Path(authorized_shadow_root).resolve(), p08b.path.parent.resolve(), project_root.resolve())
    return authorize_fresh_context(FreshContextRequest(inputs=tuple(inputs), project_root=project_root, allowed_roots=roots, execution_id=f"{job.job_id}-P08B-R{manifest.revision:03d}", plan_id=f"{job.job_id}-P08B-FRESH-R{manifest.revision:03d}", execution_budget=32, load_budget=8_000_000))


def _fresh_p08b_payload(authorization: Any, manifest: ArtifactManifest) -> dict[str, Any]:
    if not authorization.authorized or not authorization.plan:
        raise PermissionError("D03 did not authorize P08B fresh context")
    return {
        "execution_id": authorization.plan.execution_id,
        "context_id": authorization.plan.context_id,
        "bundle_fingerprint": authorization.plan.bundle_fingerprint,
        "candidate": {"artifact_id": manifest.artifact_id, "revision": manifest.revision, "sha256": manifest.sha256},
        "inputs": [
            {"role": item.role, "reference": item.reference, "expected_sha256": item.expected_sha256, "parse_mode": item.parse_mode}
            for item in authorization.plan.inputs
        ],
    }


async def _run_maf_agent(agent: Any, request: Any, *, executor_id: str, output: bool = True) -> Any:
    """Run one isolated MAF executor using the local 1.13.0 builder shape."""
    from agent_framework import AgentExecutor, AgentExecutorResponse, WorkflowBuilder, WorkflowContext, executor

    agent_exec = AgentExecutor(agent, id=executor_id)

    # MAF 1.13.0 requires a context parameter annotation to recognize the
    # handler shape, but explicit decorator types must own the message and
    # workflow-output contracts.  The module's future-annotations mode would
    # otherwise leave this locally imported type as a string, so bind only the
    # non-parameterized context marker to its concrete runtime type before
    # applying the decorator.  No WorkflowContext output introspection is used.
    async def collect(response, ctx) -> None:
        await ctx.yield_output(response.agent_response.text)

    collect.__annotations__["ctx"] = WorkflowContext
    collect = executor(
        id=f"{executor_id}-out",
        input=AgentExecutorResponse,
        workflow_output=str,
    )(collect)

    builder = WorkflowBuilder(start_executor=agent_exec, output_from=[collect])
    builder.add_edge(agent_exec, collect)
    workflow = builder.build()
    events = await workflow.run(request)
    outputs = events.get_outputs()
    if not outputs:
        raise RuntimeError("MAF executor produced no output")
    return outputs[0]


async def run_p08_once(
    job: P08WorkflowInput,
    *,
    model_profiles_path: Path,
    authorized_shadow_root: Path | None = None,
    p08_response: Any | None = None,
    p08b_response: Any | None = None,
    response_provider: Callable[[str, Mapping[str, Any]], Any | Awaitable[Any]] | None = None,
) -> tuple[P08GateResult, ArtifactManifest]:
    """Execute one P08 candidate and one separately authorized fresh P08B review."""
    enforce_shadow_output_root(job, authorized_shadow_root)
    project_root = Path(__file__).resolve().parents[3]
    prompts = load_formal_prompts(project_root)
    store = ArtifactStore(job.output_dir)
    _, source_bundle = _source_bundle(job, project_root, authorized_roots=(Path(authorized_shadow_root).resolve(),))
    p08_payload = {
        "job_id": job.job_id,
        "parent_id": job.parent_id,
        "source_mother": source_bundle["source_mother"]["content"],
        "next_parent_constraint": source_bundle["next_parent_constraint"]["content"],
        "previous_canon": source_bundle.get("previous_canon", {}).get("content", ""),
        "ledger_open_context": source_bundle.get("ledger_open_context", {}).get("content", ""),
        "approved_dossier": source_bundle.get("approved_dossier", {}).get("content", ""),
        "source_bundle": source_bundle,
        "shadow_only": True,
    }
    if response_provider:
        p08_response = response_provider("P08", p08_payload)
        if hasattr(p08_response, "__await__"):
            p08_response = await p08_response
    if p08_response is None:
        try:
            from agent_framework import AgentExecutorRequest, Message
        except ImportError as exc:
            raise RuntimeError("agent-framework is not installed; inject p08_response/p08b_response for offline execution") from exc
        profile = load_model_profile("reason_high", model_profiles_path)
        schema = load_runtime_schema(project_root, "P08")
        instructions = build_structured_agent_instructions(prompts["P08"].content, schema, "P08")
        agent = DeepSeekAgentFactory(profile).create_agent(agent_id=f"p08-{job.job_id}", name="p08_structure_mapper", instructions=instructions)
        p08_response = await _run_maf_agent(agent, AgentExecutorRequest(messages=[Message("user", contents=[json.dumps(p08_payload, ensure_ascii=False)])], should_respond=True), executor_id=f"p08-{job.job_id}")
    draft = validate_p08_output(p08_response)
    # P08A is deterministic and is the only producer of the persisted candidate.
    persisted, manifest = persist_p08a(store, job, draft, authorized_shadow_root=authorized_shadow_root)
    authorization = authorize_p08b_context(job, manifest, prompts, authorized_shadow_root=Path(authorized_shadow_root))
    p08b_payload = _fresh_p08b_payload(authorization, manifest)
    if response_provider:
        p08b_response = response_provider("P08B", p08b_payload)
        if hasattr(p08b_response, "__await__"):
            p08b_response = await p08b_response
    if p08b_response is None:
        if not authorization.authorized:
            raise PermissionError("D03 did not authorize P08B fresh context")
        from agent_framework import AgentExecutorRequest, Message
        profile = load_model_profile("reason_high", model_profiles_path)
        schema = load_runtime_schema(project_root, "P08B")
        instructions = build_structured_agent_instructions(prompts["P08B"].content, schema, "P08B")
        agent = DeepSeekAgentFactory(profile).create_agent(agent_id=f"p08b-{job.job_id}-R{manifest.revision:03d}", name="p08b_independent_gate", instructions=instructions)
        p08b_response = await _run_maf_agent(agent, AgentExecutorRequest(messages=[Message("user", contents=[json.dumps(p08b_payload, ensure_ascii=False)])], should_respond=True), executor_id=f"p08b-{job.job_id}-R{manifest.revision:03d}")
    gate_candidate = validate_p08b_output(p08b_response)
    if gate_candidate.reviewed_sha256 != manifest.sha256:
        raise ValueError(f"P08B reviewed SHA mismatch: expected {manifest.sha256}, got {gate_candidate.reviewed_sha256}")
    return _as_public_gate(gate_candidate), manifest


async def run_p08_cycle(
    job: P08WorkflowInput,
    *,
    model_profiles_path: Path,
    authorized_shadow_root: Path | None = None,
    response_provider: Callable[[str, Mapping[str, Any]], Any | Awaitable[Any]] | None = None,
) -> P08WorkflowResult:
    """Run bounded cycles; D02 is the sole route authority."""
    enforce_shadow_output_root(job, authorized_shadow_root)
    current = job.model_copy(update={"previous_gate_result": None})
    latest_manifest: ArtifactManifest | None = None
    previous_sha: str | None = None
    for cycle in range(1, job.max_revisions + 2):
        cycle_job = current.model_copy(update={"job_id": f"{job.job_id}-C{cycle:02d}", "previous_gate_result": None})
        gate, latest_manifest = await run_p08_once(cycle_job, model_profiles_path=model_profiles_path, authorized_shadow_root=authorized_shadow_root, response_provider=response_provider)
        if previous_sha is not None and latest_manifest.sha256 == previous_sha:
            raise RuntimeError("REVISE requires a new P08 candidate SHA binding")
        candidate = {
            "verdict": gate.verdict.value if isinstance(gate.verdict, GateVerdict) else gate.verdict,
            "reviewed_sha256": gate.reviewed_sha256,
            "summary": gate.summary,
            "revision_targets": gate.revision_targets,
            "blocker_details": gate.blocker_details,
            "return_action": getattr(gate, "return_action", _REVISE_ACTION),
        }
        decision: RouteDecision = route_review(candidate, RoutingContext(latest_manifest.artifact_id, latest_manifest.revision, latest_manifest.sha256))
        if decision.action.value == "GATE_CANDIDATE" or decision.action.value == "STOP_BLOCKER":
            return P08WorkflowResult(job_id=job.job_id, cycles=cycle, final_gate=gate, latest_artifact=latest_manifest)
        if cycle > job.max_revisions:
            raise RuntimeError("P08 revision budget exhausted.")
        # D02 RETURN_TO_P08 requires a new execution/candidate/revision/fresh context.
        previous_sha = latest_manifest.sha256
        current = current.model_copy(update={"previous_gate_result": None})
    raise AssertionError("Unreachable")


__all__ = [
    "FORMAL_PROMPT_BINDINGS", "RUNTIME_SCHEMA_BINDINGS", "P08DraftCandidate", "P08BGateCandidate", "load_formal_prompts",
    "load_runtime_schema", "build_structured_agent_instructions",
    "validate_p08_output", "validate_p08b_output", "enforce_shadow_output_root", "persist_p08a",
    "authorize_p08b_context", "run_p08_once", "run_p08_cycle",
]
