from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .enums import GateVerdict, PersistenceClass


class ArtifactManifest(BaseModel):
    artifact_id: str
    revision: int = Field(ge=1)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    path: str
    persistence_class: PersistenceClass
    created_at: str
    job_id: str
    input_fingerprint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def now(cls, **kwargs: Any) -> 'ArtifactManifest':
        return cls(created_at=datetime.now(timezone.utc).isoformat(), **kwargs)


class ModelProfile(BaseModel):
    profile_id: str
    provider: Literal['deepseek'] = 'deepseek'
    model: str
    thinking: Literal['enabled', 'disabled'] = 'disabled'
    reasoning_effort: Literal['low', 'high', 'max'] = 'high'
    max_tokens: int = Field(default=16000, ge=1)


class P08StructureDraft(BaseModel):
    parent_id: str
    decision: Literal['KEEP', 'SPLIT']
    draft_markdown: str = Field(min_length=1)
    source_coverage_summary: str
    history_boundary_blocker: str | None = None


class PersistedDraft(BaseModel):
    parent_id: str
    artifact_path: str
    manifest_path: str
    revision: int
    sha256: str
    draft_markdown: str


class P08GateResult(BaseModel):
    verdict: GateVerdict
    reviewed_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    summary: str
    revision_targets: list[str] = Field(default_factory=list)
    blocker_details: str | None = None


class P08WorkflowInput(BaseModel):
    job_id: str
    project_id: str = 'tianxiabo-shadow'
    parent_id: str
    source_mother: str
    next_parent_constraint: str
    previous_canon: str = ''
    ledger_open_context: str = ''
    approved_dossier: str = ''
    previous_gate_result: P08GateResult | None = None
    output_dir: Path
    max_revisions: int = Field(default=2, ge=0, le=10)
    shadow_only: bool = True


class P08WorkflowResult(BaseModel):
    job_id: str
    cycles: int
    final_gate: P08GateResult
    latest_artifact: ArtifactManifest
