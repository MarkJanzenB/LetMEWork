; Let Me Work — Inno Setup script (unsigned pre-release)
; Prerequisites:
;   1. pyinstaller packaging/letmework.spec  → dist\LetMeWork.exe
;   2. Inno Setup 6 → Compile this script
; OpenCode is NOT bundled. Post-install: detect → (if missing + task) soft-install.
; Signing optional — see SIGNING.md. SmartScreen: More info → Run anyway.

#define MyAppName "Let Me Work"
#define MyAppVersion "0.1.0-beta.4"
#define MyAppPublisher "Mark Janzen Bandola"
#define MyAppURL "https://github.com/MarkJanzenB/LetMEWork"
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
VersionInfoVersion=0.1.0.4
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
Name: "installopencode"; Description: "Install OpenCode CLI if missing (recommended)"; GroupDescription: "AI runtime:"; Flags: checkedonce

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
function IsSilentSetup: Boolean;
begin
  Result := WizardSilent;
end;

function PsScript: String;
begin
  Result := ExpandConstant('{app}\install_opencode.ps1');
end;

function RunOpenCodeScript(const ExtraArgs: String; var ResultCode: Integer): Boolean;
begin
  Result := Exec(
    ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -ExecutionPolicy Bypass -File "' + PsScript + '" ' + ExtraArgs,
    '', SW_SHOW, ewWaitUntilTerminated, ResultCode
  );
  if not Result then
    ResultCode := -1;
end;

function DetectOpenCode: Boolean;
var
  ResultCode: Integer;
begin
  { Exit 0 = found, 2 = missing, other = treat as missing }
  RunOpenCodeScript('-DetectOnly', ResultCode);
  Result := (ResultCode = 0);
end;

function WantSoftInstall: Boolean;
begin
  { Wizard Tasks page opt-in (checked by default on first install) }
  Result := WizardIsTaskSelected('installopencode');
end;

function InstallOpenCodeDeps: Boolean;
var
  ResultCode: Integer;
  Retry: Boolean;
  Soft: Boolean;
begin
  Result := True;
  Soft := WantSoftInstall;

  { 1) Detect first — never reinstall if already present }
  if DetectOpenCode then
  begin
    if not IsSilentSetup then
      MsgBox(
        'OpenCode is already installed on this PC.' + #13#10 + #13#10 +
        'Skipping the OpenCode download step.',
        mbInformation, MB_OK
      );
    Exit;
  end;

  { 2) Missing — only soft-install when user opted in via Tasks }
  if not Soft then
  begin
    if not IsSilentSetup then
      MsgBox(
        'OpenCode was not detected, and you chose not to install it.' + #13#10 + #13#10 +
        'You can soft-install later from the app onboarding/Settings screen, or run:' + #13#10 +
        '  npm install -g opencode-ai' + #13#10 + #13#10 +
        'Docs: https://opencode.ai/docs/',
        mbInformation, MB_OK
      );
    Result := False;
    Exit;
  end;

  if not IsSilentSetup then
  begin
    if MsgBox(
      'OpenCode was not detected.' + #13#10 + #13#10 +
      'Soft-install now from official channels?' + #13#10 +
      '(npm / Scoop / Chocolatey; may install Node.js LTS if needed)' + #13#10 + #13#10 +
      'Network access is required.',
      mbConfirmation, MB_YESNO
    ) = IDNO then
    begin
      MsgBox(
        'Setup will finish without OpenCode.' + #13#10 +
        'Install later from the app or: npm install -g opencode-ai',
        mbInformation, MB_OK
      );
      Result := False;
      Exit;
    end;
  end;

  { 3) Soft install + re-detect on failure }
  Retry := True;
  while Retry do
  begin
    RunOpenCodeScript('', ResultCode);
    if ResultCode = 0 then
    begin
      if not IsSilentSetup then
        MsgBox('OpenCode is ready.', mbInformation, MB_OK);
      Retry := False;
    end
    else if DetectOpenCode then
    begin
      if not IsSilentSetup then
        MsgBox(
          'The OpenCode installer reported an error, but OpenCode was detected on this PC.' + #13#10 + #13#10 +
          'You can continue — Let Me Work will use the existing install.',
          mbInformation, MB_OK
        );
      Retry := False;
      Result := True;
    end
    else
    begin
      if IsSilentSetup then
      begin
        Retry := False;
        Result := False;
      end
      else if MsgBox(
        'OpenCode setup did not complete (exit code ' + IntToStr(ResultCode) + ').' + #13#10 + #13#10 +
        'Retry the soft install now?' + #13#10 + #13#10 +
        'Choose No to finish Setup and install later from the app or:' + #13#10 +
        '  npm install -g opencode-ai',
        mbConfirmation, MB_YESNO
      ) = IDNO then
      begin
        MsgBox(
          'Let Me Work is installed. OpenCode is still missing — scrape/score will need it.' + #13#10 +
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
    InstallOpenCodeDeps();
end;
