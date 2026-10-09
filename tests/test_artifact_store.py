from pathlib import Path

import pytest

from universal_runtime.core.artifact_store import ArtifactCurrentnessError, ArtifactStore


def test_store_blocks_path_escape(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    with pytest.raises(PermissionError):
        store.persist_exact_text(artifact_id='A', relative_path='../escape.txt', text='x', job_id='J')


def test_revision_increments(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    a = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='one', job_id='J1')
    b = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='two', job_id='J2')
    assert a.revision == 1
    assert b.revision == 2


def test_exact_current_binding_becomes_stale_after_new_revision(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    first = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='one', job_id='J1')
    assert store.assert_current('A', first.revision, first.sha256).revision == 1

    second = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='two', job_id='J2')
    with pytest.raises(ArtifactCurrentnessError, match='Stale artifact binding'):
        store.assert_current('A', first.revision, first.sha256)
    current = store.assert_current('A', second.revision, second.sha256)
    assert current.revision == 2
    assert current.sha256 == second.sha256


def test_current_binding_rejects_wrong_sha_and_missing_history(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    current = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='one', job_id='J1')
    with pytest.raises(ArtifactCurrentnessError, match='Stale artifact binding'):
        store.assert_current('A', current.revision, '0' * 64)
    with pytest.raises(ArtifactCurrentnessError, match='history not found'):
        store.assert_current('MISSING', 1, '0' * 64)


def test_current_binding_rejects_tampered_current_bytes(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    current = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='one', job_id='J1')
    Path(current.path).write_text('tampered', encoding='utf-8')
    with pytest.raises(ArtifactCurrentnessError, match='bytes do not match'):
        store.assert_current('A', current.revision, current.sha256)


def test_current_binding_rejects_invalid_current_manifest(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    current = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='one', job_id='J1')
    store.manifest_path('A', current.revision).write_text('{}', encoding='utf-8')
    with pytest.raises(ArtifactCurrentnessError, match='manifest is invalid'):
        store.assert_current('A', current.revision, current.sha256)


def test_current_binding_rejects_manifest_root_escape(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    with pytest.raises(ArtifactCurrentnessError, match='escapes'):
        store.current_manifest('../outside')


CURRENT_INVENTORY_ARTIFACT_IDS = (
    'BIOMEDICAL_STATISTICS_FIRST_SLICE_G10_FRESH_PROFESSOR_AND_PROJECT_STATISTICIAN_REVIEW_R001',
    'F2_GOVERNMENT_LIVE_SEMANTIC_CANDIDATE',
    'OKD_F1A_TEACHER_STRATEGY_CANDIDATE',
    'OKD_F1B_INDEPENDENT_VALIDATION_RESULT',
    'OKD_F1B_SELF_DISTILLATION_CANDIDATE',
)


@pytest.mark.parametrize('artifact_id', CURRENT_INVENTORY_ARTIFACT_IDS)
def test_manifest_namespace_accepts_exact_inventory_ids(tmp_path: Path, artifact_id: str):
    store = ArtifactStore(tmp_path / 'artifacts')
    assert store.next_revision(artifact_id) == 1
    assert store.manifest_path(artifact_id, 1).parent.name == artifact_id


@pytest.mark.parametrize(
    'artifact_id',
    [
        '', None, 1, 'a', 'Artifact', 'A/B', r'A\B', 'A//B', r'A\\B',
        'A/', 'A\\', 'A/../B', 'A/./B', '.', '..', '/A', r'\A',
        'C:A', r'C:\A', r'\server\share', 'A:B', 'A.', 'A ', 'A-B',
        'A~B', 'Á',
    ],
)
def test_manifest_namespace_rejects_alias_forms_before_mutation(tmp_path: Path, artifact_id):
    store = ArtifactStore(tmp_path / 'artifacts')
    target = store.root / 'must_not_exist.txt'
    with pytest.raises(PermissionError):
        store.persist_exact_text(
            artifact_id=artifact_id,
            relative_path='must_not_exist.txt',
            text='x',
            job_id='J',
        )
    assert not target.exists()
    assert not (store.root / '_manifests').exists()


@pytest.mark.parametrize(
    'artifact_id',
    ['CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)], *[f'LPT{i}' for i in range(1, 10)]],
)
def test_manifest_namespace_rejects_reserved_windows_device_names(tmp_path: Path, artifact_id: str):
    store = ArtifactStore(tmp_path / 'artifacts')
    with pytest.raises(PermissionError, match='reserved Windows device'):
        store.next_revision(artifact_id)


def test_all_manifest_surfaces_share_namespace_guard(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    with pytest.raises(PermissionError):
        store.next_revision('A/B')
    with pytest.raises(PermissionError):
        store.manifest_path('A/B', 1)
    with pytest.raises(PermissionError):
        store.persist_exact_text(artifact_id='A/B', relative_path='x.txt', text='x', job_id='J')
    with pytest.raises(ArtifactCurrentnessError):
        store.current_manifest('A/B')


def test_case_alias_attempt_is_rejected_without_rewrite(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    persisted = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='one', job_id='J')
    assert persisted.artifact_id == 'A'
    with pytest.raises(PermissionError):
        store.next_revision('a')
    assert store.next_revision('A') == 2


def test_manifest_namespace_symlink_redirection_fails_closed(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    manifest_root = store.root / '_manifests'
    manifest_root.mkdir(parents=True)
    target = manifest_root / 'TARGET'
    target.mkdir()
    redirect = manifest_root / 'REDIRECT'
    try:
        redirect.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'directory symlink unavailable: {exc}')
    with pytest.raises(PermissionError, match='redirected'):
        store.manifest_path('REDIRECT', 1)


def test_manifest_root_redirection_fails_closed(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    outside = tmp_path / 'outside_manifests'
    outside.mkdir()
    manifest_root = store.root / '_manifests'
    try:
        manifest_root.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'directory symlink unavailable: {exc}')
    with pytest.raises(PermissionError, match='manifest root is redirected'):
        store.next_revision('A')

def _on_disk_manifest(store: ArtifactStore, artifact_id: str, revision: int) -> dict:
    import json

    return json.loads(store.manifest_path(artifact_id, revision).read_text(encoding='utf-8'))


def _make_legacy_absolute_manifest(store: ArtifactStore, artifact_id: str, relative_path: str, text: str):
    import json

    persisted = store.persist_exact_text(
        artifact_id=artifact_id,
        relative_path=relative_path,
        text=text,
        job_id='LEGACY',
    )
    path = store.manifest_path(artifact_id, persisted.revision)
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['path'] = persisted.path
    path.write_text(json.dumps(raw, indent=2), encoding='utf-8')
    return persisted


def test_new_manifest_is_portable_on_disk_but_returned_path_stays_usable(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    persisted = store.persist_exact_text(artifact_id='A', relative_path='nested/a.txt', text='one', job_id='J')
    disk = _on_disk_manifest(store, 'A', persisted.revision)

    assert disk['path'] == 'nested/a.txt'
    assert str(store.root) not in disk['path']
    assert Path(persisted.path).read_text(encoding='utf-8') == 'one'

    current = store.current_manifest('A')
    assert Path(current.path).resolve() == (store.root / 'nested' / 'a.txt').resolve()
    assert Path(current.path).read_text(encoding='utf-8') == 'one'


def test_new_portable_store_copy_rebinds_to_new_root_without_manifest_rewrite(tmp_path: Path):
    import shutil

    source = ArtifactStore(tmp_path / 'source')
    persisted = source.persist_exact_text(
        artifact_id='A', relative_path='nested/a.txt', text='portable', job_id='J'
    )
    destination_root = tmp_path / 'destination'
    shutil.copytree(source.root, destination_root)

    copied = ArtifactStore(destination_root)
    current = copied.current_manifest('A')
    assert current.revision == persisted.revision
    assert current.sha256 == persisted.sha256
    assert Path(current.path).resolve() == (destination_root / 'nested' / 'a.txt').resolve()
    assert _on_disk_manifest(copied, 'A', persisted.revision)['path'] == 'nested/a.txt'


@pytest.mark.parametrize('locator', ['../escape.txt', './a.txt', 'C:/outside.txt', r'C:\outside.txt', '/outside.txt'])
def test_portable_manifest_rejects_unsafe_locator(tmp_path: Path, locator: str):
    import json

    store = ArtifactStore(tmp_path / 'artifacts')
    persisted = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='one', job_id='J')
    path = store.manifest_path('A', persisted.revision)
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['path'] = locator
    path.write_text(json.dumps(raw, indent=2), encoding='utf-8')

    with pytest.raises(ArtifactCurrentnessError):
        store.current_manifest('A')


def test_persist_rejects_symlink_target_redirection_before_write(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    real = store.root / 'real.txt'
    real.write_text('original', encoding='utf-8')
    alias = store.root / 'alias.txt'
    try:
        alias.symlink_to(real)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'file symlink unavailable: {exc}')

    with pytest.raises(PermissionError, match='reparse/symlink'):
        store.persist_exact_text(artifact_id='A', relative_path='alias.txt', text='mutated', job_id='J')
    assert real.read_text(encoding='utf-8') == 'original'


def test_portable_manifest_rejects_symlink_payload_redirection(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    persisted = store.persist_exact_text(artifact_id='A', relative_path='a.txt', text='one', job_id='J')
    payload = Path(persisted.path)
    outside = store.root / 'outside.txt'
    outside.write_text('one', encoding='utf-8')
    payload.unlink()
    try:
        payload.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f'file symlink unavailable: {exc}')

    with pytest.raises(ArtifactCurrentnessError, match='reparse/symlink'):
        store.current_manifest('A')


def test_legacy_absolute_manifest_remains_valid_only_in_original_root(tmp_path: Path):
    import shutil

    source = ArtifactStore(tmp_path / 'source')
    persisted = _make_legacy_absolute_manifest(source, 'A', 'a.txt', 'legacy')
    assert Path(source.current_manifest('A').path).read_text(encoding='utf-8') == 'legacy'

    destination_root = tmp_path / 'destination'
    shutil.copytree(source.root, destination_root)
    copied = ArtifactStore(destination_root)
    with pytest.raises(ArtifactCurrentnessError, match='outside the ArtifactStore root'):
        copied.current_manifest('A')

    assert Path(persisted.path).resolve().is_file()


def test_explicit_legacy_relocation_rewrites_verified_manifests_and_is_replay_safe(tmp_path: Path):
    import shutil

    source = ArtifactStore(tmp_path / 'source')
    a = _make_legacy_absolute_manifest(source, 'A', 'a.txt', 'one')
    b = _make_legacy_absolute_manifest(source, 'B', 'nested/b.txt', 'two')
    destination_root = tmp_path / 'destination'
    shutil.copytree(source.root, destination_root)
    copied = ArtifactStore(destination_root)

    receipt = copied.relocate_legacy_absolute_manifests(source_root=source.root)
    assert receipt['result'] == 'PASS'
    assert receipt['migrated_manifest_count'] == 2
    assert {(row['artifact_id'], row['revision'], row['sha256']) for row in receipt['manifests']} == {
        ('A', a.revision, a.sha256),
        ('B', b.revision, b.sha256),
    }
    assert _on_disk_manifest(copied, 'A', a.revision)['path'] == 'a.txt'
    assert _on_disk_manifest(copied, 'B', b.revision)['path'] == 'nested/b.txt'
    assert Path(copied.current_manifest('A').path).resolve() == (destination_root / 'a.txt').resolve()
    assert Path(copied.current_manifest('B').path).resolve() == (destination_root / 'nested' / 'b.txt').resolve()

    replay = copied.relocate_legacy_absolute_manifests(source_root=source.root)
    assert replay['result'] == 'NO_OP'
    assert replay['migrated_manifest_count'] == 0


def test_legacy_relocation_wrong_source_root_blocks_before_mutation(tmp_path: Path):
    import shutil

    source = ArtifactStore(tmp_path / 'source')
    persisted = _make_legacy_absolute_manifest(source, 'A', 'a.txt', 'one')
    destination_root = tmp_path / 'destination'
    shutil.copytree(source.root, destination_root)
    copied = ArtifactStore(destination_root)
    before = copied.manifest_path('A', persisted.revision).read_bytes()
    wrong = tmp_path / 'wrong'
    wrong.mkdir()

    with pytest.raises(ArtifactCurrentnessError, match='outside the declared source root'):
        copied.relocate_legacy_absolute_manifests(source_root=wrong)

    assert copied.manifest_path('A', persisted.revision).read_bytes() == before


def test_legacy_relocation_destination_sha_mismatch_blocks_before_mutation(tmp_path: Path):
    import shutil

    source = ArtifactStore(tmp_path / 'source')
    persisted = _make_legacy_absolute_manifest(source, 'A', 'a.txt', 'one')
    destination_root = tmp_path / 'destination'
    shutil.copytree(source.root, destination_root)
    copied = ArtifactStore(destination_root)
    before = copied.manifest_path('A', persisted.revision).read_bytes()
    (destination_root / 'a.txt').write_text('tampered', encoding='utf-8')

    with pytest.raises(ArtifactCurrentnessError, match='destination payload SHA256 mismatch'):
        copied.relocate_legacy_absolute_manifests(source_root=source.root)

    assert copied.manifest_path('A', persisted.revision).read_bytes() == before


def test_legacy_relocation_commit_failure_restores_all_manifests(tmp_path: Path, monkeypatch):
    import os
    import shutil
    import universal_runtime.core.artifact_store as artifact_store_module

    source = ArtifactStore(tmp_path / 'source')
    a = _make_legacy_absolute_manifest(source, 'A', 'a.txt', 'one')
    b = _make_legacy_absolute_manifest(source, 'B', 'b.txt', 'two')
    destination_root = tmp_path / 'destination'
    shutil.copytree(source.root, destination_root)
    copied = ArtifactStore(destination_root)
    paths = [copied.manifest_path('A', a.revision), copied.manifest_path('B', b.revision)]
    before = {path: path.read_bytes() for path in paths}

    real_replace = os.replace
    calls = {'count': 0}

    def fail_second_replace(src, dst):
        calls['count'] += 1
        if calls['count'] == 2:
            raise OSError('injected relocation commit failure')
        return real_replace(src, dst)

    monkeypatch.setattr(artifact_store_module.os, 'replace', fail_second_replace)

    with pytest.raises(ArtifactCurrentnessError, match='rolled back'):
        copied.relocate_legacy_absolute_manifests(source_root=source.root)

    assert {path: path.read_bytes() for path in paths} == before


def test_r009_contract_remains_independent_of_ordinary_portable_locator(tmp_path: Path):
    store = ArtifactStore(tmp_path / 'artifacts')
    identity = store.mint_r009_opaque_artifact_identity()
    binding, prepared = store.prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
        artifact_identity_sha256=identity,
        artifact_bytes=b'opaque',
        job_id='R009',
    )
    manifest, data = store.load_exact_r009_opaque_artifact_r001_v1(
        artifact_identity_sha256=binding.artifact_identity_sha256,
        artifact_revision=binding.artifact_revision,
        artifact_sha256=binding.artifact_sha256,
    )
    assert data == b'opaque'
    assert prepared.path == manifest.path
    assert Path(manifest.path).is_absolute()

