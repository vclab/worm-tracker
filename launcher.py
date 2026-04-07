"""
WormTracker launcher.

Finds a free port, starts the FastAPI server via uvicorn, then opens
the browser. This is the entry point for the packaged .app bundle.
"""

import multiprocessing
import os
import socket
import sys
import threading
import time
import webbrowser

# Env-var key used to ensure the browser is opened exactly once even if
# a spawned subprocess re-enters this module before freeze_support() fires.
_LAUNCHED_KEY = "_WORMTRACKER_LAUNCHED"


def _open_browser(port: int, delay: float = 2.0) -> None:
    time.sleep(delay)
    webbrowser.open(f"http://127.0.0.1:{port}")


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

    # Bind a socket now and keep it open to eliminate the race window between
    # finding a free port and uvicorn binding the same address.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(128)

    if open_browser:
        browser_thread = threading.Thread(
            target=_open_browser, args=(port,), daemon=True
        )
        browser_thread.start()

    import uvicorn
    # Pass fd so uvicorn reuses the already-bound socket (no re-bind race).
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
