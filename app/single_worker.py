"""Fail closed if two service processes try to operate on one SQLite database.

Workflow locks and the audit-chain writer are thread-local. Until they have a
transactional, cross-process replacement, a second worker must not serve the
same database. The OS releases the lock if the process exits unexpectedly.
"""

from __future__ import annotations

import fcntl
import os
import threading
from pathlib import Path

_guard = threading.Lock()
_held: dict[str, tuple[int, int]] = {}  # canonical database path -> (fd, local app reference count)
_pid = os.getpid()


def _clear_after_fork() -> None:
    global _pid
    if _pid == os.getpid():
        return
    for fd, _ in _held.values():
        os.close(fd)
    _held.clear()
    _pid = os.getpid()


def _after_fork() -> None:
    global _guard
    _guard = threading.Lock()
    _clear_after_fork()


os.register_at_fork(after_in_child=_after_fork)


class SingleWorkerGuard:
    def __init__(self, db_path: str) -> None:
        self.path = str(Path(db_path).resolve())
        self.pid = os.getpid()
        self.active = False
        self._acquire()

    def _acquire(self) -> None:
        with _guard:
            _clear_after_fork()
            if self.path in _held:
                fd, count = _held[self.path]
                _held[self.path] = fd, count + 1
            else:
                lock_path = self.path + ".worker.lock"
                Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(fd)
                    raise RuntimeError("Another TradeOS worker is using this SQLite database. "
                                       "Run one worker per database until cross-process workflow locks are available.") from None
                _held[self.path] = fd, 1
            self.pid = os.getpid()
            self.active = True

    def ensure_current_process(self) -> None:
        """A preloaded ASGI app may be inherited by a forked worker."""
        if self.pid != os.getpid():
            self._acquire()

    def release(self) -> None:
        with _guard:
            if not self.active or self.pid != os.getpid():
                return
            fd, count = _held[self.path]
            if count == 1:
                del _held[self.path]
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
            else:
                _held[self.path] = fd, count - 1
            self.active = False
