# Troubleshooting

| Problem | Solution |
|---|---|
| `command not found` (pip, python, node) | Ensure Python/Node are installed and on `PATH`. Restart the terminal. |
| `pip install` fails on `numpy` | You're likely on Python 3.13+. `numpy<2` has no wheels there; install and use **Python 3.11**. |
| `running scripts is disabled on this system` (Windows) | PowerShell blocks local scripts by default. Run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, or invoke via `powershell -ExecutionPolicy Bypass -File .\dev.ps1 <target>`. |
| Video won't play in browser | FFmpeg is bundled (`imageio-ffmpeg`); if H.264 transcoding failed, the app falls back to a raw `.mp4` some browsers can't play. Check the backend logs for an FFmpeg error and re-run the job; the data files are unaffected. |
| CORS / network errors | Make sure the backend is running at `http://127.0.0.1:8000`. |
| Port already in use | `npm run dev -- --port 5174`. |
| "app is damaged" / "cannot verify developer" on macOS | Right-click the app → **Open** → **Open**. First launch only. See the bundled *READ ME FIRST.txt*. |
| Windows SmartScreen: "Windows protected your PC" | Click **More info → Run anyway**. First launch only (the app isn't code-signed). |
| Packaged app launches but no browser tab appears | Ensure a default browser is set. The active port is written to `~/Documents/ParaTracker/paratracker.port`; open `http://127.0.0.1:<that-port>` manually. |
| Double-clicked the app and nothing happens | It's already running; it brought the existing browser tab forward. Check your open tabs. |
| Server keeps running after closing the browser | Give it ~20 seconds (heartbeat watchdog). Force-quit from Activity Monitor / Task Manager if needed. |

---

# Uninstalling

A full uninstall removes three things: the app, its **config** directory, and its **outputs** directory (job history, results, settings). Removing only the app leaves your data on disk.

**macOS:**

```bash
rm -rf /Applications/ParaTracker.app                # the app
rm -rf ~/Library/Application\ Support/ParaTracker   # config (settings, model path)
rm -rf ~/Documents/ParaTracker                      # outputs: jobs.db, videos, keypoints, CSVs, uploads
```

**Windows:** first remove the app itself:

- **Installed via `ParaTracker-<version>-Setup.exe`:** uninstall from **Settings → Apps → Installed apps → ParaTracker → Uninstall** (or Control Panel → Programs & Features). This removes the Program Files install, Start Menu shortcut, and registry entry.
- **Portable zip:** just delete the extracted folder (`Remove-Item -Recurse -Force "path\to\ParaTracker"`).

Either way, the uninstaller/deletion leaves your **data** behind; remove it separately:

```powershell
Remove-Item -Recurse -Force "$env:APPDATA\ParaTracker"                 # config
Remove-Item -Recurse -Force "$env:USERPROFILE\Documents\ParaTracker"   # outputs
```

**Linux:**

```bash
rm -rf ~/.config/ParaTracker                        # config
rm -rf ~/Documents/ParaTracker                      # outputs
```

- **Moved your outputs directory** via Settings (⚙) to a custom location? Delete that location instead of `~/Documents/ParaTracker`. The path is stored under `outputs_dir` in `config.json` in the config directory above.
- **Upgrading from v1.3.0 or earlier?** The app was previously named *WormTracker*. On first launch of v1.4.0+, the old `WormTracker` config and outputs directories are automatically renamed to `ParaTracker` in place; your jobs and settings carry over untouched.
- **Built from source?** Also run `make clean-python-env` / `.\dev.ps1 clean-python-env` (venv), `make clean-weights` / `.\dev.ps1 clean-weights` (model), and delete the project folder.
