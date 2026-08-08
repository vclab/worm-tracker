# Building for Distribution

Both packaged builds are **self-contained**: they bundle Python, FFmpeg, and the YOLO weights, so the target machine needs no Python, Node, or FFmpeg. The YOLO model has been bundled since v1.4.1, so **both pipelines work out of the box** in the packaged app; a user can still point `model_path` at a different `.pt` file in Settings (⚙).

## macOS: building the DMG

Produce a `ParaTracker.app` that runs on machines with no dev tools installed:

```bash
make dist        # full clean rebuild; ad-hoc signs the .app
```

Launch it locally with:

```bash
open dist/ParaTracker.app       # normal launch
dist/ParaTracker/ParaTracker    # folder-mode binary; shows server logs in the terminal
```

Package the `.app` into a DMG for distribution (this is what we upload to GitHub Releases):

```bash
make release     # = make dist + make dmg
```

This produces `dist/ParaTracker-<version>-arm64.dmg`. Use `make dmg` on its own to repackage an existing `.app` without rebuilding.

**Notes:**
- **Apple Silicon only (arm64).** Intel Macs are not supported.
- **Ad-hoc signed, not notarized** (this is free research software). Gatekeeper shows a warning on first launch; the bundled *READ ME FIRST.txt* walks users through the one-time right-click → **Open** step to bypass it.
- The version comes from `CFBundleShortVersionString` in `worm_tracker.spec`.

## Windows: building the .exe and installer

First complete the setup steps in [Installation & Development](install.md) (venv created, weights downloaded). Optionally install [Inno Setup](https://jrsoftware.org/isinfo.php) so the build can also produce a one-click installer:

```powershell
winget install JRSoftware.InnoSetup   # optional: enables the installer step
```

Then build:

```powershell
.\build_windows.ps1
```

This builds the frontend and packages the app with PyInstaller into `dist\ParaTracker\` (an **onedir** build: a folder containing `ParaTracker.exe` plus an `_internal\` directory). If Inno Setup is installed, it then wraps that folder into a single installer:

```
dist\ParaTracker-<version>-Setup.exe
```

If Inno Setup is **not** found, the installer step is skipped with a warning (the onedir folder is still built). Pass `-SkipInstaller` to skip it deliberately.

Launch the freshly built app locally by double-clicking `dist\ParaTracker\ParaTracker.exe`. It starts the server in the background and opens your browser automatically, with **no console window**.

**Distribution, two options:**
- **Installer (recommended):** ship `ParaTracker-<version>-Setup.exe`. It installs into `Program Files`, adds a Start Menu shortcut (and an optional desktop icon), and registers an uninstaller in **Programs & Features**. Re-running a newer installer upgrades in place; user data (job history, settings) is left untouched.
- **Portable zip:** zip the whole `dist\ParaTracker\` folder (not just the `.exe`; it needs `_internal\`). The recipient extracts and double-clicks `ParaTracker.exe`; nothing is installed or registered.

**Notes:**
- **Not code-signed.** Windows SmartScreen shows "Windows protected your PC" on first launch of either the installer or the exe → click **More info → Run anyway** (once).
- The installer runs elevated (Program Files needs admin); accept the UAC prompt.
- The version comes from `CFBundleShortVersionString` in `worm_tracker.spec` (the single source of truth for both platforms).
- Uses a dedicated spec, `worm_tracker_windows.spec` (kept in sync with the macOS `worm_tracker.spec`), and the installer script `installer\paratracker.iss`.

## Running a build someone sent you

**Windows installer (`ParaTracker-<version>-Setup.exe`):** double-click it, click through the SmartScreen prompt (**More info → Run anyway**), accept the UAC prompt, and follow the wizard. Launch afterwards from the Start Menu. Uninstall later from **Settings → Apps** (or Programs & Features).

**Portable zip (Windows or macOS):**

1. Extract the zip anywhere on your computer.
2. Open the extracted `ParaTracker` folder.
3. Double-click **`ParaTracker.exe`** (Windows) or the `.app` (macOS).

The app starts a local server in the background and opens your browser automatically; no installation. On Windows, click through the SmartScreen prompt (**More info → Run anyway**); on macOS, right-click → **Open** the first time.
