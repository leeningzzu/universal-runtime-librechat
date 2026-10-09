"""Development-only acceptance evidence tooling."""

from .acceptance_models import AcceptanceReport, AcceptanceSpec, load_spec

__all__ = ["AcceptanceSpec", "AcceptanceReport", "load_spec", "run_acceptance", "run_bootstrap"]


def __getattr__(name: str):
    if name == "run_acceptance":
        from .acceptance_runner import run_acceptance

        return run_acceptance
    if name == "run_bootstrap":
        from .bootstrap_acceptance import run_bootstrap

        return run_bootstrap
    raise AttributeError(name)
