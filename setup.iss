; Inno Setup script for AoE4 Spotify. Build: ISCC.exe setup.iss (after building the dist\AoE4 Spotify\ folder)
#ifndef AppVer
#define AppVer "1.0.9"
#endif
#ifdef TEST
; test build (ISCC /DTEST): separate AppId/name/folder so it never touches a real install
#define AppName "AoE4 Spotify TEST"
#define AppGuid "{{0C1D7A52-93E4-4B6F-A1D2-7E55C0FFEE01}"
#else
#define AppName "AoE4 Spotify"
#define AppGuid "{{6F2B8C1E-4A7D-4E0B-9C33-A0E4F5B71D42}"
#endif
[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=Capstar
LicenseFile=LICENSE
SetupIconFile=assets\app.ico
DefaultDirName={localappdata}\Programs\{#AppName}
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=out
OutputBaseFilename={#AppName} Setup
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\_internal\assets\app.ico
; refresh Explorer's icon cache at the end (new icon shows on shortcuts / Installed apps right away)
ChangesAssociations=yes
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Files]
Source: "dist\AoE4 Spotify\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "config.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"
Source: "aoe4_spotify.py"; DestDir: "{app}\source"
Source: "aoe4spotify\*"; DestDir: "{app}\source\aoe4spotify"; Excludes: "*\__pycache__\*,__pycache__\*,*.pyc,*.bak*"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "config.json"; DestDir: "{app}\source"
Source: "setup.iss"; DestDir: "{app}\source"
Source: "build.md"; DestDir: "{app}\source"
Source: "build.bat"; DestDir: "{app}\source"
Source: "LICENSE"; DestDir: "{app}\source"
Source: "make_icon.py"; DestDir: "{app}\source"
Source: "make_gtg_frames.py"; DestDir: "{app}\source"
Source: "make_editor_assets.py"; DestDir: "{app}\source"
Source: "assets\app.ico"; DestDir: "{app}\source\assets"

[Icons]
; the app window (settings)
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\assets\app.ico"
Name: "{userprograms}\{#AppName}"; Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\assets\app.ico"

[InstallDelete]
; app is a PyInstaller folder build (exe + _internal); drop stale libraries from an older build first
Type: filesandordirs; Name: "{app}\_internal"
; older versions used a Windows Startup shortcut
Type: files; Name: "{userstartup}\{#AppName}.lnk"
; 0.2-0.3.2 shortcuts were called "AoE4 Spotify Control Panel"
Type: files; Name: "{userdesktop}\{#AppName} Control Panel.lnk"
Type: files; Name: "{userprograms}\{#AppName} Control Panel.lnk"
Type: files; Name: "{userprograms}\{#AppName}.lnk"

[Run]
; no arguments = Spotify login only, then it exits
Filename: "{app}\AoE4 Spotify.exe"; WorkingDir: "{app}"; Description: "Log in to Spotify now"; Flags: postinstall nowait skipifsilent
; in-app update (silent, /RELAUNCH=1): reopen the app window, which shows "Updated to x.y"
Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel --updated"; WorkingDir: "{app}"; Flags: nowait; Check: Relaunch
; any other install while AoE4 is running: quietly re-attach the music switcher to that game
Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--attach"; WorkingDir: "{app}"; Flags: nowait runhidden; Check: not Relaunch
; the control panel was open when setup started (setup closed it): open it again
Filename: "{app}\AoE4 Spotify.exe"; Parameters: "--panel"; WorkingDir: "{app}"; Flags: nowait; Check: ReopenPanel

[UninstallDelete]
#ifndef TEST
Type: filesandordirs; Name: "{userappdata}\AoE4Spotify"
#endif
Type: files; Name: "{app}\launch_option_backup.json"
Type: files; Name: "{localappdata}\Temp\AoE4.Spotify.Setup-*.exe"
Type: files; Name: "{localappdata}\Temp\AoE4 Spotify Setup *.exe"
Type: files; Name: "{localappdata}\Temp\AoE4Spotify_window_*.hwnd"
Type: filesandordirs; Name: "{app}\source"
Type: dirifempty; Name: "{app}"

[Code]
{ Steam rewrites localconfig.vdf while running, so Steam is closed (gracefully) before we edit
  AoE4's launch option and reopened afterwards if it was running.
  Test-only switches: /STEAMPROC=<process name> /STEAMEXE=<path> /STEAMPATH=<dir> (or the matching
  AOE4SPOTIFY_STEAM_* environment variables) to use a dummy Steam. }
var SteamWasRunning, LaunchOptionAlreadySet, PanelWasOpen: Boolean;

function GetWindowThreadProcessId(Wnd: HWND; var Pid: DWORD): DWORD; external 'GetWindowThreadProcessId@user32.dll stdcall';

function Relaunch(): Boolean;
begin Result := ExpandConstant('{param:RELAUNCH|0}') = '1'; end;

{ /FROMSWITCHER=1: started by the app's own music switcher, which has checked that no match is running. }
function FromSwitcher(): Boolean;
begin Result := ExpandConstant('{param:FROMSWITCHER|0}') = '1'; end;

function ReopenPanel(): Boolean;
begin Result := PanelWasOpen and not Relaunch(); end;

{ True if AoE4's launch option in some Steam user's localconfig.vdf already starts this install's exe.
  Then nothing needs changing and Steam is left alone (typical for upgrades). /STEAMPATH= is for tests. }
function LaunchOptionOK(): Boolean;
var SP, P, Want: String; FR: TFindRec; Body: AnsiString;
begin
  Result := False;
  SP := ExpandConstant('{param:STEAMPATH|}');
#ifdef TEST
  if SP = '' then SP := GetEnv('AOE4SPOTIFY_STEAM_PATH');
#endif
  if SP = '' then
    if not RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamPath', SP) then Exit;
  StringChangeEx(SP, '/', '\', True);
  P := ExpandConstant('{app}\AoE4 Spotify.exe');
  StringChangeEx(P, '\', '\\', True);                 { VDF escapes backslashes and quotes }
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
#ifdef TEST
  if Result = '' then Result := GetEnv('AOE4SPOTIFY_STEAM_PROC');   { test runs (dummy Steam) }
#endif
  if Result = '' then Result := 'steam.exe';
end;

function SteamExe(): String;
begin
  Result := ExpandConstant('{param:STEAMEXE|}');
#ifdef TEST
  if Result = '' then Result := GetEnv('AOE4SPOTIFY_STEAM_EXE');
#endif
  if Result = '' then
    if not RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'SteamExe', Result) then Result := '';
end;

{ The game's process. Test-only: /GAMEPROC= or AOE4SPOTIFY_GAME_PROC (dummy game). }
function GameProc(): String;
begin
  Result := ExpandConstant('{param:GAMEPROC|}');
#ifdef TEST
  if Result = '' then Result := GetEnv('AOE4SPOTIFY_GAME_PROC');
#endif
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

{ Stop running copies of THIS install's exe only (by full path). }
procedure KillApp();
var Loc, Svc, Res: Variant; P: String; I: Integer;
begin
  P := ExpandConstant('{app}\AoE4 Spotify.exe');
  StringChangeEx(P, '\', '\\', True);
  try
    Loc := CreateOleObject('WbemScripting.SWbemLocator');
    Svc := Loc.ConnectServer('.', 'root\CIMV2');
    Res := Svc.ExecQuery('SELECT * FROM Win32_Process WHERE ExecutablePath=''' + P + '''');
    for I := 0 to Res.Count - 1 do Res.ItemIndex(I).Terminate();
  except
    Log('KillApp: ' + GetExceptionMessage);
  end;
  Sleep(700);
end;

{ Running copies of THIS install's exe: the control panel (--panel) or everything else (switcher, login, attach). }
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

{ Close the open control panel: ask its window to close (like clicking X), wait up to 6 s, then end only
  the panel process. The window handle comes from the file the panel writes, and is used only if it
  really belongs to a running panel process (a stale handle could be some other program's window). }
procedure ClosePanel();
var Res: Variant; I, J: Integer; Pid, Owner: DWORD; Wnd: Longint; S: AnsiString; F: String;
begin
  PanelWasOpen := False;
  try
    Res := AppProcs(True);
    PanelWasOpen := Res.Count > 0;
    if not PanelWasOpen then Exit;
    F := GetEnv('TEMP') + '\AoE4Spotify_window_panel';
#ifdef TEST
    F := F + GetEnv('AOE4SPOTIFY_MUTEX_SUFFIX');
#endif
    F := F + '.hwnd';
    Wnd := 0;
    if LoadStringFromFile(F, S) then Wnd := StrToIntDef(Trim(String(S)), 0);
    Owner := 0;
    if Wnd <> 0 then GetWindowThreadProcessId(Wnd, Owner);
    for I := 0 to Res.Count - 1 do begin
      Pid := Res.ItemIndex(I).ProcessId;
      if (Owner <> 0) and (Pid = Owner) then begin
        Log('Closing the control panel (pid ' + IntToStr(Pid) + ') gracefully');
        PostMessage(Wnd, $0010, 0, 0);              { WM_CLOSE }
      end;
    end;
    for J := 1 to 24 do begin                        { up to 6 s }
      if AppCount(True) = 0 then begin Log('Control panel closed gracefully'); Exit; end;
      Sleep(250);
    end;
    Res := AppProcs(True);
    for I := 0 to Res.Count - 1 do begin
      Log('Control panel still open after 6 s - ending only the panel (pid ' + IntToStr(Res.ItemIndex(I).ProcessId) + ')');
      Res.ItemIndex(I).Terminate();
    end;
    Sleep(500);
  except
    Log('ClosePanel: ' + GetExceptionMessage);
  end;
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
var R: Integer;
begin
  { Never touch the game, and never stop the app while it follows a game: only the app's own switcher
    (/FROMSWITCHER=1, after it checked no match is on) may install while the game runs. }
  if ProcRunning(GameProc()) and not FromSwitcher() then begin
    Log('Age of Empires IV is running - setup stopped without changing anything');
    Result := 'Age of Empires IV is running. Close the game first, then run setup again.';
    if Relaunch() and (AppCount(True) = 0) then             { the panel's Update button closed it: bring it back }
      Exec(ExpandConstant('{app}\AoE4 Spotify.exe'), '--panel', ExpandConstant('{app}'), SW_SHOWNORMAL, ewNoWait, R);
    Exit;
  end;
  ClosePanel();
  KillApp();                                         { anything left: a switcher whose game has closed, login window }
  LaunchOptionAlreadySet := LaunchOptionOK();
  if LaunchOptionAlreadySet then begin Log('Launch option already set - Steam left alone'); Result := ''; Exit; end;
  if CloseSteam() then Result := '' else Result := 'Setup was cancelled because Steam must be closed while it finishes.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var R: Integer;
begin
  if (CurStep = ssPostInstall) and not LaunchOptionAlreadySet then begin
    Exec(ExpandConstant('{app}\AoE4 Spotify.exe'), '--set-launch-option', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, R);
    ReopenSteam();
  end;
end;

{ One click to uninstall: our own confirm (mentions Steam), then the uninstaller re-runs itself silently,
  so there is no second "Are you sure" box, no Steam prompt and no "successfully removed" box. }
function InitializeUninstall(): Boolean;
var R: Integer; Msg: String;
begin
  Result := False;
  if not UninstallSilent() then begin
    Msg := 'Removes the app, its shortcuts and settings, and puts the game''s launch options and music volume back.';
    if ProcRunning(SteamProc()) then Msg := Msg + #13#10#13#10 + 'Steam will close for a moment and reopen by itself.';
    if TaskDialogMsgBox('Uninstall AoE4 Spotify?', Msg, mbConfirmation, MB_OKCANCEL, ['Uninstall', 'Cancel'], 0) <> IDOK then Exit;
    { start the silent run ~1 s later, after this one has let go of unins000.dat }
    Exec(ExpandConstant('{cmd}'), '/c ping -n 2 127.0.0.1 >nul & start "" "' + ExpandConstant('{app}\unins000.exe') + '" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART', '', SW_HIDE, ewNoWait, R);
    Exit;                                              { this (interactive) run ends here; the silent run does the work }
  end;
  KillApp();
  Result := CloseSteam();                              { silent: closes Steam without asking }
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var R: Integer;
begin
  if CurUninstallStep = usUninstall then
    Exec(ExpandConstant('{app}\AoE4 Spotify.exe'), '--remove-launch-option', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, R);
  if CurUninstallStep = usPostUninstall then ReopenSteam();
end;
