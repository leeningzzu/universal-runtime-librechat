from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from .enums import PersistenceClass
from .hashing import sha256_bytes
from .models import ArtifactManifest


_MANIFEST_NAMESPACE_RE = re.compile(r'^[A-Z][A-Z0-9_]*$')
_RESERVED_WINDOWS_DEVICE_NAMES = {
    'CON',
    'PRN',
    'AUX',
    'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}


_R009_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
_R009_OPAQUE_PREFIX = 'RUNTIME_OPAQUE_'
_R009_REVISION = 1
_R009_CONTENT_NAMESPACE = '_r009_opaque_r001'
_R009_PREPARE_LOCK_NAME = '.r009_opaque_r001_prepare.lock'
_PORTABLE_WINDOWS_INVALID_CHARS = set('<>:"\\|?*')
_WINDOWS_ABSOLUTE_LOCATOR_RE = re.compile(r'^[A-Za-z]:[\\/]')


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        info = os.lstat(path)
    except OSError:
        return False
    attrs = getattr(info, 'st_file_attributes', 0)
    flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return bool(attrs & flag)


def _assert_no_reparse_chain(root: Path, target: Path, *, error_cls: type[Exception]) -> None:
    root = Path(os.path.abspath(os.fspath(root)))
    target = Path(os.path.abspath(os.fspath(target)))
    if not _is_relative_to(target, root) and target != root:
        raise error_cls('path escapes exact ArtifactStore root')
    current = root
    if current.exists() and _is_reparse_or_symlink(current):
        raise error_cls(f'reparse/symlink path is forbidden: {current}')
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() and _is_reparse_or_symlink(current):
            raise error_cls(f'reparse/symlink path is forbidden: {current}')


def _windows_reserved_component(component: str) -> bool:
    return component.split('.', 1)[0].upper() in _RESERVED_WINDOWS_DEVICE_NAMES


def _canonical_portable_locator(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactCurrentnessError('portable artifact locator must be a non-empty relative string')
    if (
        value.startswith('/')
        or value.startswith('\\')
        or _WINDOWS_ABSOLUTE_LOCATOR_RE.match(value) is not None
        or '\\' in value
        or ':' in value
    ):
        raise ArtifactCurrentnessError('portable artifact locator must be Runtime-root-relative')
    if any(ord(ch) < 32 or ch == '\x7f' for ch in value):
        raise ArtifactCurrentnessError('portable artifact locator contains a control character')
    parts = value.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise ArtifactCurrentnessError('portable artifact locator contains an unsafe path component')
    for part in parts:
        if any(ch in _PORTABLE_WINDOWS_INVALID_CHARS for ch in part):
            raise ArtifactCurrentnessError('portable artifact locator contains a Windows-invalid path component')
        if part.endswith(' ') or part.endswith('.'):
            raise ArtifactCurrentnessError('portable artifact locator contains a Windows trailing dot/space')
        if _windows_reserved_component(part):
            raise ArtifactCurrentnessError('portable artifact locator aliases a Windows reserved device name')
    return '/'.join(parts)


def _looks_like_absolute_locator(value: str) -> bool:
    return (
        Path(value).is_absolute()
        or value.startswith('\\')
        or _WINDOWS_ABSOLUTE_LOCATOR_RE.match(value) is not None
    )



class R009OpaqueArtifactError(ValueError):
    """Fail-closed error for the inherited R009 opaque R001 ArtifactStore contract."""


@dataclass(frozen=True)
class R009OpaqueArtifactBinding:
    artifact_identity_sha256: str
    artifact_revision: int
    artifact_sha256: str

    def __post_init__(self) -> None:
        if _R009_SHA256_RE.fullmatch(self.artifact_identity_sha256) is None:
            raise R009OpaqueArtifactError('artifact_identity_sha256 must be lowercase 64-hex')
        if self.artifact_revision != 1:
            raise R009OpaqueArtifactError('governed Artifact revision must be exactly 1')
        if _R009_SHA256_RE.fullmatch(self.artifact_sha256) is None:
            raise R009OpaqueArtifactError('artifact_sha256 must be lowercase 64-hex')


def _r009_lexical_absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _r009_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _r009_is_reparse_or_symlink(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        info = os.lstat(path)
    except OSError as exc:
        raise R009OpaqueArtifactError(f'cannot lstat filesystem path: {path}') from exc
    attrs = getattr(info, 'st_file_attributes', 0)
    flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return bool(attrs & flag)


def _r009_assert_no_reparse_chain(root: Path, target: Path) -> None:
    root = _r009_lexical_absolute(root)
    target = _r009_lexical_absolute(target)
    if not _r009_is_relative_to(target, root):
        raise R009OpaqueArtifactError('path escapes exact ArtifactStore root')
    current = root
    if current.exists() and _r009_is_reparse_or_symlink(current):
        raise R009OpaqueArtifactError(f'reparse/symlink path is forbidden: {current}')
    for part in target.relative_to(root).parts:
        current = current / part
        if current.exists() and _r009_is_reparse_or_symlink(current):
            raise R009OpaqueArtifactError(f'reparse/symlink path is forbidden: {current}')


def _r009_flush_parent_directory(path: Path) -> None:
    if os.name == 'nt':
        return
    flags = getattr(os, 'O_DIRECTORY', 0) | os.O_RDONLY
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ArtifactCurrentnessError(ValueError):
    """Raised when a Runtime ArtifactStore revision binding is not current and exact."""


class ArtifactStore:
    def __init__(self, root: Path):
        self._r009_configured_root = _r009_lexical_absolute(root)
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative_path: str) -> Path:
        lexical = self.root / relative_path
        _assert_no_reparse_chain(self.root, lexical, error_cls=PermissionError)
        candidate = lexical.resolve()
        if self.root not in candidate.parents and candidate != self.root:
            raise PermissionError(f'Path escapes artifact root: {relative_path}')
        return candidate

    def _manifest_dir(self, artifact_id: str) -> Path:
        if not isinstance(artifact_id, str) or not artifact_id:
            raise PermissionError('artifact_id must be a non-empty string')
        if _MANIFEST_NAMESPACE_RE.fullmatch(artifact_id) is None:
            raise PermissionError('artifact_id escapes or aliases the Runtime manifest root')
        if artifact_id.upper() in _RESERVED_WINDOWS_DEVICE_NAMES:
            raise PermissionError('artifact_id aliases a reserved Windows device namespace')

        configured_manifest_root = self.root / '_manifests'
        manifest_root = configured_manifest_root.resolve(strict=False)
        if manifest_root != configured_manifest_root:
            raise PermissionError('Runtime manifest root is redirected')

        lexical_candidate = manifest_root / artifact_id
        resolved_candidate = lexical_candidate.resolve(strict=False)
        if (
            lexical_candidate.parent != manifest_root
            or resolved_candidate != lexical_candidate
            or resolved_candidate.parent != manifest_root
        ):
            raise PermissionError('artifact_id manifest namespace is redirected or escapes the Runtime manifest root')
        return lexical_candidate

    def _assert_source_content_not_retired(self, artifact_id: str, *, exact_opaque: bool = False) -> None:
        manifest_dir = self._manifest_dir(artifact_id)
        for name in (
            'PERMANENT_CONTENT_ERASURE_INTENT_R001.json',
            'PERMANENT_CONTENT_ERASURE_COMPLETE_R001.json',
        ):
            marker = manifest_dir / name
            if marker.exists() or marker.is_symlink():
                reason = 'Runtime Artifact content has a durable retirement intent; access or recreation is forbidden'
                if exact_opaque:
                    raise R009OpaqueArtifactError(reason)
                raise ArtifactCurrentnessError(reason)

    def next_revision(self, artifact_id: str) -> int:
        manifest_dir = self._manifest_dir(artifact_id)
        if not manifest_dir.exists():
            return 1
        revisions = []
        for path in manifest_dir.glob('R*.json'):
            try:
                revisions.append(int(path.stem[1:]))
            except ValueError:
                continue
        return max(revisions, default=0) + 1

    def persist_exact_text(
        self,
        *,
        artifact_id: str,
        relative_path: str,
        text: str,
        job_id: str,
        persistence_class: PersistenceClass = PersistenceClass.WORKING,
        input_fingerprint: str | None = None,
        metadata: dict | None = None,
    ) -> ArtifactManifest:
        manifest_dir = self._manifest_dir(artifact_id)
        self._assert_source_content_not_retired(artifact_id)
        revision = self.next_revision(artifact_id)
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode('utf-8')
        target.write_bytes(data)
        if target.read_bytes() != data:
            raise IOError('Byte-preservation check failed after write.')
        digest = sha256_bytes(data)
        _assert_no_reparse_chain(self.root, target, error_cls=ArtifactCurrentnessError)
        locator = _canonical_portable_locator(target.relative_to(self.root).as_posix())
        stored_manifest = ArtifactManifest.now(
            artifact_id=artifact_id,
            revision=revision,
            sha256=digest,
            path=locator,
            persistence_class=persistence_class,
            job_id=job_id,
            input_fingerprint=input_fingerprint,
            metadata=metadata or {},
        )
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f'R{revision:03d}.json'
        manifest_path.write_text(stored_manifest.model_dump_json(indent=2), encoding='utf-8')
        return stored_manifest.model_copy(update={'path': str(target)})


    @staticmethod
    def mint_r009_opaque_artifact_identity() -> str:
        return sha256_bytes(secrets.token_bytes(32))

    def _r009_raw_id(self, artifact_identity_sha256: str) -> str:
        if _R009_SHA256_RE.fullmatch(artifact_identity_sha256) is None:
            raise R009OpaqueArtifactError('artifact_identity_sha256 must be lowercase 64-hex')
        raw_id = _R009_OPAQUE_PREFIX + artifact_identity_sha256.upper()
        self._manifest_dir(raw_id)
        return raw_id

    def _r009_exact_paths(self, artifact_identity_sha256: str) -> tuple[str, Path, Path]:
        raw_id = self._r009_raw_id(artifact_identity_sha256)
        root = _r009_lexical_absolute(self.root)
        content = root / _R009_CONTENT_NAMESPACE / raw_id / 'CONTENT.bin'
        manifest = root / '_manifests' / raw_id / 'R001.json'
        if not _r009_is_relative_to(content, root) or not _r009_is_relative_to(manifest, root):
            raise R009OpaqueArtifactError('derived path escapes exact ArtifactStore root')
        return raw_id, content, manifest

    def _r009_validate_root_and_paths(self, content: Path, manifest: Path) -> None:
        root = _r009_lexical_absolute(self.root)
        configured = _r009_lexical_absolute(self._r009_configured_root)
        if configured != root:
            raise R009OpaqueArtifactError('configured ArtifactStore root is redirected')
        if configured.exists() and _r009_is_reparse_or_symlink(configured):
            raise R009OpaqueArtifactError('configured ArtifactStore root is a reparse/symlink path')
        if not root.is_dir():
            raise R009OpaqueArtifactError('ArtifactStore root is missing')
        _r009_assert_no_reparse_chain(root, root)
        manifest_root = root / '_manifests'
        if manifest_root.exists():
            _r009_assert_no_reparse_chain(root, manifest_root)
        for target in (content, manifest):
            target_abs = _r009_lexical_absolute(target)
            if not _r009_is_relative_to(target_abs, root):
                raise R009OpaqueArtifactError('R009 target escapes ArtifactStore root')
            _r009_assert_no_reparse_chain(root, target if target.exists() else target.parent)

    def _r009_prepare_lock_path(self) -> Path:
        root = _r009_lexical_absolute(self.root)
        manifest_root = root / '_manifests'
        if manifest_root.exists():
            _r009_assert_no_reparse_chain(root, manifest_root)
        manifest_root.mkdir(parents=True, exist_ok=True)
        _r009_assert_no_reparse_chain(root, manifest_root)
        path = manifest_root / _R009_PREPARE_LOCK_NAME
        if path.exists() and _r009_is_reparse_or_symlink(path):
            raise R009OpaqueArtifactError('ArtifactStore preparation lock path is redirected')
        return path

    @contextmanager
    def _r009_prepare_lock(self) -> Iterator[None]:
        path = self._r009_prepare_lock_path()
        with open(path, 'a+b') as fh:
            if fh.seek(0, os.SEEK_END) == 0:
                fh.write(b'\0')
                fh.flush()
                os.fsync(fh.fileno())
            fh.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _r009_write_exclusive(final: Path, data: bytes, *, label: str) -> None:
        fd = os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=True) as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        check = final.read_bytes()
        if check != data or sha256_bytes(check) != sha256_bytes(data):
            raise R009OpaqueArtifactError(f'{label} read-back verification failed')
        _r009_flush_parent_directory(final.parent)

    def _load_exact_r009_manifest(
        self,
        *,
        raw_id: str,
        content_path: Path,
        manifest_path: Path,
        expected_sha256: str,
        expected_job_id: str | None,
        expected_persistence: PersistenceClass | None,
    ) -> ArtifactManifest:
        self._r009_validate_root_and_paths(content_path, manifest_path)
        self._assert_source_content_not_retired(raw_id, exact_opaque=True)
        if not content_path.is_file() or not manifest_path.is_file():
            raise R009OpaqueArtifactError('R009 exact opaque Artifact R001 is missing or partial')
        if _r009_is_reparse_or_symlink(content_path) or _r009_is_reparse_or_symlink(manifest_path):
            raise R009OpaqueArtifactError('R009 exact opaque Artifact path is redirected')
        try:
            manifest = ArtifactManifest.model_validate_json(manifest_path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError) as exc:
            raise R009OpaqueArtifactError('R009 exact opaque Artifact manifest is invalid') from exc

        exact_content = _r009_lexical_absolute(content_path)
        manifest_content = _r009_lexical_absolute(manifest.path)
        if (
            manifest.artifact_id != raw_id
            or manifest.revision != 1
            or manifest.sha256 != expected_sha256
            or manifest_content != exact_content
        ):
            raise R009OpaqueArtifactError('R009 exact opaque Artifact manifest binding mismatch')
        if expected_job_id is not None and manifest.job_id != expected_job_id:
            raise R009OpaqueArtifactError('R009 exact opaque Artifact job binding mismatch')
        if expected_persistence is not None and manifest.persistence_class != expected_persistence:
            raise R009OpaqueArtifactError('R009 exact opaque Artifact persistence binding mismatch')
        data = content_path.read_bytes()
        if sha256_bytes(data) != expected_sha256:
            raise R009OpaqueArtifactError('R009 exact opaque Artifact content SHA mismatch')
        return manifest

    def prepare_or_replay_exact_r009_opaque_artifact_r001_v1(
        self,
        *,
        artifact_identity_sha256: str,
        artifact_bytes: bytes,
        job_id: str,
        persistence_class: PersistenceClass = PersistenceClass.WORKING,
        expected_artifact_sha256: str | None = None,
    ) -> tuple[R009OpaqueArtifactBinding, ArtifactManifest]:
        if _R009_SHA256_RE.fullmatch(artifact_identity_sha256) is None:
            raise R009OpaqueArtifactError('artifact_identity_sha256 must be lowercase 64-hex')
        if not isinstance(artifact_bytes, bytes):
            raise R009OpaqueArtifactError('artifact_bytes must be exact bytes')
        if not isinstance(job_id, str) or not job_id:
            raise R009OpaqueArtifactError('job_id must be non-empty')
        try:
            persistence_class = PersistenceClass(persistence_class)
        except (TypeError, ValueError) as exc:
            raise R009OpaqueArtifactError('persistence_class is not allowlisted') from exc

        digest = sha256_bytes(artifact_bytes)
        if expected_artifact_sha256 is not None and expected_artifact_sha256 != digest:
            raise R009OpaqueArtifactError('expected artifact SHA mismatch')

        raw_id, content_path, manifest_path = self._r009_exact_paths(artifact_identity_sha256)
        binding = R009OpaqueArtifactBinding(artifact_identity_sha256, 1, digest)

        with self._r009_prepare_lock():
            self._r009_validate_root_and_paths(content_path, manifest_path)
            self._assert_source_content_not_retired(raw_id, exact_opaque=True)
            ce = content_path.exists()
            me = manifest_path.exists()
            if ce != me:
                raise R009OpaqueArtifactError('R009_OPAQUE_R001_PREPARATION_PARTIAL_OR_CONFLICT_FAIL_CLOSED')
            if ce:
                manifest = self._load_exact_r009_manifest(
                    raw_id=raw_id,
                    content_path=content_path,
                    manifest_path=manifest_path,
                    expected_sha256=digest,
                    expected_job_id=job_id,
                    expected_persistence=persistence_class,
                )
                if content_path.read_bytes() != artifact_bytes:
                    raise R009OpaqueArtifactError('R009_OPAQUE_R001_PREPARATION_PARTIAL_OR_CONFLICT_FAIL_CLOSED')
                return binding, manifest

            content_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self._r009_validate_root_and_paths(content_path, manifest_path)

            self._r009_write_exclusive(content_path, artifact_bytes, label='opaque content')

            manifest = ArtifactManifest.now(
                artifact_id=raw_id,
                revision=1,
                sha256=digest,
                path=str(_r009_lexical_absolute(content_path)),
                persistence_class=persistence_class,
                job_id=job_id,
                input_fingerprint=None,
                metadata={},
            )
            manifest_bytes = manifest.model_dump_json(indent=2).encode('utf-8')
            self._r009_write_exclusive(manifest_path, manifest_bytes, label='opaque manifest')

            return binding, self._load_exact_r009_manifest(
                raw_id=raw_id,
                content_path=content_path,
                manifest_path=manifest_path,
                expected_sha256=digest,
                expected_job_id=job_id,
                expected_persistence=persistence_class,
            )


    def create_once_exact_r009_opaque_artifact_r001_v1(
        self,
        *,
        artifact_identity_sha256: str,
        artifact_bytes: bytes,
        job_id: str,
        persistence_class: PersistenceClass = PersistenceClass.WORKING,
        expected_artifact_sha256: str | None = None,
    ) -> tuple[R009OpaqueArtifactBinding, ArtifactManifest, str, bytes]:
        """Create one exact opaque Artifact once, or return exact existing bytes.

        Identity is the create-once arbiter. On first creation, proposed exact bytes are
        committed. If the identity already exists, the stored manifest/content is
        integrity-validated against its own stored SHA and returned without overwrite.
        Caller-owned semantic checks decide lawful replay versus conflicting identity reuse.

        This reuses the existing cross-process R009 preparation lock.
        """

        if _R009_SHA256_RE.fullmatch(artifact_identity_sha256) is None:
            raise R009OpaqueArtifactError('artifact_identity_sha256 must be lowercase 64-hex')
        if not isinstance(artifact_bytes, bytes):
            raise R009OpaqueArtifactError('artifact_bytes must be exact bytes')
        if not isinstance(job_id, str) or not job_id:
            raise R009OpaqueArtifactError('job_id must be non-empty')
        try:
            persistence_class = PersistenceClass(persistence_class)
        except (TypeError, ValueError) as exc:
            raise R009OpaqueArtifactError('persistence_class is not allowlisted') from exc

        digest = sha256_bytes(artifact_bytes)
        if expected_artifact_sha256 is not None and expected_artifact_sha256 != digest:
            raise R009OpaqueArtifactError('expected artifact SHA mismatch')

        raw_id, content_path, manifest_path = self._r009_exact_paths(artifact_identity_sha256)
        binding = R009OpaqueArtifactBinding(artifact_identity_sha256, 1, digest)

        with self._r009_prepare_lock():
            self._r009_validate_root_and_paths(content_path, manifest_path)
            content_exists = content_path.exists()
            manifest_exists = manifest_path.exists()
            if content_exists != manifest_exists:
                raise R009OpaqueArtifactError(
                    'R009_OPAQUE_R001_PREPARATION_PARTIAL_OR_CONFLICT_FAIL_CLOSED'
                )

            if content_exists:
                try:
                    manifest_probe = ArtifactManifest.model_validate_json(
                        manifest_path.read_text(encoding='utf-8')
                    )
                except (OSError, UnicodeError, ValueError) as exc:
                    raise R009OpaqueArtifactError(
                        'R009 exact opaque Artifact manifest is invalid'
                    ) from exc
                manifest = self._load_exact_r009_manifest(
                    raw_id=raw_id,
                    content_path=content_path,
                    manifest_path=manifest_path,
                    expected_sha256=manifest_probe.sha256,
                    expected_job_id=job_id,
                    expected_persistence=persistence_class,
                )
                existing_bytes = content_path.read_bytes()
                if sha256_bytes(existing_bytes) != manifest.sha256:
                    raise R009OpaqueArtifactError(
                        'R009 exact opaque Artifact content SHA mismatch'
                    )
                existing_binding = R009OpaqueArtifactBinding(
                    artifact_identity_sha256,
                    1,
                    manifest.sha256,
                )
                return existing_binding, manifest, 'EXISTS', existing_bytes

            content_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            self._r009_validate_root_and_paths(content_path, manifest_path)
            self._r009_write_exclusive(content_path, artifact_bytes, label='opaque content')

            manifest = ArtifactManifest.now(
                artifact_id=raw_id,
                revision=1,
                sha256=digest,
                path=str(_r009_lexical_absolute(content_path)),
                persistence_class=persistence_class,
                job_id=job_id,
                input_fingerprint=None,
                metadata={},
            )
            manifest_bytes = manifest.model_dump_json(indent=2).encode('utf-8')
            self._r009_write_exclusive(manifest_path, manifest_bytes, label='opaque manifest')
            loaded = self._load_exact_r009_manifest(
                raw_id=raw_id,
                content_path=content_path,
                manifest_path=manifest_path,
                expected_sha256=digest,
                expected_job_id=job_id,
                expected_persistence=persistence_class,
            )
            return binding, loaded, 'CREATED', artifact_bytes

    def load_exact_r009_opaque_artifact_r001_v1(
        self,
        *,
        artifact_identity_sha256: str,
        artifact_revision: int,
        artifact_sha256: str,
    ) -> tuple[ArtifactManifest, bytes]:
        binding = R009OpaqueArtifactBinding(
            artifact_identity_sha256,
            artifact_revision,
            artifact_sha256,
        )
        raw_id, content_path, manifest_path = self._r009_exact_paths(binding.artifact_identity_sha256)
        manifest = self._load_exact_r009_manifest(
            raw_id=raw_id,
            content_path=content_path,
            manifest_path=manifest_path,
            expected_sha256=binding.artifact_sha256,
            expected_job_id=None,
            expected_persistence=None,
        )
        data = content_path.read_bytes()
        if sha256_bytes(data) != binding.artifact_sha256:
            raise R009OpaqueArtifactError('R009 exact opaque Artifact content SHA mismatch')
        return manifest, data

    def _current_manifest_dir(self, artifact_id: str) -> Path:
        try:
            return self._manifest_dir(artifact_id)
        except PermissionError as exc:
            raise ArtifactCurrentnessError(str(exc)) from exc

    def current_manifest(self, artifact_id: str) -> ArtifactManifest:
        """Return the latest exact Runtime ArtifactStore revision for one artifact identity.

        This is ArtifactStore revision currentness only. It does not select or imply
        PromotionAuthority state.
        """
        manifest_dir = self._current_manifest_dir(artifact_id)
        self._assert_source_content_not_retired(artifact_id)
        if not manifest_dir.is_dir():
            raise ArtifactCurrentnessError(f'Artifact manifest history not found: {artifact_id}')
        revisions: list[tuple[int, Path]] = []
        for path in manifest_dir.glob('R*.json'):
            suffix = path.stem[1:]
            if suffix.isdigit() and int(suffix) >= 1:
                revisions.append((int(suffix), path))
        if not revisions:
            raise ArtifactCurrentnessError(f'Artifact manifest history is empty: {artifact_id}')
        revision, path = max(revisions, key=lambda item: item[0])
        try:
            manifest = ArtifactManifest.model_validate_json(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ArtifactCurrentnessError(f'Current artifact manifest is invalid: {path}') from exc
        if manifest.artifact_id != artifact_id or manifest.revision != revision:
            raise ArtifactCurrentnessError('Current artifact manifest identity/revision mismatch')
        target = self._resolved_manifest_target(manifest.path)
        if sha256_bytes(target.read_bytes()) != manifest.sha256:
            raise ArtifactCurrentnessError('Current artifact bytes do not match the current manifest SHA256')
        return manifest.model_copy(update={'path': str(target)})


    def _resolved_manifest_target(self, locator: str) -> Path:
        if _looks_like_absolute_locator(locator):
            target = Path(locator).resolve()
            if self.root not in target.parents or not target.is_file():
                raise ArtifactCurrentnessError(
                    'Current artifact path is missing or outside the ArtifactStore root'
                )
            _assert_no_reparse_chain(self.root, target, error_cls=ArtifactCurrentnessError)
            return target

        relative = _canonical_portable_locator(locator)
        lexical = self.root.joinpath(*relative.split('/'))
        _assert_no_reparse_chain(self.root, lexical, error_cls=ArtifactCurrentnessError)
        target = lexical.resolve()
        if self.root not in target.parents or not target.is_file():
            raise ArtifactCurrentnessError(
                'Current artifact path is missing or outside the ArtifactStore root'
            )
        return target

    def relocate_legacy_absolute_manifests(self, *, source_root: Path) -> dict[str, object]:
        """Explicitly rebind a copied legacy ordinary ArtifactStore to this active root.

        Only ordinary manifests whose persisted locator is an absolute path below
        source_root are rewritten. R009 opaque manifests are intentionally excluded.
        All source/destination payload identities are validated before any manifest
        mutation. A commit failure restores the original destination manifest bytes.
        """

        source = source_root.resolve()
        destination = self.root
        if source == destination:
            raise ArtifactCurrentnessError('legacy relocation requires distinct source and destination roots')
        if not source.is_dir() or not destination.is_dir():
            raise ArtifactCurrentnessError('legacy relocation source/destination root is unavailable')
        _assert_no_reparse_chain(source, source, error_cls=ArtifactCurrentnessError)
        _assert_no_reparse_chain(destination, destination, error_cls=ArtifactCurrentnessError)

        manifest_root = destination / '_manifests'
        if not manifest_root.exists():
            return {
                'result': 'NO_OP',
                'migrated_manifest_count': 0,
                'source_root_class': 'LEGACY_ARTIFACT_STORE_ROOT',
                'destination_root_class': 'ACTIVE_ARTIFACT_STORE_ROOT',
                'manifests': [],
            }
        _assert_no_reparse_chain(destination, manifest_root, error_cls=ArtifactCurrentnessError)

        plan: list[dict[str, object]] = []
        for manifest_dir in sorted(manifest_root.iterdir(), key=lambda item: item.name):
            if not manifest_dir.is_dir():
                continue
            artifact_id = manifest_dir.name
            if artifact_id.startswith(_R009_OPAQUE_PREFIX):
                continue
            try:
                expected_dir = self._manifest_dir(artifact_id)
            except PermissionError as exc:
                raise ArtifactCurrentnessError(str(exc)) from exc
            if expected_dir != manifest_dir:
                raise ArtifactCurrentnessError('legacy relocation manifest directory identity mismatch')
            for manifest_path in sorted(manifest_dir.glob('R*.json'), key=lambda item: item.name):
                suffix = manifest_path.stem[1:]
                if not suffix.isdigit() or int(suffix) < 1:
                    continue
                _assert_no_reparse_chain(destination, manifest_path, error_cls=ArtifactCurrentnessError)
                original_bytes = manifest_path.read_bytes()
                try:
                    manifest = ArtifactManifest.model_validate_json(original_bytes)
                except (UnicodeError, ValueError) as exc:
                    raise ArtifactCurrentnessError(
                        f'legacy relocation manifest is invalid: {manifest_path.name}'
                    ) from exc
                revision = int(suffix)
                if manifest.artifact_id != artifact_id or manifest.revision != revision:
                    raise ArtifactCurrentnessError('legacy relocation manifest identity/revision mismatch')
                if not _looks_like_absolute_locator(manifest.path):
                    _canonical_portable_locator(manifest.path)
                    continue

                source_target = Path(manifest.path).resolve()
                if source not in source_target.parents or not source_target.is_file():
                    raise ArtifactCurrentnessError(
                        'legacy relocation source payload is missing or outside the declared source root'
                    )
                _assert_no_reparse_chain(source, source_target, error_cls=ArtifactCurrentnessError)
                if sha256_bytes(source_target.read_bytes()) != manifest.sha256:
                    raise ArtifactCurrentnessError('legacy relocation source payload SHA256 mismatch')

                relative = _canonical_portable_locator(source_target.relative_to(source).as_posix())
                destination_target = destination.joinpath(*relative.split('/'))
                _assert_no_reparse_chain(destination, destination_target, error_cls=ArtifactCurrentnessError)
                resolved_destination = destination_target.resolve()
                if destination not in resolved_destination.parents or not resolved_destination.is_file():
                    raise ArtifactCurrentnessError(
                        'legacy relocation destination payload is missing or outside the active root'
                    )
                if sha256_bytes(resolved_destination.read_bytes()) != manifest.sha256:
                    raise ArtifactCurrentnessError('legacy relocation destination payload SHA256 mismatch')

                rewritten = manifest.model_copy(update={'path': relative})
                rewritten_bytes = rewritten.model_dump_json(indent=2).encode('utf-8')
                plan.append(
                    {
                        'artifact_id': artifact_id,
                        'revision': revision,
                        'sha256': manifest.sha256,
                        'locator': relative,
                        'manifest_path': manifest_path,
                        'original_bytes': original_bytes,
                        'rewritten_bytes': rewritten_bytes,
                    }
                )

        if not plan:
            return {
                'result': 'NO_OP',
                'migrated_manifest_count': 0,
                'source_root_class': 'LEGACY_ARTIFACT_STORE_ROOT',
                'destination_root_class': 'ACTIVE_ARTIFACT_STORE_ROOT',
                'manifests': [],
            }

        staged: list[tuple[Path, Path]] = []
        try:
            for item in plan:
                manifest_path = item['manifest_path']
                assert isinstance(manifest_path, Path)
                temp_path = manifest_path.with_name(
                    f'.{manifest_path.name}.{secrets.token_hex(8)}.relocate.tmp'
                )
                if temp_path.exists():
                    raise ArtifactCurrentnessError('legacy relocation temporary path collision')
                temp_path.write_bytes(item['rewritten_bytes'])
                staged.append((temp_path, manifest_path))

            for temp_path, manifest_path in staged:
                os.replace(temp_path, manifest_path)
        except Exception as exc:
            for item in plan:
                manifest_path = item['manifest_path']
                assert isinstance(manifest_path, Path)
                try:
                    manifest_path.write_bytes(item['original_bytes'])
                except OSError:
                    pass
            for temp_path, _ in staged:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if isinstance(exc, ArtifactCurrentnessError):
                raise
            raise ArtifactCurrentnessError('legacy relocation commit failed and was rolled back') from exc

        receipt_rows = [
            {
                'artifact_id': str(item['artifact_id']),
                'revision': int(item['revision']),
                'sha256': str(item['sha256']),
                'locator': str(item['locator']),
            }
            for item in plan
        ]
        return {
            'result': 'PASS',
            'migrated_manifest_count': len(receipt_rows),
            'source_root_class': 'LEGACY_ARTIFACT_STORE_ROOT',
            'destination_root_class': 'ACTIVE_ARTIFACT_STORE_ROOT',
            'manifests': receipt_rows,
        }

    def assert_current(self, artifact_id: str, revision: int, sha256: str) -> ArtifactManifest:
        """Fail closed unless the exact artifact revision/SHA is the current store revision."""
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ArtifactCurrentnessError('revision must be an integer >= 1')
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(ch not in '0123456789abcdef' for ch in sha256)
        ):
            raise ArtifactCurrentnessError('sha256 must be lowercase 64-hex')
        current = self.current_manifest(artifact_id)
        if current.revision != revision or current.sha256 != sha256:
            raise ArtifactCurrentnessError(
                f'Stale artifact binding: {artifact_id} '
                f'expected=R{revision:03d}/{sha256} '
                f'current=R{current.revision:03d}/{current.sha256}'
            )
        return current

    def manifest_path(self, artifact_id: str, revision: int) -> Path:
        return self._manifest_dir(artifact_id) / f'R{revision:03d}.json'
