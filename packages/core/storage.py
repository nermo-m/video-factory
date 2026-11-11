"""Storage interface (decision D9): files are accessed only through a storage adapter.

Paths are relative to the storage root and use forward slashes, whatever the host system.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Protocol


class StorageError(Exception):
    """The storage could not do what was asked. The message is safe to show the owner."""


class StorageAdapter(Protocol):
    def write_bytes(self, path: PurePosixPath | str, data: bytes) -> None:
        """Write a file, replacing any earlier one. Readers never see a half-written file."""

    def read_bytes(self, path: PurePosixPath | str) -> bytes:
        """Read a file. Raises StorageError when it does not exist."""

    def exists(self, path: PurePosixPath | str) -> bool:
        """True when a file is stored at this path."""

    def check(self) -> None:
        """Prove the storage is usable right now. Raises StorageError when it is not."""
