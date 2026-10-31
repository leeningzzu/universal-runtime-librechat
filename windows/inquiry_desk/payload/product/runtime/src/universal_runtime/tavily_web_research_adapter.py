from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from .core.network_permissions import NetworkRequest
from .web_research_contract import (
    WebExtractEvidence,
    WebResearchBudget,
    WebResearchContractError,
    WebResearchIntent,
    WebRetrievedDocument,
    WebSearchEvidence,
    WebSearchHit,
    canonical_json_bytes,
)


class TavilyWebResearchAdapterError(WebResearchContractError):
    """Raised when Tavily-shaped input/output violates the provider-neutral contract."""


ADAPTER_ID = "TAVILY_HTTP_V1"
TAVILY_HOST = "api.tavily.com"
SEARCH_URL = "https://api.tavily.com/search"
EXTRACT_URL = "https://api.tavily.com/extract"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _request(
    *,
    request_id: str,
    url: str,
    role: str,
    body: bytes,
    response_byte_budget: int,
) -> NetworkRequest:
    return NetworkRequest(
        request_id=request_id,
        url=url,
        role=role,
        method="POST",
        byte_budget=response_byte_budget,
        request_body_sha256=_sha256(body),
        request_body_bytes=len(body),
        content_type="application/json",
        requires_bearer_authorization=True,
    )


def compile_search_request(
    *,
    request_id: str,
    intent: WebResearchIntent,
    budget: WebResearchBudget,
) -> tuple[NetworkRequest, bytes]:
    budget.validate_first_slice()
    intent.validate()
    payload = {
        "query": intent.query.strip(),
        "search_depth": "basic",
        "max_results": budget.search_results_max,
        "topic": intent.topic,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
        "include_image_descriptions": False,
        "include_favicon": False,
        "include_domains": [],
        "exclude_domains": [],
        "auto_parameters": False,
        "include_usage": True,
    }
    body = canonical_json_bytes(payload)
    if len(body) > budget.request_body_bytes_max:
        raise TavilyWebResearchAdapterError("Tavily search body exceeds first-slice request_body_bytes_max.")
    return (
        _request(
            request_id=request_id,
            url=SEARCH_URL,
            role="web_research_search",
            body=body,
            response_byte_budget=budget.search_response_bytes_max,
        ),
        body,
    )


def parse_search_response(
    *,
    request_id: str,
    intent: WebResearchIntent,
    budget: WebResearchBudget,
    response_body: bytes,
) -> WebSearchEvidence:
    budget.validate_first_slice()
    intent.validate()
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TavilyWebResearchAdapterError("Tavily search response is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise TavilyWebResearchAdapterError("Tavily search response must be a JSON object.")
    results = payload.get("results")
    if not isinstance(results, list):
        raise TavilyWebResearchAdapterError("Tavily search response.results must be an array.")
    if len(results) > budget.search_results_max:
        raise TavilyWebResearchAdapterError("Tavily search returned more results than authorized.")

    hits: list[WebSearchHit] = []
    seen: set[str] = set()
    for row in results:
        if not isinstance(row, dict):
            raise TavilyWebResearchAdapterError("Tavily search result must be an object.")
        title = row.get("title")
        url = row.get("url")
        content = row.get("content")
        score = row.get("score")
        if not isinstance(title, str) or not isinstance(url, str) or not isinstance(content, str):
            raise TavilyWebResearchAdapterError("Tavily search result is missing title/url/content.")
        hit = WebSearchHit(
            rank=len(hits) + 1,
            title=title,
            url=url,
            snippet=content,
            provider_score=float(score) if isinstance(score, (int, float)) else None,
        )
        hit.validate()
        canonical_url = hit.to_dict()["url"]
        if canonical_url in seen:
            continue
        seen.add(canonical_url)
        hits.append(hit)
        if len(hits) == budget.search_results_max:
            break

    evidence = WebSearchEvidence(
        adapter_id=ADAPTER_ID,
        request_id=request_id,
        query_sha256=intent.query_sha256(),
        provider_response_sha256=_sha256(response_body),
        hits=tuple(hits),
    )
    evidence.validate(max_results=budget.search_results_max)
    return evidence


def select_extract_urls(
    search: WebSearchEvidence,
    *,
    budget: WebResearchBudget,
) -> tuple[str, ...]:
    budget.validate_first_slice()
    search.validate(max_results=budget.search_results_max)
    return tuple(hit.to_dict()["url"] for hit in search.hits[: budget.extract_urls_max])


def compile_extract_request(
    *,
    request_id: str,
    urls: Iterable[str],
    budget: WebResearchBudget,
) -> tuple[NetworkRequest, bytes, tuple[str, ...]]:
    budget.validate_first_slice()
    exact_urls = tuple(urls)
    if not exact_urls or len(exact_urls) > budget.extract_urls_max:
        raise TavilyWebResearchAdapterError("Extract URL count must be within the exact first-slice bound.")
    # Reuse provider-neutral URL validation without importing provider-specific types.
    validated = []
    for rank, url in enumerate(exact_urls, start=1):
        probe = WebSearchHit(rank=rank, title="url-validation", url=url, snippet="")
        probe.validate()
        validated.append(probe.to_dict()["url"])
    if len(set(validated)) != len(validated):
        raise TavilyWebResearchAdapterError("Extract URL list must be unique after canonicalization.")

    payload = {
        "urls": validated,
        "extract_depth": "basic",
        "format": "markdown",
        "include_images": False,
    }
    body = canonical_json_bytes(payload)
    if len(body) > budget.request_body_bytes_max:
        raise TavilyWebResearchAdapterError("Tavily extract body exceeds first-slice request_body_bytes_max.")
    return (
        _request(
            request_id=request_id,
            url=EXTRACT_URL,
            role="web_research_extract",
            body=body,
            response_byte_budget=budget.extract_response_bytes_max,
        ),
        body,
        tuple(validated),
    )


def parse_extract_response(
    *,
    request_id: str,
    expected_urls: Iterable[str],
    budget: WebResearchBudget,
    response_body: bytes,
) -> WebExtractEvidence:
    budget.validate_first_slice()
    expected = tuple(expected_urls)
    try:
        payload = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TavilyWebResearchAdapterError("Tavily extract response is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise TavilyWebResearchAdapterError("Tavily extract response must be a JSON object.")
    results = payload.get("results")
    if not isinstance(results, list):
        raise TavilyWebResearchAdapterError("Tavily extract response.results must be an array.")
    by_url: dict[str, str] = {}
    for row in results:
        if not isinstance(row, dict):
            raise TavilyWebResearchAdapterError("Tavily extract result must be an object.")
        url = row.get("url")
        raw = row.get("raw_content")
        if not isinstance(url, str) or not isinstance(raw, str) or not raw:
            raise TavilyWebResearchAdapterError("Tavily extract result requires url and non-empty raw_content.")
        probe = WebSearchHit(rank=1, title="url-validation", url=url, snippet="")
        canonical_url = probe.to_dict()["url"]
        if canonical_url in by_url:
            raise TavilyWebResearchAdapterError("Tavily extract returned duplicate URL.")
        by_url[canonical_url] = raw

    documents: list[WebRetrievedDocument] = []
    for url in expected:
        probe = WebSearchHit(rank=1, title="url-validation", url=url, snippet="")
        canonical_url = probe.to_dict()["url"]
        if canonical_url not in by_url:
            continue
        documents.append(
            WebRetrievedDocument.from_content(
                rank=len(documents) + 1,
                url=canonical_url,
                content=by_url[canonical_url],
                retrieval_via="PROVIDER_EXTRACTED_PAGE_CONTENT",
            )
        )
    evidence = WebExtractEvidence(
        adapter_id=ADAPTER_ID,
        request_id=request_id,
        provider_response_sha256=_sha256(response_body),
        documents=tuple(documents),
    )
    evidence.validate(expected_urls=expected, max_documents=budget.extract_urls_max)
    return evidence


__all__ = [
    "ADAPTER_ID",
    "TAVILY_HOST",
    "SEARCH_URL",
    "EXTRACT_URL",
    "TavilyWebResearchAdapterError",
    "compile_search_request",
    "parse_search_response",
    "select_extract_urls",
    "compile_extract_request",
    "parse_extract_response",
]
