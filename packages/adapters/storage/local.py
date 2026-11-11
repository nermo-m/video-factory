"""Local folder storage: the v1 implementation of the storage adapter (decision D9).

In Docker the root is the `app-data` named volume mounted at /data. The design's mock for
storage is this same class pointed at a temporary folder (section 3.3).
"""

from __future__ import annotations

import uuid
from pathlib import Path, PurePosixPath

from packages.core.storage import StorageError


class LocalStorage:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _resolve(self, path: PurePosixPath | str) -> Path:
        """Map a storage path to a file under the root, refusing anything that escapes it."""
        relative = PurePosixPath(str(path).replace("\\", "/"))
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise StorageError(f"'{path}' is not a valid storage path.")
        if any(":" in part for part in relative.parts):
            raise StorageError(f"'{path}' is not a valid storage path.")
        return self._root.joinpath(*relative.parts)

    def write_bytes(self, path: PurePosixPath | str, data: bytes) -> None:
        target = self._resolve(path)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(data)
            # Rename is atomic on one file system: readers see the old file or the new one.
            temporary.replace(target)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise StorageError(f"Could not write '{path}': {error.strerror or error}.") from error

    def read_bytes(self, path: PurePosixPath | str) -> bytes:
        target = self._resolve(path)
        try:
            return target.read_bytes()
        except FileNotFoundError as error:
            raise StorageError(f"'{path}' does not exist.") from error
        except OSError as error:
            raise StorageError(f"Could not read '{path}': {error.strerror or error}.") from error

    def exists(self, path: PurePosixPath | str) -> bool:
        return self._resolve(path).is_file()

    def check(self) -> None:
        """Write and remove a small probe file to prove the folder is writable."""
        if not self._root.is_dir():
            raise StorageError("The data folder does not exist.")
        probe = self._root / f".health-{uuid.uuid4().hex}"
        try:
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as error:
            raise StorageError("The data folder is not writable.") from error
