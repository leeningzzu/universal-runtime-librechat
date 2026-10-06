from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path

import yaml

from universal_runtime.core.model_catalog import ResolvedModelExecution
from universal_runtime.core.models import ModelProfile


def load_model_profile(profile_id: str, path: Path) -> ModelProfile:
    data = yaml.safe_load(path.read_text(encoding='utf-8'))['profiles']
    if profile_id not in data:
        raise KeyError(f'Unknown model profile: {profile_id}')
    raw = data[profile_id]
    model = os.getenv(raw['model_env'])
    if not model:
        raise RuntimeError(f"Environment variable {raw['model_env']} is not set")
    return ModelProfile(profile_id=profile_id, model=model, **{k: v for k, v in raw.items() if k != 'model_env'})


def materialize_resolved_model_profile(
    profile_id: str, resolution: ResolvedModelExecution, path: Path
) -> tuple[ModelProfile, str]:
    """Materialize a logical profile with the immutable concrete catalog model."""
    if not isinstance(resolution, ResolvedModelExecution):
        raise ValueError("resolution must be a ResolvedModelExecution")
    if resolution.selected_profile != profile_id:
        raise ValueError("resolution selected_profile does not match profile_id")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))["profiles"]
    if profile_id not in data:
        raise KeyError(f"Unknown model profile: {profile_id}")
    raw = data[profile_id]
    if resolution.provider != "deepseek":
        raise ValueError(f"No model adapter exists for provider: {resolution.provider}")
    settings = {
        "profile_id": profile_id,
        "thinking": raw["thinking"],
        "reasoning_effort": raw["reasoning_effort"],
        "max_tokens": raw["max_tokens"],
    }
    config_sha256 = hashlib.sha256(
        json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    profile = ModelProfile(
        profile_id=profile_id,
        provider="deepseek",
        model=resolution.model,
        thinking=raw["thinking"],
        reasoning_effort=raw["reasoning_effort"],
        max_tokens=raw["max_tokens"],
    )
    return profile, config_sha256
