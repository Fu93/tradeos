"""A shared SQLite database is deliberately limited to one server process."""

import subprocess
import sys

from app.single_worker import SingleWorkerGuard


def test_same_process_can_construct_two_apps_but_second_process_is_refused(tmp_path):
    database = str(tmp_path / "tradeos.db")
    first = SingleWorkerGuard(database)
    second = SingleWorkerGuard(database)
    try:
        code = ("from app.single_worker import SingleWorkerGuard; "
                f"SingleWorkerGuard({database!r})")
        blocked = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        assert blocked.returncode != 0
        assert "Another TradeOS worker" in blocked.stderr
        first.release()
        still_blocked = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        assert still_blocked.returncode != 0  # second local app still owns the lock
        second.release()
        allowed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
        assert allowed.returncode == 0, allowed.stderr
    finally:
        first.release()
        second.release()
