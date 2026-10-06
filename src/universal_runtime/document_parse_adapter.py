from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from typing import Mapping


class DocumentParseAdapterError(RuntimeError):
    """Fail-closed local document parser adapter error."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_NORMALIZE_RE = re.compile(r"[-_.]+")
_DEFAULT_MAX_INPUT_BYTES = 64 * 1024 * 1024
_DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024 * 1024


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalize_package_name(value: str) -> str:
    return _PACKAGE_NORMALIZE_RE.sub("-", value).lower()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class DoclingSidecarBinding:
    sidecar_root: Path
    combined_lock_sha256: str
    accepted_install_result_sha256: str
    expected_packages: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        root = Path(self.sidecar_root).resolve()
        object.__setattr__(self, "sidecar_root", root)
        if not _SHA256_RE.fullmatch(self.combined_lock_sha256):
            raise ValueError("combined_lock_sha256 must be lowercase 64-hex")
        if not _SHA256_RE.fullmatch(self.accepted_install_result_sha256):
            raise ValueError("accepted_install_result_sha256 must be lowercase 64-hex")
        normalized: dict[str, str] = {}
        for name, version in self.expected_packages:
            key = _normalize_package_name(name)
            if not key or not isinstance(version, str) or not version:
                raise ValueError("expected_packages contains an invalid name/version")
            if key in normalized and normalized[key] != version:
                raise ValueError("expected_packages contains conflicting normalized names")
            normalized[key] = version
        if len(normalized) != len(self.expected_packages):
            raise ValueError("expected_packages contains duplicate normalized names")

    @property
    def python_executable(self) -> Path:
        return self.sidecar_root / "Scripts" / "python.exe"

    def package_map(self) -> dict[str, str]:
        return {_normalize_package_name(k): v for k, v in self.expected_packages}


@dataclass(frozen=True)
class ParsedDocumentProposal:
    input_sha256: str
    input_format: str
    markdown_bytes: bytes
    json_bytes: bytes
    markdown_sha256: str
    json_sha256: str
    parser_binding: Mapping[str, object]
    warnings: tuple[str, ...]


def parse_local_document_proposal(
    *,
    input_path: Path | str,
    expected_input_sha256: str,
    allowed_roots: tuple[Path | str, ...],
    work_root: Path | str,
    sidecar: DoclingSidecarBinding,
    timeout_seconds: int = 120,
    max_input_bytes: int = _DEFAULT_MAX_INPUT_BYTES,
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
) -> ParsedDocumentProposal:
    """Parse one exact local PDF/DOCX into non-authoritative neutral bytes.

    This function does not persist Artifacts and does not mutate Project/Pack state.
    The caller remains responsible for Runtime-owned validation and persistence.
    """
    if not _SHA256_RE.fullmatch(expected_input_sha256):
        raise DocumentParseAdapterError("expected_input_sha256 must be lowercase 64-hex")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or timeout_seconds < 1:
        raise DocumentParseAdapterError("timeout_seconds must be an integer >= 1")
    if not isinstance(max_input_bytes, int) or max_input_bytes < 1:
        raise DocumentParseAdapterError("max_input_bytes must be >= 1")
    if not isinstance(max_output_bytes, int) or max_output_bytes < 1:
        raise DocumentParseAdapterError("max_output_bytes must be >= 1")

    from universal_runtime.core.file_resolver import FileResolver, FileResolutionError

    try:
        resolved = FileResolver(
            allowed_roots,
            allowed_extensions=(".pdf", ".docx"),
        ).resolve(input_path, required=True)
    except (FileResolutionError, FileNotFoundError, ValueError) as exc:
        raise DocumentParseAdapterError(str(exc)) from exc
    if resolved is None:
        raise DocumentParseAdapterError("input file is required")
    if resolved.byte_length > max_input_bytes:
        raise DocumentParseAdapterError("input exceeds max_input_bytes")

    before_bytes = resolved.path.read_bytes()
    before_sha = _sha256_bytes(before_bytes)
    if before_sha != expected_input_sha256:
        raise DocumentParseAdapterError("input SHA mismatch before parser execution")

    sidecar_python = sidecar.python_executable
    if not sidecar_python.is_file():
        raise DocumentParseAdapterError("sidecar Python executable is missing")
    if sidecar_python.resolve().parent.parent != sidecar.sidecar_root:
        raise DocumentParseAdapterError("sidecar Python resolves outside the exact sidecar root")

    work = Path(work_root).resolve()
    if not work.is_dir():
        raise DocumentParseAdapterError("work_root must be an existing directory")

    expected_packages = sidecar.package_map()
    required = {
        "docling-slim": "2.126.0",
        "docling-core": "2.95.0",
        "docling-parse": "7.17.0",
        "scipy": "1.18.1",
        "rtree": "1.4.1",
    }
    if any(expected_packages.get(k) != v for k, v in required.items()):
        raise DocumentParseAdapterError("sidecar package binding does not match the accepted C1 parser set")

    input_format = "pdf" if resolved.extension == ".pdf" else "docx"

    with tempfile.TemporaryDirectory(prefix="ur_docling_parse_", dir=work) as td:
        run_dir = Path(td)
        request_path = run_dir / "worker_request.json"
        request = {
            "schema": "UR_DOCLING_SIDE_CAR_WORKER_REQUEST_R001",
            "input_path": str(resolved.path),
            "input_sha256": before_sha,
            "input_format": input_format,
            "combined_lock_sha256": sidecar.combined_lock_sha256,
            "accepted_install_result_sha256": sidecar.accepted_install_result_sha256,
            "expected_packages": expected_packages,
            "output_dir": str(run_dir),
        }
        request_path.write_bytes(_canonical_json_bytes(request))

        env = os.environ.copy()
        env.update(
            {
                "PYTHONNOUSERSITE": "1",
                "PIP_NO_INDEX": "1",
                "HTTP_PROXY": "",
                "HTTPS_PROXY": "",
                "ALL_PROXY": "",
                "NO_PROXY": "*",
            }
        )
        command = [
            str(sidecar_python),
            str(Path(__file__).resolve()),
            "--docling-worker",
            str(request_path),
        ]
        try:
            completed = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise DocumentParseAdapterError("sidecar parser timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            if len(detail) > 2000:
                detail = detail[-2000:]
            raise DocumentParseAdapterError(
                f"sidecar parser failed with exit {completed.returncode}: {detail}"
            )

        result_path = run_dir / "worker_result.json"
        markdown_path = run_dir / "document.md"
        json_path = run_dir / "document.json"
        for candidate in (result_path, markdown_path, json_path):
            if not candidate.is_file():
                raise DocumentParseAdapterError(f"sidecar output is missing: {candidate.name}")
            if candidate.stat().st_size > max_output_bytes:
                raise DocumentParseAdapterError(f"sidecar output exceeds limit: {candidate.name}")

        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DocumentParseAdapterError("sidecar result envelope is invalid") from exc
        if result.get("schema") != "UR_DOCLING_SIDE_CAR_WORKER_RESULT_R001":
            raise DocumentParseAdapterError("sidecar result schema mismatch")
        if result.get("status") != "PASS":
            raise DocumentParseAdapterError("sidecar result is not PASS")
        if result.get("input_sha256") != before_sha or result.get("input_format") != input_format:
            raise DocumentParseAdapterError("sidecar input binding mismatch")
        if result.get("combined_lock_sha256") != sidecar.combined_lock_sha256:
            raise DocumentParseAdapterError("sidecar lock binding mismatch")
        if result.get("accepted_install_result_sha256") != sidecar.accepted_install_result_sha256:
            raise DocumentParseAdapterError("sidecar install-receipt binding mismatch")

        installed = result.get("installed_packages")
        if not isinstance(installed, dict) or {
            _normalize_package_name(k): str(v) for k, v in installed.items()
        } != expected_packages:
            raise DocumentParseAdapterError("sidecar installed package set mismatch")

        markdown_bytes = markdown_path.read_bytes()
        json_bytes = json_path.read_bytes()
        if _sha256_bytes(markdown_bytes) != result.get("markdown_sha256"):
            raise DocumentParseAdapterError("Markdown output SHA mismatch")
        if _sha256_bytes(json_bytes) != result.get("json_sha256"):
            raise DocumentParseAdapterError("JSON output SHA mismatch")
        try:
            json.loads(json_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DocumentParseAdapterError("document JSON output is invalid UTF-8 JSON") from exc
        try:
            markdown_bytes.decode("utf-8")
        except UnicodeError as exc:
            raise DocumentParseAdapterError("Markdown output is not UTF-8") from exc

        after_sha = _sha256_bytes(resolved.path.read_bytes())
        if after_sha != before_sha:
            raise DocumentParseAdapterError("input bytes changed during parser execution")

        raw_warnings = result.get("warnings", [])
        if not isinstance(raw_warnings, list) or any(not isinstance(x, str) for x in raw_warnings):
            raise DocumentParseAdapterError("sidecar warnings payload is invalid")

        parser_binding = {
            "component": "docling-slim",
            "component_version": expected_packages["docling-slim"],
            "docling_core_version": expected_packages["docling-core"],
            "docling_parse_version": expected_packages["docling-parse"],
            "scipy_version": expected_packages["scipy"],
            "rtree_version": expected_packages["rtree"],
            "combined_lock_sha256": sidecar.combined_lock_sha256,
            "accepted_install_result_sha256": sidecar.accepted_install_result_sha256,
            "pipeline": result.get("pipeline"),
        }
        return ParsedDocumentProposal(
            input_sha256=before_sha,
            input_format=input_format,
            markdown_bytes=markdown_bytes,
            json_bytes=json_bytes,
            markdown_sha256=_sha256_bytes(markdown_bytes),
            json_sha256=_sha256_bytes(json_bytes),
            parser_binding=parser_binding,
            warnings=tuple(raw_warnings),
        )


def _worker_fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _worker_main(request_path: str) -> int:
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    except Exception as exc:
        return _worker_fail(f"WORKER_REQUEST_INVALID:{exc}")

    try:
        if request.get("schema") != "UR_DOCLING_SIDE_CAR_WORKER_REQUEST_R001":
            raise ValueError("request schema mismatch")
        input_path = Path(request["input_path"]).resolve()
        output_dir = Path(request["output_dir"]).resolve()
        expected_sha = str(request["input_sha256"])
        input_format = str(request["input_format"])
        expected_packages = {
            _normalize_package_name(k): str(v)
            for k, v in dict(request["expected_packages"]).items()
        }
        if input_format not in {"pdf", "docx"}:
            raise ValueError("input format is not allowlisted")
        if not input_path.is_file() or not output_dir.is_dir():
            raise ValueError("worker input/output path is invalid")
        before = input_path.read_bytes()
        if _sha256_bytes(before) != expected_sha:
            raise ValueError("worker input SHA mismatch")

        have: dict[str, str] = {}
        for dist in distributions():
            name = dist.metadata.get("Name")
            if name:
                have[_normalize_package_name(name)] = dist.version
        bootstrap = {"pip", "setuptools", "wheel"}
        relevant_have = {k: v for k, v in have.items() if k not in bootstrap}
        if relevant_have != expected_packages:
            missing = sorted(set(expected_packages) - set(relevant_have))
            extra = sorted(set(relevant_have) - set(expected_packages))
            wrong = sorted(
                k for k in set(expected_packages).intersection(relevant_have)
                if expected_packages[k] != relevant_have[k]
            )
            raise ValueError(
                f"installed package set mismatch missing={missing} extra={extra} wrong={wrong}"
            )

        def deny_network(*args: object, **kwargs: object) -> None:
            raise RuntimeError("NETWORK_ATTEMPT_FORBIDDEN")
        socket.create_connection = deny_network  # type: ignore[assignment]
        socket.socket.connect = deny_network  # type: ignore[assignment]

        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import NativePdfPipelineOptions
        from docling.document_converter import (
            DocumentConverter,
            NativePdfFormatOption,
            WordFormatOption,
        )
        from docling.pipeline.simple_pipeline import SimplePipeline

        format_options = {
            InputFormat.PDF: NativePdfFormatOption(
                pipeline_options=NativePdfPipelineOptions()
            ),
            InputFormat.DOCX: WordFormatOption(pipeline_cls=SimplePipeline),
        }
        converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX],
            format_options=format_options,
        )
        result = converter.convert(input_path)
        status = str(result.status.value if hasattr(result.status, "value") else result.status)
        if status.lower() != "success":
            raise RuntimeError(f"Docling conversion status is not success: {status}")

        markdown = result.document.export_to_markdown()
        neutral_json = result.document.export_to_dict()
        markdown_bytes = markdown.encode("utf-8")
        json_bytes = _canonical_json_bytes(neutral_json)
        (output_dir / "document.md").write_bytes(markdown_bytes)
        (output_dir / "document.json").write_bytes(json_bytes)

        errors = getattr(result, "errors", None) or []
        warnings = [str(item) for item in errors]
        pipeline = "NativePdfPipeline" if input_format == "pdf" else "SimplePipeline"
        envelope = {
            "schema": "UR_DOCLING_SIDE_CAR_WORKER_RESULT_R001",
            "status": "PASS",
            "input_sha256": expected_sha,
            "input_format": input_format,
            "combined_lock_sha256": request["combined_lock_sha256"],
            "accepted_install_result_sha256": request["accepted_install_result_sha256"],
            "installed_packages": expected_packages,
            "pipeline": pipeline,
            "markdown_sha256": _sha256_bytes(markdown_bytes),
            "json_sha256": _sha256_bytes(json_bytes),
            "warnings": warnings,
        }
        (output_dir / "worker_result.json").write_bytes(_canonical_json_bytes(envelope))
        if _sha256_bytes(input_path.read_bytes()) != expected_sha:
            raise RuntimeError("input bytes changed during worker execution")
        return 0
    except Exception as exc:
        return _worker_fail(f"WORKER_FAILED:{type(exc).__name__}:{exc}")


def _main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docling-worker", action="store_true")
    parser.add_argument("request_path", nargs="?")
    args = parser.parse_args()
    if not args.docling_worker or not args.request_path:
        parser.error("this module is only executable in --docling-worker mode")
    return _worker_main(args.request_path)


if __name__ == "__main__":
    raise SystemExit(_main())
