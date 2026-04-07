# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for WormTracker.

Build with:
    pyinstaller worm_tracker.spec
"""

import sys
import importlib.util
from pathlib import Path

block_cipher = None
PROJECT = Path(SPECPATH)

# Resolve imageio_ffmpeg location from the active Python environment
_spec = importlib.util.find_spec("imageio_ffmpeg")
IMAGEIO_FFMPEG_DIR = str(Path(_spec.origin).parent) if _spec else None

# ---------------------------------------------------------------------------
# Data files to bundle
# ---------------------------------------------------------------------------
datas = [
    # Pre-built React frontend
    (str(PROJECT / "frontend" / "dist"), "frontend_dist"),
    # App Python package (worm_tracker.py, etc.)
    (str(PROJECT / "app"), "app"),
    # imageio_ffmpeg ships its own static ffmpeg binary — include the whole package
    *([(IMAGEIO_FFMPEG_DIR, "imageio_ffmpeg")] if IMAGEIO_FFMPEG_DIR else []),
]

# ---------------------------------------------------------------------------
# Hidden imports that PyInstaller's static analysis misses
# ---------------------------------------------------------------------------
hidden_imports = [
    # App modules — listed explicitly so PyInstaller traces all their imports
    "app.main",
    "app.worm_tracker",
    # uvicorn internals
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # FastAPI / starlette — full middleware stack
    "fastapi",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "fastapi.staticfiles",
    "starlette.middleware",
    "starlette.middleware.cors",
    "starlette.middleware.base",
    "starlette.staticfiles",
    "starlette.routing",
    "starlette.responses",
    "starlette.requests",
    "anyio",
    "anyio._backends._asyncio",
    # Scientific stack
    "skimage",
    "skimage.filters",
    "skimage.morphology",
    "skimage.graph",
    "skimage.util",
    "scipy.optimize",
    "scipy.sparse",
    "scipy.ndimage",
    "imageio_ffmpeg",
    "yaml",
    "pydantic",
    "tqdm",
    # Python standard library items sometimes missed
    "sqlite3",
    "csv",
    "zipfile",
    "platform",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(PROJECT / "launcher.py")],
    pathex=[str(PROJECT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "pandas",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# macOS .app bundle
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WormTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # No terminal window on macOS
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WormTracker",
)

app_bundle = BUNDLE(
    coll,
    name="WormTracker.app",
    icon=None,
    bundle_identifier="ca.vclab.wormtracker",
    info_plist={
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
        "CFBundleShortVersionString": "1.1.0",
        "CFBundleVersion": "1.1.0",
    },
)
