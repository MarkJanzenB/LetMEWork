; Let Me Work — Inno Setup script (unsigned pre-release)
; Prerequisites:
;   1. cd frontend && npm ci && npm run build
;   2. pyinstaller packaging/letmework.spec  → dist\LetMeWork.exe
;   3. Inno Setup 6 → Compile this script
; OpenCode + Node.js installed via official CLI during post-install (NOT bundled).
; Signing is optional later — see SIGNING.md. SmartScreen: More info → Run anyway.

#define MyAppName "Let Me Work"
#define MyAppVersion "0.1.0-beta.1"
#define MyAppPublisher "Mark Janzen Bandola"
#define MyAppURL "https://github.com/MarkJanzenB/ai-job-scraper"
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
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
InfoBeforeFile=INFO_BEFORE.txt
SetupLogging=yes
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
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InstallOpenCodeDeps: Boolean;
var
  ResultCode: Integer;
  Retry: Boolean;
begin
  Result := True;
  Retry := True;
  while Retry do
  begin
    if not Exec(
      ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
      '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install_opencode.ps1') + '"',
      '', SW_SHOW, ewWaitUntilTerminated, ResultCode
    ) then
    begin
      ResultCode := -1;
    end;
    if ResultCode = 0 then
    begin
      Retry := False;
    end
    else
    begin
      if MsgBox(
        'OpenCode / Node.js setup failed (exit code ' + IntToStr(ResultCode) + ').' + #13#10 + #13#10 +
        'Retry now? Choose No to finish install and set up OpenCode later:' + #13#10 +
        '  npm install -g opencode-ai',
        mbConfirmation, MB_YESNO
      ) = IDNO then
      begin
        MsgBox(
          'Let Me Work is installed, but the agent needs OpenCode before scraping.' + #13#10 +
          'Docs: https://opencode.ai/docs/',
          mbInformation, MB_OK
        );
        Retry := False;
        Result := False;
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    InstallOpenCodeDeps();
  end;
end;
