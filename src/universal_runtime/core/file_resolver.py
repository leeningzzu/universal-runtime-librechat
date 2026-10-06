from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable


class FileResolutionError(ValueError):
    """Raised when a reference cannot be safely resolved under an allowlist."""


@dataclass(frozen=True)
class ResolvedFile:
    path: Path
    byte_length: int
    extension: str


class FileResolver:
    """Resolve explicitly named files without ever reading or mutating them."""

    def __init__(self, allowed_roots: Iterable[Path | str], *, allowed_extensions: Iterable[str] = ('.md', '.docx')):
        roots = tuple(Path(root).resolve() for root in allowed_roots)
        if not roots:
            raise ValueError('At least one allowlist root is required.')
        self.allowed_roots = roots
        self.allowed_extensions = frozenset(self._extension(ext) for ext in allowed_extensions)

    @staticmethod
    def _extension(value: str) -> str:
        value = str(value).lower()
        return value if value.startswith('.') else f'.{value}'

    def _under_root(self, path: Path) -> bool:
        return any(path == root or root in path.parents for root in self.allowed_roots)

    @staticmethod
    def _reject_windows_special_path(reference: Path | str) -> None:
        """Reject Windows device and network forms before filesystem resolution."""
        text = str(reference)
        if text.startswith(('\\\\', '//')):
            raise FileResolutionError('UNC/network paths are not allowed.')
        device_names = {'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1, 10)} | {f'LPT{i}' for i in range(1, 10)}
        for component in re.split(r'[\\/]+', text):
            normalized = component.rstrip(' .').split('.', 1)[0].upper()
            if normalized in device_names:
                raise FileResolutionError('Windows device names are not allowed.')

    def resolve(self, reference: Path | str, *, required: bool = True, allowed_extensions: Iterable[str] | None = None) -> ResolvedFile | None:
        self._reject_windows_special_path(reference)
        raw = Path(reference)
        if '..' in raw.parts:
            raise FileResolutionError('Path traversal is not allowed.')
        candidate = raw.resolve(strict=False)
        if not self._under_root(candidate):
            raise FileResolutionError(f'Path is outside the allowlist: {reference}')
        extensions = self.allowed_extensions if allowed_extensions is None else frozenset(self._extension(x) for x in allowed_extensions)
        if candidate.suffix.lower() not in extensions:
            raise FileResolutionError(f'Extension is not authorized: {candidate.suffix}')
        if not candidate.is_file():
            if required:
                raise FileNotFoundError(str(candidate))
            return None
        # resolve() above follows symlinks/junctions; the containment check therefore
        # also protects against links escaping an allowlisted root.
        return ResolvedFile(candidate, candidate.stat().st_size, candidate.suffix.lower())
