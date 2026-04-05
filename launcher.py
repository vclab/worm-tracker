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


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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

    port = _find_free_port()

    browser_thread = threading.Thread(
        target=_open_browser, args=(port,), daemon=True
    )
    browser_thread.start()

    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
