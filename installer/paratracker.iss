; paratracker.iss - Inno Setup script for ParaTracker (Windows)
;
; Wraps the PyInstaller onedir build (dist\ParaTracker\) into a single
; ParaTracker-<version>-Setup.exe that installs into Program Files, adds a
; Start Menu shortcut (and an optional desktop icon), registers an uninstaller
; and a "Programs & Features" entry.
;
; Build:
;   build_windows.ps1 runs this automatically after PyInstaller (it passes the
;   version via /DMyAppVersion and locates ISCC.exe for you).
;
; Or build the installer by hand, once dist\ParaTracker\ exists:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.4.2 installer\paratracker.iss
;
; The version is defined by CFBundleShortVersionString in worm_tracker.spec
; (the single source of truth). build_windows.ps1 reads it from there and
; passes it in; the fallback below only applies to a bare hand-invocation.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "ParaTracker"
#define MyAppPublisher "VCLab, Ontario Tech University"
#define MyAppURL "https://github.com/vclab/worm-tracker"
#define MyAppExeName "ParaTracker.exe"

; Onedir build produced by worm_tracker_windows.spec. Relative to this script's
; folder (installer\), the PyInstaller output lives at ..\dist\ParaTracker.
#define SourceDir "..\dist\ParaTracker"

; Optional branding icon (not committed yet; add paratracker.ico at the repo
; root to brand the installer + shortcuts). Guarded so the build works without it.
#define IconFile "..\paratracker.ico"

[Setup]
; AppId uniquely identifies this application for upgrades and uninstall.
; NEVER change it once released, or upgrades will install side-by-side instead
; of replacing the previous version.
AppId={{A3F5C2E1-9B7D-4E6A-8C1F-2D4B6E8A0C33}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}

; Program Files requires elevation.
PrivilegesRequired=admin

; The bundled Python / FFmpeg / native wheels are all 64-bit x86. "x64compatible"
; is the modern identifier (Inno Setup 6.3+): it allows install on native x64 and
; on ARM64 Windows (which runs x64 binaries under emulation).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\dist
OutputBaseFilename=ParaTracker-{#MyAppVersion}-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

#if FileExists(AddBackslash(SourcePath) + IconFile)
SetupIconFile={#IconFile}
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Recurse the entire onedir folder (ParaTracker.exe + _internal\...).
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

; NOTE: user data lives outside {app} and is intentionally left untouched on
; uninstall -- the outputs folder (Documents\ParaTracker\, holds jobs.db and all
; results) and the config file (%APPDATA%\ParaTracker\config.json). A full
; uninstall = remove the app here, then delete those two folders by hand.
