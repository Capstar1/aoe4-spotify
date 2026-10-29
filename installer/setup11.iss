; AoE4 Spotify 1.1 (Rust, Slint UI) installer. Build: ISCC.exe installer\setup11.iss  (after cargo build --release -p aoe4spotify-slint)
; No WebView2: the Slint build draws its own windows (software renderer), so no runtime bootstrapper is shipped or run.
; Upgrades in place from 1.0.9 (PyInstaller) and from the Tauri 1.1 build: same AppId, name, folder, exe name and
; data folder (%APPDATA%\AoE4Spotify-1.1, untouched); the Tauri build's WebView2 profile is removed.
; Same AppId, name and folder as 1.0.x, so 1.0.9's own auto-updater (GitHub release asset, run with
; /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/RELAUNCH=1 | /FROMSWITCHER=1] /LOG=...) upgrades in place:
; the 1.0.9 files (PyInstaller _internal\, source\) are removed, the Steam launch option keeps pointing at
; "<this folder>\AoE4 Spotify.exe" %command% (your other options stay), and the 1.1 exe imports the 1.0.9
; settings, intros, presets, covers, Spotify login and saved game-music level (verified), then deletes the 1.0.9 data.
#ifndef AppVer
#define AppVer "1.1.2"
#endif
#ifdef TEST
; test build (ISCC /DTEST): the 1.0.9 TEST build's AppId/name/folder, so upgrade tests never touch a real install
#define AppName "AoE4 Spotify TEST"
#define AppGuid "{{0C1D7A52-93E4-4B6F-A1D2-7E55C0FFEE01}"
; sandbox: per-user paths from the (test-set) environment, shortcuts into AOE4S_DESKTOP (else the install folder)
#define LAD "{%LOCALAPPDATA}"
#define Desk "{%AOE4S_DESKTOP|{app}}"
#define Progs "{%AOE4S_DESKTOP|{app}}\Start"
#else
#define AppName "AoE4 Spotify"
#define AppGuid "{{6F2B8C1E-4A7D-4E0B-9C33-A0E4F5B71D42}"
#define LAD "{localappdata}"
#define Desk "{userdesktop}"
#define Progs "{userprograms}"
#endif
#define Root ".."
[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=Capstar
LicenseFile={#Root}\installer\LICENSE
SetupIconFile={#Root}\installer\icon.ico
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir={#Root}\out
OutputBaseFilename={#AppName} Setup {#AppVer}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\app.ico
ChangesAssociations=yes
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Files]
Source: "{#Root}\target\release\aoe4spotify-slint.exe"; DestDir: "{app}"; DestName: "AoE4 Spotify.exe"; Flags: ignoreversion
Source: "{#Root}\installer\config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\installer\icon.ico"; DestDir: "{app}"; DestName: "app.ico"; Flags: ignoreversion
Source: "{#Root}\installer\LICENSE"; DestDir: "{app}"

[Icons]
Name: "{#Desk}\{#AppName}"; Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"
Name: "{#Progs}\{#AppName}"; Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel"; WorkingDir: "{app}"; IconFilename: "{app}\app.ico"

[InstallDelete]
; 1.0.x was a PyInstaller folder build: its libraries and bundled source go (settings/token are imported by the exe)
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\source"
Type: files; Name: "{userstartup}\{#AppName}.lnk"
; Tauri 1.1 -> Slint: the WebView2 profile of the Tauri build (Tauri identifier folder; settings live in AoE4Spotify-1.1)
Type: filesandordirs; Name: "{#LAD}\com.capstar1.aoe4spotify"

[Run]
Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel"; WorkingDir: "{app}"; Description: "Open AoE4 Spotify"; Flags: postinstall nowait skipifsilent
Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel --updated"; WorkingDir: "{app}"; Flags: nowait; Check: Relaunch
Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--attach"; WorkingDir: "{app}"; Flags: nowait runhidden; Check: not Relaunch
Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel"; WorkingDir: "{app}"; Flags: nowait; Check: ReopenPanel

[UninstallDelete]
#ifndef TEST
Type: filesandordirs; Name: "{userappdata}\AoE4Spotify-1.1"
Type: filesandordirs; Name: "{userappdata}\AoE4Spotify"
#else
; TEST: delete only a sandbox data folder (APPDATA must point into a sbx_ test dir), never the real one
Type: filesandordirs; Name: "{code:SbxData}\AoE4Spotify-1.1"
#endif
Type: files; Name: "{app}\launch_option_backup.json"
Type: filesandordirs; Name: "{#LAD}\com.capstar1.aoe4spotify"
Type: files; Name: "{#LAD}\Temp\AoE4.Spotify.Setup-*.exe"
Type: files; Name: "{#LAD}\Temp\AoE4 Spotify Setup *.exe"
Type: dirifempty; Name: "{app}"

[Code]
var SteamWasRunning, LaunchOptionAlreadySet, PanelWasOpen: Boolean;

function Relaunch(): Boolean; begin Result := ExpandConstant('{param:RELAUNCH|0}') = '1'; end;
function FromSwitcher(): Boolean; begin Result := ExpandConstant('{param:FROMSWITCHER|0}') = '1'; end;
function ReopenPanel(): Boolean; begin Result := PanelWasOpen and not Relaunch(); end;

function TestEnv(Name: String): String;
begin
  Result := '';
#ifdef TEST
  Result := GetEnv(Name);
#endif
end;

function SbxData(Param: String): String;
begin
  Result := TestEnv('APPDATA');
  if Pos('sbx_', Lowercase(Result)) = 0 then Result := ExpandConstant('{tmp}') + '\no-sandbox';
end;

function LaunchOptionOK(): Boolean;
var SP, P, Want: String; FR: TFindRec; Body: AnsiString;
begin
  Result := False;
  SP := ExpandConstant('{param:STEAMPATH|}');
  if SP = '' then SP := TestEnv('AOE4SPOTIFY_STEAM_PATH');
  if SP = '' then
    if not RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamPath', SP) then Exit;
  StringChangeEx(SP, '/', '\', True);
  P := ExpandConstant('{app}\AoE4 Spotify.exe');
  StringChangeEx(P, '\', '\\', True);
  Want := Lowercase('\"' + P + '\" %command%');
  if FindFirst(SP + '\userdata\*', FR) then
    try
      repeat
        if (FR.Name <> '.') and (FR.Name <> '..') and
           LoadStringFromFile(SP + '\userdata\' + FR.Name + '\config\localconfig.vdf', Body) then
          if Pos(Want, Lowercase(String(Body))) > 0 then Result := True;
      until Result or not FindNext(FR);
    finally
      FindClose(FR);
    end;
end;

function SteamProc(): String;
begin
  Result := ExpandConstant('{param:STEAMPROC|}');
  if Result = '' then Result := TestEnv('AOE4SPOTIFY_STEAM_PROC');
  if Result = '' then Result := 'steam.exe';
end;
function SteamExe(): String;
begin
  Result := ExpandConstant('{param:STEAMEXE|}');
  if Result = '' then Result := TestEnv('AOE4SPOTIFY_STEAM_EXE');
  if Result = '' then
    if not RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamExe', Result) then Result := '';
end;
function GameProc(): String;
begin
  Result := ExpandConstant('{param:GAMEPROC|}');
  if Result = '' then Result := TestEnv('AOE4SPOTIFY_GAME_PROC');
  if Result = '' then Result := 'RelicCardinal.exe';
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

{ Running copies of THIS install's exe (1.0.9 panel/switcher or 1.1). Panel = command line has --panel. }
function AppProcs(Panel: Boolean): Variant;
var Loc, Svc: Variant; P, Q: String;
begin
  P := ExpandConstant('{app}\AoE4 Spotify.exe');
  StringChangeEx(P, '\', '\\', True);
  Q := 'SELECT ProcessId FROM Win32_Process WHERE ExecutablePath=''' + P + ''' AND ';
  if Panel then Q := Q + 'CommandLine LIKE ''%--panel%''' else Q := Q + '(CommandLine IS NULL OR NOT CommandLine LIKE ''%--panel%'')';
  Loc := CreateOleObject('WbemScripting.SWbemLocator');
  Svc := Loc.ConnectServer('.', 'root\CIMV2');
  Result := Svc.ExecQuery(Q);
end;
function AppCount(Panel: Boolean): Integer;
begin
  try Result := AppProcs(Panel).Count; except Result := 0; end;
end;
procedure KillApp(Panel: Boolean);
var Res: Variant; I: Integer;
begin
  try
    Res := AppProcs(Panel);
    if Panel then PanelWasOpen := Res.Count > 0;
    for I := 0 to Res.Count - 1 do begin Log('Ending app process ' + IntToStr(Res.ItemIndex(I).ProcessId)); Res.ItemIndex(I).Terminate(); end;
  except
    Log('KillApp: ' + GetExceptionMessage);
  end;
  Sleep(700);
end;

function IsSilentRun(): Boolean;
begin
  if IsUninstaller() then Result := UninstallSilent() else Result := WizardSilent();
end;

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
  for I := 1 to 60 do begin
    if not ProcRunning(SteamProc()) then Break;
    Sleep(500);
  end;
  if ProcRunning(SteamProc()) then begin
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
var I: Integer;
begin
  Result := '';
  { Never update while Age of Empires IV runs - not even from the switcher (/FROMSWITCHER=1): silent runs wait
    in the background until the game has closed, interactive runs ask you to close it. }
  if ProcRunning(GameProc()) then begin
    if IsSilentRun() then begin
      Log('Age of Empires IV is running - waiting until it closes before updating');
      I := 0;
      while ProcRunning(GameProc()) and (I < 8640) do begin Sleep(5000); I := I + 1; end;     { up to 12 h }
      if ProcRunning(GameProc()) then begin Result := 'Age of Empires IV is still running.'; Exit; end;
      Log('Age of Empires IV closed - updating now');
      Sleep(15000);                                     { let the old switcher hand Spotify back and exit }
    end else begin
      Result := 'Age of Empires IV is running. Close the game first, then run setup again.'; Exit;
    end;
  end;
  KillApp(True);                                        { panel (setup reopens it afterwards) }
  KillApp(False);                                       { switcher / login window of 1.0.x or 1.1 }
  LaunchOptionAlreadySet := LaunchOptionOK();
  if LaunchOptionAlreadySet then begin Log('Launch option already set - Steam left alone'); Exit; end;
  if not CloseSteam() then Result := 'Setup was cancelled because Steam must be closed while it finishes.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var R: Integer;
begin
  if CurStep = ssPostInstall then begin
    { 1.0.9 -> 1.1: import settings, intros, presets, covers, Spotify login and saved music level; the 1.0.9 data
      is deleted only when the copy verified (exit code 0). }
    if Exec(ExpandConstant('{app}\AoE4 Spotify.exe'), '--migrate-109 "' + ExpandConstant('{app}') + '" --cleanup', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, R) then
      Log('1.0.9 import exit code ' + IntToStr(R) + ' (0 = verified, 2 = nothing to import or not verified: 1.0.9 data kept)');
    if not LaunchOptionAlreadySet then begin
      Exec(ExpandConstant('{app}\AoE4 Spotify.exe'), '--set-launch-option', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, R);
      ReopenSteam();
    end;
  end;
end;

function InitializeUninstall(): Boolean;
var R: Integer; Msg: String;
begin
  Result := False;
  if not UninstallSilent() then begin
    Msg := 'Removes the app, its shortcuts and settings, and puts the game''s launch options and music volume back.';
    if ProcRunning(SteamProc()) then Msg := Msg + #13#10#13#10 + 'Steam will close for a moment and reopen by itself.';
    if TaskDialogMsgBox('Uninstall AoE4 Spotify?', Msg, mbConfirmation, MB_OKCANCEL, ['Uninstall', 'Cancel'], 0) <> IDOK then Exit;
    Exec(ExpandConstant('{cmd}'), '/c ping -n 2 127.0.0.1 >nul & start "" "' + ExpandConstant('{app}\unins000.exe') + '" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewNoWait, R);
    Exit;
  end;
  if ProcRunning(GameProc()) then begin Log('Age of Empires IV is running - uninstall stopped'); Exit; end;
  KillApp(True); KillApp(False);
  Result := CloseSteam();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var R: Integer;
begin
  if CurUninstallStep = usUninstall then
    Exec(ExpandConstant('{app}\AoE4 Spotify.exe'), '--remove-launch-option', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, R);
  if CurUninstallStep = usPostUninstall then ReopenSteam();
end;
