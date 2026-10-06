from __future__ import annotations

from pathlib import Path


class PermissionPolicy:
    def __init__(self, *, allowed_read_roots: list[Path], allowed_write_roots: list[Path]):
        self.allowed_read_roots = [p.resolve() for p in allowed_read_roots]
        self.allowed_write_roots = [p.resolve() for p in allowed_write_roots]

    @staticmethod
    def _within(path: Path, roots: list[Path]) -> bool:
        resolved = path.resolve()
        return any(resolved == root or root in resolved.parents for root in roots)

    def require_read(self, path: Path) -> None:
        if not self._within(path, self.allowed_read_roots):
            raise PermissionError(f'Read denied: {path}')

    def require_write(self, path: Path) -> None:
        if not self._within(path, self.allowed_write_roots):
            raise PermissionError(f'Write denied: {path}')
