from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from universal_runtime.core.file_resolver import FileResolver, ResolvedFile
from universal_runtime.core.load_plan import LoadPlan, LoadPlanError


class PromptReferenceError(ValueError):
    """Raised when a prompt reference fails deterministic validation or parsing."""


@dataclass(frozen=True)
class LoadedReference:
    path: Path
    byte_length: int
    sha256: str
    provenance: str
    content: str


class PromptReferenceLoader:
    def __init__(self, resolver: FileResolver):
        self.resolver = resolver

    def load(self, reference: Path | str, expected_sha256: str, *, parse_mode: str | None = None, plan: LoadPlan | None = None, provenance: str | None = None) -> LoadedReference:
        if plan is not None:
            plan.validate()
            declared = {item.reference: item for item in plan.required_inputs}
            if str(reference) not in declared:
                raise LoadPlanError('Reference is not declared in the validated LoadPlan.')
            parse_mode = parse_mode or declared[str(reference)].parse_mode
        resolved = self.resolver.resolve(reference)
        assert resolved is not None
        raw = resolved.path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest.lower() != expected_sha256.lower():
            raise PromptReferenceError('SHA-256 mismatch.')
        mode = (parse_mode or ('docx' if resolved.extension == '.docx' else 'markdown')).lower()
        if mode in {'markdown', 'md', 'text'}:
            try:
                content = raw.decode('utf-8')
            except UnicodeDecodeError as exc:
                raise PromptReferenceError('Markdown is not valid UTF-8.') from exc
        elif mode == 'docx':
            content = self._parse_docx(raw)
        elif mode == 'bytes':
            content = raw.decode('utf-8')
        else:
            raise PromptReferenceError(f'Unsupported parse mode: {parse_mode}')
        return LoadedReference(resolved.path, len(raw), digest, provenance or str(resolved.path), content)

    def load_reference(self, *args, **kwargs) -> LoadedReference:
        return self.load(*args, **kwargs)

    @staticmethod
    def _parse_docx(raw: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                xml = archive.read('word/document.xml')
            root = ElementTree.fromstring(xml)
        except (KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise PromptReferenceError('Invalid DOCX reference.') from exc
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        paragraphs = []
        for paragraph in root.findall('.//w:p', ns):
            parts = [node.text or '' for node in paragraph.findall('.//w:t', ns)]
            paragraphs.append(''.join(parts))
        return '\n'.join(paragraphs)
