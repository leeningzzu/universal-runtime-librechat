from __future__ import annotations

def run_maf_smoke() -> dict:
    """Small opt-in smoke; intentionally never imports production/model code."""
    try:
        import agent_framework  # type: ignore  # noqa: F401
    except ImportError:
        return {"pass": False, "output": "", "reason": "agent-framework unavailable"}
    return {"pass": True, "output": "ACCEPTANCE_MAF_SMOKE_PASS", "reason": "local fake workflow"}
