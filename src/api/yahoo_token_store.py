"""Opt-in private token file for processes sharing one POSIX filesystem.

Provision the directory and initial file separately. This module never seeds a
store from environment variables. flock is not a distributed secret manager.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # Legacy environment-only mode also supports non-POSIX hosts.
    fcntl = None


class TokenStoreError(RuntimeError):
    """A deliberately credential-free persistence error."""


@dataclass(frozen=True, repr=False)
class TokenPair:
    access_token: str
    refresh_token: str


def _valid_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and not any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)
    )


def configured_store() -> YahooTokenStore | None:
    value = os.getenv("YAHOO_TOKEN_STORE")
    return YahooTokenStore(value) if value else None


class YahooTokenStore:
    def __init__(self, path: str | Path):
        if fcntl is None or any(
            not hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "getuid")
        ):
            raise TokenStoreError("Yahoo token store requires a supported POSIX filesystem")
        self.path = Path(path)
        if not self.path.is_absolute():
            raise TokenStoreError("Yahoo token store must use an absolute path")
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    def _validate_directory(self) -> None:
        try:
            parent = self.path.parent
            for directory in [parent, *parent.parents]:
                info = directory.lstat()
                if not stat.S_ISDIR(info.st_mode):
                    raise TokenStoreError("Yahoo token store path contains an unsafe directory")
                if directory == parent:
                    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                        raise TokenStoreError(
                            "Yahoo token directory must be owned and private (0700)"
                        )
                elif info.st_uid not in (0, os.getuid()) or (
                    info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
                ):
                    raise TokenStoreError("Yahoo token store ancestor is unsafe")
        except (OSError, ValueError):
            raise TokenStoreError("Yahoo token store directory is unavailable") from None

    @staticmethod
    def _validate_file(fd: int) -> None:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise TokenStoreError("Yahoo token files must be owned, regular, private (0600) files")

    def _open_lock(self) -> int:
        self._validate_directory()
        # A missing store is an error, never a request to copy injected secrets.
        self.read()
        try:
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                self._validate_file(fd)
                return fd
            except BaseException:
                os.close(fd)
                raise
        except OSError:
            raise TokenStoreError("Yahoo token lock is unavailable") from None

    @contextmanager
    def locked(self):
        """Immediate read lock; fail safely if another process is rotating tokens."""
        fd = self._open_lock()
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise TokenStoreError("Yahoo token store is busy; retry shortly") from None
            except OSError:
                raise TokenStoreError("Yahoo token lock failed") from None
            yield self
        finally:
            os.close(fd)

    @asynccontextmanager
    async def async_locked(self):
        """Wait without blocking the event loop; retain lock through remote rotation."""
        fd = self._open_lock()
        deadline = time.monotonic() + 30
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TokenStoreError("Yahoo token store lock timed out") from None
                    await asyncio.sleep(0.05)
                except OSError:
                    raise TokenStoreError("Yahoo token lock failed") from None
            yield self
        finally:
            os.close(fd)

    def read(self) -> TokenPair:
        """Read one atomic snapshot. Caller holds the lock for authoritative use."""
        self._validate_directory()
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "r", encoding="utf-8") as handle:
                self._validate_file(handle.fileno())
                payload = handle.read(65537)
            if len(payload) > 65536:
                raise ValueError
            value = json.loads(payload)
            if (
                not isinstance(value, dict)
                or type(value.get("version")) is not int
                or value["version"] != 1
            ):
                raise ValueError
            if any(not _valid_token(value.get(k)) for k in ("access_token", "refresh_token")):
                raise ValueError
            return TokenPair(value["access_token"], value["refresh_token"])
        except (OSError, ValueError, UnicodeError):
            raise TokenStoreError(
                "Yahoo token store is missing, malformed, or inaccessible"
            ) from None

    def write(self, tokens: TokenPair) -> None:
        """Replace atomically under caller's exclusive lock; publish only on success."""
        if not isinstance(tokens, TokenPair) or not all(
            _valid_token(value) for value in (tokens.access_token, tokens.refresh_token)
        ):
            raise TokenStoreError("Yahoo token pair is invalid")
        payload = (
            json.dumps(
                {
                    "version": 1,
                    "access_token": tokens.access_token,
                    "refresh_token": tokens.refresh_token,
                }
            )
            + "\n"
        )
        if len(payload.encode("utf-8")) > 65536:
            raise TokenStoreError("Yahoo token pair exceeds the supported size")
        self.read()  # Revalidate destination before replacing.
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(prefix=".yahoo-", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
            directory_fd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            raise TokenStoreError(
                "Yahoo token persistence failed after rotation; "
                "recovery may require reauthorization"
            ) from None
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass  # Preserve the credential-free primary failure.
