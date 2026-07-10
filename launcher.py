"""
ParaTracker launcher.

Finds a free port, starts the FastAPI server via uvicorn, then opens
the browser. This is the entry point for the packaged .app bundle.
"""

import atexit
import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Env-var key used to ensure the browser is opened exactly once even if
# a spawned subprocess re-enters this module before freeze_support() fires.
_LAUNCHED_KEY = "_PARATRACKER_LAUNCHED"

# Timeout for the "is the primary reachable?" probe. Kept short so a
# stale port file does not delay a legitimate cold start.
_PROBE_TIMEOUT_S = 0.5


def _open_browser(port: int, delay: float = 2.0) -> None:
    time.sleep(delay)
    webbrowser.open(f"http://127.0.0.1:{port}")


def _port_file_path() -> Path | None:
    """Return the path to `{outputs_dir}/paratracker.port`, or None if the
    config cannot be loaded (which we treat as "no primary detectable").
    """
    try:
        from app.config import load_config
        return Path(load_config()["outputs_dir"]) / "paratracker.port"
    except Exception:
        return None


def _find_running_primary() -> str | None:
    """If a primary ParaTracker is already running against the same outputs
    folder, return its URL. Otherwise return None and clean up any stale
    port file left behind by a previous crashed instance.
    """
    pf = _port_file_path()
    if pf is None or not pf.exists():
        return None
    try:
        port = int(pf.read_text().strip())
    except (ValueError, OSError):
        return None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(_PROBE_TIMEOUT_S)
        try:
            probe.connect(("127.0.0.1", port))
        except OSError:
            # Nothing listening on that port: the file is stale. Remove
            # so subsequent launches do not keep tripping on it.
            try:
                pf.unlink()
            except OSError:
                pass
            return None
    return f"http://127.0.0.1:{port}"


def _write_port_file(port: int) -> None:
    pf = _port_file_path()
    if pf is None:
        return
    try:
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(str(port))
    except OSError:
        # Not fatal: second-instance detection will fall back to the
        # lifespan flock error and a "cannot connect" browser tab.
        pass


def _delete_port_file() -> None:
    pf = _port_file_path()
    if pf is None:
        return
    try:
        pf.unlink()
    except OSError:
        pass


def main() -> None:
    # On macOS, Python's multiprocessing uses the 'spawn' start method, which
    # re-runs the frozen executable for every spawned subprocess (used internally
    # by numpy, scipy, and others).  Without the guards below, each subprocess
    # re-enters main() and opens an extra browser window.
    #
    # freeze_support() intercepts subprocess re-entry early (standard fix).
    # The env-var guard is a belt-and-suspenders check for any path that
    # freeze_support() doesn't catch.
    open_browser = not os.environ.get(_LAUNCHED_KEY)
    os.environ[_LAUNCHED_KEY] = "1"

    # When running as a PyInstaller bundle the project root is next to the
    # executable; make sure Python can find the app package.
    if getattr(sys, "frozen", False):
        bundle_dir = os.path.dirname(sys.executable)
        if bundle_dir not in sys.path:
            sys.path.insert(0, bundle_dir)

    # Second-instance short-circuit: if a primary ParaTracker is already
    # running against the same outputs folder, open its URL in the browser
    # (which brings the existing window/tab forward on most browsers) and
    # exit before starting a second uvicorn. Without this the second
    # instance would die on flock contention in the lifespan handler, and
    # the user would be left staring at a "cannot connect" browser tab.
    # Only runs for user-initiated launches, not multiprocessing subprocess
    # re-entries.
    if open_browser:
        primary_url = _find_running_primary()
        if primary_url is not None:
            webbrowser.open(primary_url)
            return

    # Bind a socket now and keep it open to eliminate the race window between
    # finding a free port and uvicorn binding the same address.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(128)

    # Advertise our port so a subsequent launch can focus this window.
    # The lifespan handler in app.main will still enforce the flock, so if
    # two launchers race and both write here, whichever loses the flock
    # exits and its stale write is cleaned up on the next launch.
    _write_port_file(port)
    atexit.register(_delete_port_file)

    if open_browser:
        browser_thread = threading.Thread(
            target=_open_browser, args=(port,), daemon=True
        )
        browser_thread.start()

    import uvicorn
    # On POSIX we pass the already-bound socket fd directly so uvicorn inherits
    # it without a re-bind race.  On Windows, fd= is not supported (no fd
    # inheritance for sockets), so we close our socket first and pass host/port
    # instead — there is a small race window but it's acceptable on Windows.
    if sys.platform == "win32":
        sock.close()
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    else:
        uvicorn.run(
            "app.main:app",
            fd=sock.fileno(),
            log_level="warning",
        )


if __name__ == "__main__":
    # freeze_support() must be called before main() — it intercepts spawned
    # subprocesses on macOS (spawn start method) and exits them cleanly
    # instead of letting them re-run the full launcher.
    multiprocessing.freeze_support()
    main()
