"""R007 first-slice Runtime-owned provider execution configuration.

No credential value is stored here and this module performs no provider/network execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping
from urllib.parse import urlsplit


class ProviderExecutionConfigError(ValueError):
    pass


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PROXY_MODES = frozenset({"DIRECT", "EXPLICIT_LOOPBACK_ONLY"})


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderExecutionConfigError(f"{name} must be non-empty text")
    return value


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ProviderExecutionConfigError(f"{name} must be lowercase 64-hex")
    return value


def direct_proxy_config_sha256() -> str:
    return _digest({"proxy_mode": "DIRECT", "proxy_url": None})


@dataclass(frozen=True)
class ProviderExecutionConfig:
    provider_execution_config_id: str
    revision: int
    provider: str
    resolved_model_entry_id: str
    model_resolution_sha256: str
    endpoint_origin: str
    api_route: str
    http_method: str
    stream: bool
    adapter_relative_path: str
    adapter_sha256: str
    transport_client_class: str
    transport_package_versions: tuple[tuple[str, str], ...]
    transport_retries_max: int
    trust_env: bool
    proxy_mode: str
    proxy_config_sha256: str
    credential_ref_id: str
    credential_ref_class: str

    def __post_init__(self) -> None:
        _text(self.provider_execution_config_id, "provider_execution_config_id")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ProviderExecutionConfigError("revision must be a positive integer")
        for name in (
            "provider",
            "resolved_model_entry_id",
            "endpoint_origin",
            "api_route",
            "adapter_relative_path",
            "transport_client_class",
            "proxy_mode",
            "credential_ref_id",
            "credential_ref_class",
        ):
            _text(getattr(self, name), name)
        for name in ("model_resolution_sha256", "adapter_sha256", "proxy_config_sha256"):
            _sha(getattr(self, name), name)

        parsed = urlsplit(self.endpoint_origin)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ProviderExecutionConfigError("endpoint_origin must be an explicit https origin")
        if parsed.username is not None or parsed.password is not None:
            raise ProviderExecutionConfigError("endpoint_origin must not contain credentials")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ProviderExecutionConfigError("endpoint_origin must not contain path/query/fragment")
        if not self.api_route.startswith("/") or "://" in self.api_route:
            raise ProviderExecutionConfigError("api_route must be an absolute route path")
        if "?" in self.api_route or "#" in self.api_route:
            raise ProviderExecutionConfigError("api_route must not contain query/fragment")

        if self.http_method != "POST":
            raise ProviderExecutionConfigError("formal provider execution requires POST")
        if self.revision == 1:
            if self.stream is not False:
                raise ProviderExecutionConfigError("revision 1 requires stream=false")
        elif self.revision == 2:
            if self.stream is not True:
                raise ProviderExecutionConfigError("revision 2 requires stream=true")
        else:
            raise ProviderExecutionConfigError("unsupported provider execution config revision")
        if self.transport_retries_max != 0:
            raise ProviderExecutionConfigError("first slice requires transport_retries_max=0")
        if self.trust_env is not False:
            raise ProviderExecutionConfigError("first slice requires trust_env=false")
        if self.proxy_mode not in _PROXY_MODES:
            raise ProviderExecutionConfigError("unsupported proxy_mode")
        if self.proxy_mode == "DIRECT" and self.proxy_config_sha256 != direct_proxy_config_sha256():
            raise ProviderExecutionConfigError("DIRECT proxy_config_sha256 mismatch")

        packages = self.transport_package_versions
        if not isinstance(packages, tuple) or not packages:
            raise ProviderExecutionConfigError("transport_package_versions must be non-empty")
        names: list[str] = []
        for item in packages:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ProviderExecutionConfigError("transport package entry must be a name/version pair")
            name, version = item
            _text(name, "transport package name")
            _text(version, "transport package version")
            names.append(name)
        if names != sorted(names) or len(names) != len(set(names)):
            raise ProviderExecutionConfigError("transport packages must be unique and sorted")

    def payload(self) -> dict[str, object]:
        return {
            "schema": "RUNTIME_PROVIDER_EXECUTION_CONFIG_V1",
            "provider_execution_config_id": self.provider_execution_config_id,
            "revision": self.revision,
            "provider": self.provider,
            "resolved_model_entry_id": self.resolved_model_entry_id,
            "model_resolution_sha256": self.model_resolution_sha256,
            "endpoint_origin": self.endpoint_origin,
            "api_route": self.api_route,
            "http_method": self.http_method,
            "stream": self.stream,
            "adapter_relative_path": self.adapter_relative_path,
            "adapter_sha256": self.adapter_sha256,
            "transport_client_class": self.transport_client_class,
            "transport_package_versions": {
                name: version for name, version in self.transport_package_versions
            },
            "transport_retries_max": self.transport_retries_max,
            "trust_env": self.trust_env,
            "proxy_mode": self.proxy_mode,
            "proxy_config_sha256": self.proxy_config_sha256,
            "credential_ref_id": self.credential_ref_id,
            "credential_ref_class": self.credential_ref_class,
        }

    @property
    def semantic_sha256(self) -> str:
        return _digest(self.payload())

    @classmethod
    def create(
        cls,
        *,
        revision: int,
        provider: str,
        resolved_model_entry_id: str,
        model_resolution_sha256: str,
        endpoint_origin: str,
        api_route: str,
        adapter_relative_path: str,
        adapter_sha256: str,
        transport_client_class: str,
        transport_package_versions: Mapping[str, str],
        credential_ref_id: str,
        credential_ref_class: str,
        stream: bool = False,
        proxy_mode: str = "DIRECT",
        proxy_config_sha256: str | None = None,
    ) -> "ProviderExecutionConfig":
        packages = tuple(sorted(transport_package_versions.items()))
        effective_proxy_sha = (
            direct_proxy_config_sha256()
            if proxy_mode == "DIRECT" and proxy_config_sha256 is None
            else proxy_config_sha256
        )
        if effective_proxy_sha is None:
            raise ProviderExecutionConfigError("proxy_config_sha256 is required")
        seed = {
            "revision": revision,
            "provider": provider,
            "resolved_model_entry_id": resolved_model_entry_id,
            "model_resolution_sha256": model_resolution_sha256,
            "endpoint_origin": endpoint_origin,
            "api_route": api_route,
            "adapter_relative_path": adapter_relative_path,
            "adapter_sha256": adapter_sha256,
            "transport_client_class": transport_client_class,
            "transport_package_versions": dict(packages),
            "proxy_mode": proxy_mode,
            "proxy_config_sha256": effective_proxy_sha,
            "credential_ref_id": credential_ref_id,
            "credential_ref_class": credential_ref_class,
        }
        return cls(
            provider_execution_config_id="PEC_" + _digest(seed)[:24].upper(),
            revision=revision,
            provider=provider,
            resolved_model_entry_id=resolved_model_entry_id,
            model_resolution_sha256=model_resolution_sha256,
            endpoint_origin=endpoint_origin,
            api_route=api_route,
            http_method="POST",
            stream=stream,
            adapter_relative_path=adapter_relative_path,
            adapter_sha256=adapter_sha256,
            transport_client_class=transport_client_class,
            transport_package_versions=packages,
            transport_retries_max=0,
            trust_env=False,
            proxy_mode=proxy_mode,
            proxy_config_sha256=effective_proxy_sha,
            credential_ref_id=credential_ref_id,
            credential_ref_class=credential_ref_class,
        )

    def assert_matches_resolution(
        self,
        *,
        provider: str,
        resolved_model_entry_id: str,
        model_resolution_sha256: str,
    ) -> None:
        if self.provider != provider:
            raise ProviderExecutionConfigError("provider differs from exact ModelResolution")
        if self.resolved_model_entry_id != resolved_model_entry_id:
            raise ProviderExecutionConfigError("model entry differs from exact ModelResolution")
        if self.model_resolution_sha256 != model_resolution_sha256:
            raise ProviderExecutionConfigError("resolution SHA differs from exact ModelResolution")
