from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit


class WebResearchContractError(ValueError):
    """Raised when provider-neutral Web Research input/output fails closed."""


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_external_url(value: str) -> str:
    if not isinstance(value, str) or not value or any(ord(ch) < 32 or ch == " " for ch in value):
        raise WebResearchContractError("Research URL must be a non-empty control-character-free string.")
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"}:
        raise WebResearchContractError("Research result URL must use HTTP or HTTPS.")
    if parts.username is not None or parts.password is not None:
        raise WebResearchContractError("Credentials in Research URLs are forbidden.")
    if parts.hostname is None:
        raise WebResearchContractError("Research URL must include a hostname.")
    if parts.fragment:
        parts = parts._replace(fragment="")
    return urlunsplit(parts)


@dataclass(frozen=True)
class WebResearchBudget:
    search_calls_max: int = 1
    extract_calls_max: int = 1
    search_results_max: int = 5
    extract_urls_max: int = 3
    search_response_bytes_max: int = 512_000
    extract_response_bytes_max: int = 2_000_000
    request_body_bytes_max: int = 64_000
    timeout_seconds: float = 20.0

    def validate_first_slice(self) -> None:
        if self.search_calls_max != 1:
            raise WebResearchContractError("first slice requires exactly one allowed search call.")
        if self.extract_calls_max != 1:
            raise WebResearchContractError("first slice requires exactly one allowed extract call.")
        if not isinstance(self.search_results_max, int) or not (1 <= self.search_results_max <= 5):
            raise WebResearchContractError("search_results_max must be within 1..5.")
        if not isinstance(self.extract_urls_max, int) or not (1 <= self.extract_urls_max <= 3):
            raise WebResearchContractError("extract_urls_max must be within 1..3.")
        if self.extract_urls_max > self.search_results_max:
            raise WebResearchContractError("extract_urls_max cannot exceed search_results_max.")
        for name, value, upper in (
            ("search_response_bytes_max", self.search_response_bytes_max, 2_000_000),
            ("extract_response_bytes_max", self.extract_response_bytes_max, 8_000_000),
            ("request_body_bytes_max", self.request_body_bytes_max, 256_000),
        ):
            if not isinstance(value, int) or value <= 0 or value > upper:
                raise WebResearchContractError(f"{name} is outside the first-slice bound.")
        if not isinstance(self.timeout_seconds, (int, float)) or not (0 < float(self.timeout_seconds) <= 30):
            raise WebResearchContractError("timeout_seconds must be >0 and <=30.")


@dataclass(frozen=True)
class WebResearchIntent:
    query: str
    topic: str = "general"

    def validate(self) -> None:
        if not isinstance(self.query, str):
            raise WebResearchContractError("Research query must be a string.")
        query = self.query.strip()
        if not query or len(query) > 500:
            raise WebResearchContractError("Research query must contain 1..500 characters.")
        if self.topic not in {"general", "news"}:
            raise WebResearchContractError("first-slice topic must be general or news.")

    def query_sha256(self) -> str:
        self.validate()
        return _digest_bytes(self.query.strip().encode("utf-8"))


@dataclass(frozen=True)
class WebSearchHit:
    rank: int
    title: str
    url: str
    snippet: str
    provider_score: float | None = None

    def validate(self) -> None:
        if not isinstance(self.rank, int) or self.rank <= 0:
            raise WebResearchContractError("Search hit rank must be a positive integer.")
        if not isinstance(self.title, str) or not self.title.strip():
            raise WebResearchContractError("Search hit title must be non-empty.")
        _canonical_external_url(self.url)
        if not isinstance(self.snippet, str):
            raise WebResearchContractError("Search hit snippet must be a string.")
        if self.provider_score is not None and not isinstance(self.provider_score, (int, float)):
            raise WebResearchContractError("provider_score must be numeric when present.")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "rank": self.rank,
            "title": self.title.strip(),
            "url": _canonical_external_url(self.url),
            "snippet": self.snippet,
            "provider_score": float(self.provider_score) if self.provider_score is not None else None,
        }


@dataclass(frozen=True)
class WebSearchEvidence:
    adapter_id: str
    request_id: str
    query_sha256: str
    provider_response_sha256: str
    hits: tuple[WebSearchHit, ...]

    def validate(self, *, max_results: int) -> None:
        if not isinstance(self.adapter_id, str) or not self.adapter_id:
            raise WebResearchContractError("adapter_id must be non-empty.")
        if not isinstance(self.request_id, str) or not self.request_id:
            raise WebResearchContractError("request_id must be non-empty.")
        for value, label in (
            (self.query_sha256, "query_sha256"),
            (self.provider_response_sha256, "provider_response_sha256"),
        ):
            if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise WebResearchContractError(f"{label} must be lowercase 64-hex.")
        if len(self.hits) > max_results:
            raise WebResearchContractError("Search response exceeds max_results.")
        seen: set[str] = set()
        for expected_rank, hit in enumerate(self.hits, start=1):
            hit.validate()
            if hit.rank != expected_rank:
                raise WebResearchContractError("Search hit ranks must be contiguous and provider-order preserving.")
            url = _canonical_external_url(hit.url)
            if url in seen:
                raise WebResearchContractError("Search evidence contains duplicate canonical URLs.")
            seen.add(url)

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "request_id": self.request_id,
            "query_sha256": self.query_sha256,
            "provider_response_sha256": self.provider_response_sha256,
            "hits": [hit.to_dict() for hit in self.hits],
        }


@dataclass(frozen=True)
class WebRetrievedDocument:
    rank: int
    url: str
    content: str
    content_sha256: str
    retrieval_via: str

    @classmethod
    def from_content(
        cls,
        *,
        rank: int,
        url: str,
        content: str,
        retrieval_via: str,
    ) -> "WebRetrievedDocument":
        if not isinstance(content, str) or not content:
            raise WebResearchContractError("Retrieved content must be non-empty text.")
        canonical_url = _canonical_external_url(url)
        digest = _digest_bytes(content.encode("utf-8"))
        return cls(rank, canonical_url, content, digest, retrieval_via)

    def validate(self) -> None:
        if not isinstance(self.rank, int) or self.rank <= 0:
            raise WebResearchContractError("Retrieved document rank must be positive.")
        _canonical_external_url(self.url)
        if not isinstance(self.content, str) or not self.content:
            raise WebResearchContractError("Retrieved document content must be non-empty.")
        if _digest_bytes(self.content.encode("utf-8")) != self.content_sha256:
            raise WebResearchContractError("Retrieved document content SHA mismatch.")
        if not isinstance(self.retrieval_via, str) or not self.retrieval_via:
            raise WebResearchContractError("retrieval_via must be non-empty.")

    def to_evidence_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "rank": self.rank,
            "url": _canonical_external_url(self.url),
            "content_sha256": self.content_sha256,
            "content_bytes": len(self.content.encode("utf-8")),
            "retrieval_via": self.retrieval_via,
        }


@dataclass(frozen=True)
class WebExtractEvidence:
    adapter_id: str
    request_id: str
    provider_response_sha256: str
    documents: tuple[WebRetrievedDocument, ...]

    def validate(self, *, expected_urls: Iterable[str], max_documents: int) -> None:
        if not isinstance(self.adapter_id, str) or not self.adapter_id:
            raise WebResearchContractError("adapter_id must be non-empty.")
        if not isinstance(self.request_id, str) or not self.request_id:
            raise WebResearchContractError("request_id must be non-empty.")
        if not isinstance(self.provider_response_sha256, str) or len(self.provider_response_sha256) != 64:
            raise WebResearchContractError("provider_response_sha256 must be 64-hex.")
        expected = tuple(_canonical_external_url(x) for x in expected_urls)
        if len(self.documents) > max_documents:
            raise WebResearchContractError("Extract response exceeds max_documents.")
        actual = tuple(doc.url for doc in self.documents)
        if actual != expected[: len(actual)]:
            raise WebResearchContractError("Extract documents must preserve the exact requested URL order.")
        for expected_rank, doc in enumerate(self.documents, start=1):
            doc.validate()
            if doc.rank != expected_rank:
                raise WebResearchContractError("Extract document ranks must be contiguous.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "request_id": self.request_id,
            "provider_response_sha256": self.provider_response_sha256,
            "documents": [doc.to_evidence_dict() for doc in self.documents],
        }


def canonical_json_bytes(payload: Any) -> bytes:
    return _canonical_json_bytes(payload)


__all__ = [
    "WebResearchBudget",
    "WebResearchContractError",
    "WebResearchIntent",
    "WebSearchHit",
    "WebSearchEvidence",
    "WebRetrievedDocument",
    "WebExtractEvidence",
    "canonical_json_bytes",
]
