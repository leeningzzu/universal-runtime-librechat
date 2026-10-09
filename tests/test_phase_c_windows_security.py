from pathlib import Path

import pytest

from universal_runtime.core.file_resolver import FileResolutionError, FileResolver


@pytest.mark.parametrize('name', ['CON', 'NUL', 'PRN', 'AUX', 'COM1', 'LPT1', 'CON.txt'])
def test_windows_device_names_fail_closed(tmp_path: Path, name: str):
    root = tmp_path / 'root'; root.mkdir()
    with pytest.raises(FileResolutionError):
        FileResolver([root]).resolve(root / name)


def test_unc_path_cannot_be_accepted_as_local_resource(tmp_path: Path):
    root = tmp_path / 'root'; root.mkdir()
    with pytest.raises(FileResolutionError):
        FileResolver([root]).resolve(r'\\server\share\prompt.md')


def test_drive_qualified_escape_is_rejected(tmp_path: Path):
    root = tmp_path / 'root'; root.mkdir()
    with pytest.raises(FileResolutionError):
        FileResolver([root]).resolve(r'C:\outside\prompt.md')

