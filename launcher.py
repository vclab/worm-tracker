"""
WormTracker launcher.

Finds a free port, starts the FastAPI server via uvicorn, then opens
the browser. This is the entry point for the packaged .app bundle.
"""

import socket
import sys
import threading
import time
import webbrowser


def _open_browser(port: int, delay: float = 2.0) -> None:
    time.sleep(delay)
    webbrowser.open(f"http://127.0.0.1:{port}")


def main() -> None:
    # When running as a PyInstaller bundle the project root is next to the
    # executable; make sure Python can find the app package.
    import os
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
    main()
