from __future__ import annotations

import hashlib
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

FASTEMBED_VERSION = "0.8.0"
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_ONNX_SHA256 = "634d0f66c29dc934c8fa72b8a4fe91dd4d420a22f1d82a241058d4316e659a99"
TOKENIZER_SHA256 = "fa685fc160bbdbab64058d4fc91b60e62d207e8dc60b9af5c002c5ab946ded00"
DEFAULT_SIDECAR_REL = Path(".sidecars") / "fastembed_0_8_0_multilingual_minilm_r001"
MAX_QUERY_CHARS = 1200
MAX_PROJECT_SOURCES = 12
MAX_SOURCE_CHARS = 24000
MAX_TOP_K = 5


class ProjectSemanticSearchError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ProjectSemanticSearchError("SEMANTIC_SEARCH_BINDING_INVALID", f"{field} invalid")
    return value


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        raise ProjectSemanticSearchError("SEMANTIC_SEARCH_VECTOR_INVALID", "vector dimensions differ")
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


class ProjectSemanticSearchAdapter:
    """Web-owned source-level semantic search over exact Runtime Project SourceRefs.

    Deliberately not a generic retrieval engine. The retained FastEmbed sidecar
    proposes vectors; Runtime Project/SourceRef/Artifact currentness remains authoritative.
    """

    def __init__(self, *, runtime_root: Path, service: Any, sidecar_root: Path | None = None):
        self.runtime_root = Path(runtime_root).resolve()
        self.service = service
        self.sidecar_root = (
            Path(sidecar_root).resolve()
            if sidecar_root is not None
            else (self.runtime_root / DEFAULT_SIDECAR_REL).resolve()
        )
        self.sidecar_python = self.sidecar_root / "venv" / "Scripts" / "python.exe"
        self.model_dir = self.sidecar_root / "model"

    def _sidecar_currentness(self) -> None:
        if not self.sidecar_python.is_file():
            raise ProjectSemanticSearchError("FASTEMBED_SIDECAR_MISSING", "FastEmbed sidecar Python missing", status_code=503)
        model_file = self.model_dir / "model_optimized.onnx"
        tokenizer = self.model_dir / "tokenizer.json"
        if not model_file.is_file() or _sha256_bytes(model_file.read_bytes()) != MODEL_ONNX_SHA256:
            raise ProjectSemanticSearchError("FASTEMBED_MODEL_STALE", "FastEmbed model bytes differ", status_code=503)
        if not tokenizer.is_file() or _sha256_bytes(tokenizer.read_bytes()) != TOKENIZER_SHA256:
            raise ProjectSemanticSearchError("FASTEMBED_TOKENIZER_STALE", "FastEmbed tokenizer bytes differ", status_code=503)

    @staticmethod
    def _binding_triplet(binding: dict[str, Any], field: str) -> tuple[str, int, str]:
        if not isinstance(binding, dict):
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_BINDING_INVALID", f"{field} missing")
        identity = _require_sha(binding.get("artifact_identity_sha256"), f"{field}.artifact_identity_sha256")
        revision = binding.get("revision")
        sha256 = _require_sha(binding.get("sha256"), f"{field}.sha256")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_BINDING_INVALID", f"{field}.revision invalid")
        return identity, revision, sha256

    def _current_source_rows(self, project_id: str) -> list[dict[str, Any]]:
        resume = self.service.resume_project(project_id)
        rows = resume.get("sources", [])
        if not isinstance(rows, list):
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_PROJECT_INVALID", "project source projection invalid")
        if len(rows) > MAX_PROJECT_SOURCES:
            raise ProjectSemanticSearchError(
                "SEMANTIC_SEARCH_SOURCE_LIMIT",
                f"first slice supports at most {MAX_PROJECT_SOURCES} project sources",
                status_code=413,
            )
        current: list[dict[str, Any]] = []
        for item in rows:
            ref = item.get("source_ref") if isinstance(item, dict) else None
            derivation = item.get("text_derivation") if isinstance(item, dict) else None
            derivation_binding = item.get("derivation_binding") if isinstance(item, dict) else None
            if not isinstance(ref, dict) or not isinstance(derivation, dict) or not isinstance(derivation_binding, dict):
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_SOURCE_INVALID", "source projection incomplete")
            if ref.get("project_id") != project_id:
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_SCOPE_MISMATCH", "SourceRef project mismatch")
            sid = ref.get("source_ref_id")
            if not isinstance(sid, str) or not sid:
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_SOURCE_INVALID", "source_ref_id missing")
            source_binding = ref.get("source_artifact_binding")
            identity, revision, source_sha = self._binding_triplet(source_binding, "source_artifact_binding")
            try:
                _, raw = self.service.store.load_exact_r009_opaque_artifact_r001_v1(
                    artifact_identity_sha256=identity,
                    artifact_revision=revision,
                    artifact_sha256=source_sha,
                )
            except Exception as exc:
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_SOURCE_STALE", "exact source bytes failed currentness") from exc
            if _sha256_bytes(raw) != source_sha:
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_SOURCE_STALE", "source SHA mismatch")

            expected_derivation = ref.get("derived_projection_binding")
            if not isinstance(expected_derivation, dict):
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_DERIVATION_STALE", "derived projection binding missing")
            if (
                derivation_binding.get("artifact_id") != expected_derivation.get("artifact_id")
                or derivation_binding.get("revision") != expected_derivation.get("revision")
                or derivation_binding.get("sha256") != expected_derivation.get("sha256")
            ):
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_DERIVATION_STALE", "text derivation binding changed")
            if derivation.get("source_sha256") != source_sha:
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_DERIVATION_STALE", "derivation source SHA mismatch")
            text = derivation.get("decoded_text")
            derivation_sha = _require_sha(derivation.get("derivation_sha256"), "derivation_sha256")
            if not isinstance(text, str) or _sha256_bytes(text.encode("utf-8")) != derivation_sha:
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_DERIVATION_STALE", "decoded text differs")

            truncated = len(text) > MAX_SOURCE_CHARS
            current.append(
                {
                    "project_id": project_id,
                    "source_ref_id": sid,
                    "source_artifact_sha256": source_sha,
                    "filename": str(ref.get("filename") or "Unnamed Source"),
                    "text": text[:MAX_SOURCE_CHARS],
                    "text_truncated": truncated,
                }
            )
        return current

    def _embed(self, *, texts: list[str], query: str) -> tuple[list[list[float]], list[float]]:
        self._sidecar_currentness()
        with tempfile.TemporaryDirectory(prefix="ur_p2c_semantic_search_") as td:
            td_path = Path(td)
            inp = td_path / "input.json"
            out = td_path / "output.json"
            inp.write_text(json.dumps({"texts": texts, "query": query}, ensure_ascii=False), encoding="utf-8")
            env = dict(os.environ)
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            cp = subprocess.run(
                [str(self.sidecar_python), "-B", str(Path(__file__).resolve()), "--embed", str(inp), str(out), str(self.model_dir)],
                cwd=str(self.runtime_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if cp.returncode != 0 or not out.is_file():
                raise ProjectSemanticSearchError("FASTEMBED_LOCAL_EXECUTION_STOP", "local FastEmbed execution failed", status_code=503)
            result = json.loads(out.read_text(encoding="utf-8"))
        if result.get("result") != "PASS" or result.get("fastembed_version") != FASTEMBED_VERSION:
            raise ProjectSemanticSearchError("FASTEMBED_LOCAL_EXECUTION_STOP", "FastEmbed result invalid", status_code=503)
        vectors = result.get("vectors")
        query_vector = result.get("query_vector")
        if not isinstance(vectors, list) or not isinstance(query_vector, list):
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_VECTOR_INVALID", "embedding output invalid", status_code=503)
        return [[float(x) for x in row] for row in vectors], [float(x) for x in query_vector]

    def search(self, *, project_id: str, query: str, top_k: int = 3) -> dict[str, Any]:
        if not isinstance(project_id, str) or not project_id:
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_PROJECT_INVALID", "project_id required", status_code=400)
        if not isinstance(query, str) or not query.strip():
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_QUERY_INVALID", "query required", status_code=400)
        query = query.strip()
        if len(query) > MAX_QUERY_CHARS:
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_QUERY_TOO_LONG", "query too long", status_code=413)
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1 or top_k > MAX_TOP_K:
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_TOP_K_INVALID", "top_k out of range", status_code=400)

        before = self._current_source_rows(project_id)
        if not before:
            return {
                "schema": "UR_WEB_R004_P2C_PROJECT_SEMANTIC_SEARCH_RESPONSE_R001",
                "authority_class": "NON_AUTHORITY_RETRIEVAL_PROPOSAL",
                "result": "PASS_EMPTY_PROJECT",
                "project_id": project_id,
                "query_sha256": _sha256_bytes(query.encode("utf-8")),
                "results": [],
                "source_count": 0,
                "network_calls": 0,
                "external_model_provider_calls": 0,
            }

        vectors, query_vector = self._embed(texts=[row["text"] for row in before], query=query)
        if len(vectors) != len(before):
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_VECTOR_INVALID", "embedding row count differs")
        scores = [_cosine(query_vector, vector) for vector in vectors]
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[: min(top_k, len(before))]

        after = self._current_source_rows(project_id)
        before_map = {row["source_ref_id"]: row["source_artifact_sha256"] for row in before}
        after_map = {row["source_ref_id"]: row["source_artifact_sha256"] for row in after}
        if before_map != after_map:
            raise ProjectSemanticSearchError("SEMANTIC_SEARCH_PROJECT_STALE", "Project source registry changed during retrieval")

        results = []
        for rank, idx in enumerate(order, start=1):
            row = before[idx]
            if after_map.get(row["source_ref_id"]) != row["source_artifact_sha256"]:
                raise ProjectSemanticSearchError("SEMANTIC_SEARCH_SOURCE_STALE", "returned SourceRef became stale")
            results.append(
                {
                    "rank": rank,
                    "score": scores[idx],
                    "project_id": project_id,
                    "source_ref_id": row["source_ref_id"],
                    "source_artifact_sha256": row["source_artifact_sha256"],
                    "filename": row["filename"],
                    "excerpt": row["text"].replace("\r", " ").replace("\n", " ").strip()[:280],
                    "source_text_truncated_for_embedding": row["text_truncated"],
                    "runtime_currentness_revalidated": True,
                }
            )

        return {
            "schema": "UR_WEB_R004_P2C_PROJECT_SEMANTIC_SEARCH_RESPONSE_R001",
            "authority_class": "NON_AUTHORITY_RETRIEVAL_PROPOSAL",
            "result": "PASS",
            "project_id": project_id,
            "query_sha256": _sha256_bytes(query.encode("utf-8")),
            "retrieval_mode": "SOURCE_LEVEL_FIRST_SLICE",
            "embedding_component": f"fastembed@{FASTEMBED_VERSION}",
            "embedding_model": MODEL_NAME,
            "source_count": len(before),
            "top_k": min(top_k, len(before)),
            "results": results,
            "network_calls": 0,
            "external_model_provider_calls": 0,
            "runtime_source_registry_revalidated": True,
        }


def _embed_cli(input_path: Path, output_path: Path, model_dir: Path) -> None:
    import importlib.metadata

    if importlib.metadata.version("fastembed") != FASTEMBED_VERSION:
        raise RuntimeError("FASTEMBED_VERSION_STOP")
    model_file = model_dir / "model_optimized.onnx"
    tokenizer = model_dir / "tokenizer.json"
    if not model_file.is_file() or _sha256_bytes(model_file.read_bytes()) != MODEL_ONNX_SHA256:
        raise RuntimeError("FASTEMBED_MODEL_SHA_STOP")
    if not tokenizer.is_file() or _sha256_bytes(tokenizer.read_bytes()) != TOKENIZER_SHA256:
        raise RuntimeError("FASTEMBED_TOKENIZER_SHA_STOP")

    def deny_connect(self: socket.socket, address: Any) -> None:
        raise RuntimeError(f"NETWORK_FORBIDDEN:{address!r}")

    socket.socket.connect = deny_connect
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    from fastembed import TextEmbedding

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    texts = payload.get("texts")
    query = payload.get("query")
    if not isinstance(texts, list) or any(not isinstance(x, str) for x in texts) or not isinstance(query, str):
        raise RuntimeError("EMBED_INPUT_INVALID")
    model = TextEmbedding(model_name=MODEL_NAME, specific_model_path=str(model_dir), local_files_only=True)
    vectors = [list(map(float, v)) for v in model.embed(texts)]
    query_vector = list(map(float, next(iter(model.embed([query])))))
    output_path.write_text(
        json.dumps(
            {
                "schema": "UR_WEB_R004_P2C_FASTEMBED_SOURCE_SEARCH_VECTOR_RESULT_R001",
                "result": "PASS",
                "fastembed_version": FASTEMBED_VERSION,
                "model_name": MODEL_NAME,
                "vectors": vectors,
                "query_vector": query_vector,
                "network_calls": 0,
                "external_model_provider_calls": 0,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--embed":
        raise SystemExit("usage: web_project_semantic_search.py --embed INPUT OUTPUT MODEL_DIR")
    _embed_cli(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
