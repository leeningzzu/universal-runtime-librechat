import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from universal_runtime.core.file_resolver import FileResolutionError, FileResolver
from universal_runtime.core.load_plan import LoadInput, LoadPlan, LoadPlanError
from universal_runtime.prompts.reference_loader import PromptReferenceError, PromptReferenceLoader


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_markdown_allowlist_and_sha(tmp_path: Path):
    root = tmp_path / 'imports'; root.mkdir()
    path = root / 'prompt.md'; data = b'# prompt\n'; path.write_bytes(data)
    loaded = PromptReferenceLoader(FileResolver([root])).load(path, _sha(data))
    assert loaded.path == path.resolve()
    assert loaded.byte_length == len(data)
    assert loaded.sha256 == _sha(data)
    assert loaded.content == '# prompt\n'


def test_resolver_rejects_missing_traversal_and_extension(tmp_path: Path):
    root = tmp_path / 'root'; root.mkdir()
    resolver = FileResolver([root])
    with pytest.raises(FileNotFoundError): resolver.resolve(root / 'missing.md')
    with pytest.raises(FileResolutionError): resolver.resolve(root / '..' / 'secret.md')
    bad = root / 'run.py'; bad.write_text('x')
    with pytest.raises(FileResolutionError): resolver.resolve(bad)


def test_resolver_rejects_canonical_escape_and_symlink(tmp_path: Path):
    root = tmp_path / 'root'; outside = tmp_path / 'outside'; root.mkdir(); outside.mkdir()
    target = outside / 'secret.md'; target.write_text('secret')
    with pytest.raises(FileResolutionError): FileResolver([root]).resolve(target)
    link = root / 'link.md'
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'symlink unavailable on this platform: {exc}')
    with pytest.raises(FileResolutionError): FileResolver([root]).resolve(link)


def test_sha_mismatch_fails_before_decode(tmp_path: Path):
    path = tmp_path / 'prompt.md'; path.write_bytes(b'\xff')
    with pytest.raises(PromptReferenceError, match='SHA-256 mismatch'):
        PromptReferenceLoader(FileResolver([tmp_path])).load(path, '0' * 64)


def test_docx_parse_is_deterministic(tmp_path: Path):
    path = tmp_path / 'prompt.docx'
    xml = b'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>One</w:t></w:r></w:p><w:p><w:r><w:t>Two</w:t></w:r></w:p></w:body></w:document>'''
    with zipfile.ZipFile(path, 'w') as archive: archive.writestr('word/document.xml', xml)
    digest = _sha(path.read_bytes()); loader = PromptReferenceLoader(FileResolver([tmp_path]))
    first = loader.load(path, digest).content
    second = loader.load(path, digest).content
    assert first == second == 'One\nTwo'


def test_load_plan_scope_and_budget(tmp_path: Path):
    plan = LoadPlan.from_inputs(
        plan_id='plan', project_root=str(tmp_path), allowed_roots=[str(tmp_path)],
        required_inputs=[LoadInput(reference='prompt.md', role='prompt', byte_budget=3)],
        execution_budget=1, load_budget=3,
    )
    plan.validate([3])
    with pytest.raises(LoadPlanError): plan.validate([4])
    with pytest.raises(LoadPlanError):
        PromptReferenceLoader(FileResolver([tmp_path])).load(tmp_path / 'prompt.md', '0' * 64, plan=plan)

