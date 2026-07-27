; Let Me Work — Inno Setup script (unsigned pre-release)
; Prerequisites:
;   1. pyinstaller packaging/letmework.spec  → dist\LetMeWork.exe
;   2. Inno Setup 6 → Compile this script
; OpenCode + Node.js installed via official CLI/winget/MSI during post-install (NOT bundled).
; Signing is optional later — see SIGNING.md. SmartScreen warnings on unsigned builds are expected.

#define MyAppName "Let Me Work"
#define MyAppVersion "0.1.0-beta.1"
#define MyAppPublisher "Mark Janzen Bandola"
#define MyAppURL "https://github.com/MarkJanzenB"
#define MyAppExeName "LetMeWork.exe"

[Setup]
AppId={{A7C3E91B-4D2F-4E8A-9B1C-6F0E2A8D5B31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={localappdata}\LetMeWork
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=LetMeWork-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user install — fewer UAC prompts / less AV suspicion than admin
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
InfoBeforeFile=INFO_BEFORE.txt
SetupLogging=yes
; Version resources help Windows / SmartScreen identify the publisher
VersionInfoVersion=0.1.0.1
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} — local AI job finder
VersionInfoProductName={#MyAppName}
VersionInfoCopyright=Copyright (C) 2026 {#MyAppPublisher}
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\LetMeWork.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "INFO_BEFORE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "install_opencode.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Official Node.js (if needed) + OpenCode — not bundled binaries
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_opencode.ps1"""; \
  StatusMsg: "Installing dependencies (Node.js + OpenCode)…"; \
  Flags: waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
