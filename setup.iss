; Inno Setup script for AoE4 Spotify. Build: ISCC.exe setup.iss (after building dist\AoE4 Spotify.exe)
#define AppName "AoE4 Spotify"
[Setup]
AppId={{6F2B8C1E-4A7D-4E0B-9C33-A0E4F5B71D42}
AppName={#AppName}
AppVersion=1.4
AppPublisher=Capstar
LicenseFile=LICENSE
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=out
OutputBaseFilename=AoE4 Spotify Setup
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\AoE4 Spotify.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Files]
Source: "dist\AoE4 Spotify.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"
Source: "aoe4_spotify_friend.py"; DestDir: "{app}\source"
Source: "config.json"; DestDir: "{app}\source"
Source: "setup.iss"; DestDir: "{app}\source"
Source: "build.md"; DestDir: "{app}\source"
Source: "build.bat"; DestDir: "{app}\source"
Source: "LICENSE"; DestDir: "{app}\source"

[InstallDelete]
; older versions used a Windows Startup shortcut
Type: files; Name: "{userstartup}\AoE4 Spotify.lnk"

[Run]
; no arguments = Spotify login only, then it exits
Filename: "{app}\AoE4 Spotify.exe"; WorkingDir: "{app}"; Description: "Log in to Spotify now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\AoE4Spotify"
Type: files; Name: "{app}\launch_option_backup.json"

[Code]
{ Steam rewrites localconfig.vdf while running, so Steam is closed (gracefully) before we edit
  AoE4's launch option and reopened afterwards if it was running.
  Test-only switches: /STEAMPROC=<process name> /STEAMEXE=<path> to use a dummy process. }
var SteamWasRunning: Boolean;

function SteamProc(): String;
begin Result := ExpandConstant('{param:STEAMPROC|steam.exe}'); end;

function SteamExe(): String;
begin
  Result := ExpandConstant('{param:STEAMEXE|}');
  if Result = '' then
    if not RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamExe', Result) then Result := '';
end;

function ProcRunning(Name: String): Boolean;
var Loc, Svc, Res: Variant;
begin
  Result := False;
  try
    Loc := CreateOleObject('WbemScripting.SWbemLocator');
    Svc := Loc.ConnectServer('.', 'root\CIMV2');
    Res := Svc.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name=''' + Name + '''');
    Result := Res.Count > 0;
  except
  end;
end;

procedure KillApp();
var R: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "AoE4 Spotify.exe"', '', SW_HIDE, ewWaitUntilTerminated, R);
  Sleep(500);
end;

function IsSilentRun(): Boolean;
begin
  if IsUninstaller() then Result := UninstallSilent() else Result := WizardSilent();
end;

{ Returns False if the user cancelled. }
function CloseSteam(): Boolean;
var R, I: Integer;
begin
  Result := True;
  SteamWasRunning := ProcRunning(SteamProc());
  if not SteamWasRunning then Exit;
  if not IsSilentRun() then
    if TaskDialogMsgBox('Steam needs to close to finish setup.',
         'It will reopen automatically.' + #13#10#13#10 + 'AoE4 Spotify adds itself to Age of Empires IV''s Steam launch options, and Steam must be closed while that file is changed.',
         mbConfirmation, MB_OKCANCEL, ['Continue', 'Cancel'], 0) <> IDOK then begin Result := False; Exit; end;
  Log('Closing Steam gracefully');
  if SteamExe() <> '' then Exec(SteamExe(), '-shutdown', '', SW_HIDE, ewNoWait, R);
  for I := 1 to 60 do begin                        { wait up to 30 s }
    if not ProcRunning(SteamProc()) then Break;
    Sleep(500);
  end;
  if ProcRunning(SteamProc()) then begin            { last resort }
    Log('Steam did not exit in 30 s - force closing');
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "' + SteamProc() + '"', '', SW_HIDE, ewWaitUntilTerminated, R);
    Sleep(1500);
  end;
  Log('Steam closed');
end;

procedure ReopenSteam();
var R: Integer;
begin
  if SteamWasRunning and (SteamExe() <> '') then begin
    Log('Reopening Steam');
    Exec(SteamExe(), '-silent', '', SW_SHOWMINNOACTIVE, ewNoWait, R);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  KillApp();
  if CloseSteam() then Result := '' else Result := 'Setup was cancelled because Steam must be closed while it finishes.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var R: Integer;
begin
  if CurStep = ssPostInstall then begin
    Exec(ExpandConstant('{app}\AoE4 Spotify.exe'), '--set-launch-option', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, R);
    ReopenSteam();
  end;
end;

function InitializeUninstall(): Boolean;
begin
  KillApp();
  Result := CloseSteam();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var R: Integer;
begin
  if CurUninstallStep = usUninstall then
    Exec(ExpandConstant('{app}\AoE4 Spotify.exe'), '--remove-launch-option', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, R);
  if CurUninstallStep = usPostUninstall then ReopenSteam();
end;
