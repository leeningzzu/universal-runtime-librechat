from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .enums import PersistenceClass


class ParseMode:
    BYTES = 'bytes'
    MARKDOWN = 'markdown'
    DOCX = 'docx'


class LoadPlanError(ValueError):
    """Raised when a plan is incomplete or exceeds its declared budget."""


@dataclass(frozen=True)
class LoadInput:
    reference: str
    role: str
    expected_sha256: str | None = None
    parse_mode: str = 'bytes'
    persistence_class: PersistenceClass = PersistenceClass.EPHEMERAL
    required: bool = True
    byte_budget: int | None = None


@dataclass(frozen=True)
class LoadPlan:
    plan_id: str
    project_root: str
    allowed_roots: tuple[str, ...]
    required_inputs: tuple[LoadInput, ...] = field(default_factory=tuple)
    execution_budget: int | None = None
    load_budget: int | None = None

    def __post_init__(self) -> None:
        if not self.plan_id or not self.project_root or not self.allowed_roots:
            raise LoadPlanError('plan_id, project_root, and allowed_roots are required.')
        if self.execution_budget is not None and self.execution_budget < 0:
            raise LoadPlanError('execution_budget must be non-negative.')
        if self.load_budget is not None and self.load_budget < 0:
            raise LoadPlanError('load_budget must be non-negative.')

    @classmethod
    def from_inputs(cls, *, plan_id: str, project_root: str, allowed_roots: Iterable[str], required_inputs: Iterable[LoadInput], execution_budget: int | None = None, load_budget: int | None = None) -> 'LoadPlan':
        return cls(plan_id, project_root, tuple(allowed_roots), tuple(required_inputs), execution_budget, load_budget)

    def validate(self, resolved_sizes: Iterable[int] | None = None) -> None:
        inputs = tuple(self.required_inputs)
        if any(item.required and not item.reference for item in inputs):
            raise LoadPlanError('A required input is missing its reference.')
        sizes = tuple(resolved_sizes or ())
        if self.load_budget is not None and sum(sizes) > self.load_budget:
            raise LoadPlanError('Load budget exceeded.')
        if self.execution_budget is not None and len(inputs) > self.execution_budget:
            raise LoadPlanError('Execution budget exceeded.')
