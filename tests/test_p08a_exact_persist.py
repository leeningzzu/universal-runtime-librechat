from pathlib import Path

from universal_runtime.core.artifact_store import ArtifactStore
from universal_runtime.core.hashing import sha256_text


def test_p08a_exact_bytes(tmp_path: Path):
    text = '# 草案\n\n第一行。\n第二行。\n'
    store = ArtifactStore(tmp_path / 'artifacts')
    manifest = store.persist_exact_text(
        artifact_id='P08', relative_path='draft.md', text=text, job_id='JOB'
    )
    saved = Path(manifest.path).read_text(encoding='utf-8')
    assert saved == text
    assert manifest.sha256 == sha256_text(text)
