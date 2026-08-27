; doc2md Windows installer - Inno Setup 6 script
; Compiled by build_installer.py: ISCC.exe setup_builder.iss /DVersion=x.y.z

#define AppName "doc2md"
#ifndef Version
#define Version "0.3.18"
#endif

[Setup]
AppId={{7C1E9F42-3B8D-4A66-9E15-2C4A8D0F5B31}}
AppName={#AppName}
AppVersion={#Version}
AppVerName={#AppName} v{#Version}
DefaultDirName={userpf}\{#AppName}
PrivilegesRequired=lowest
ChangesEnvironment=yes
OutputDir=dist
OutputBaseFilename=doc2md_Setup_v{#Version}
UninstallDisplayName={#AppName} v{#Version}
UninstallDisplayIcon={app}\doc2md.exe
DisableProgramGroupPage=yes
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
CloseApplicationsFilter=*doc2md.exe*
RestartApplications=no
AppMutex=doc2md_Single_Instance_Mutex
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "dist\doc2md.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\ffmpeg.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "dist\ffprobe.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\doc2md.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
Name: "{userstartmenu}\{#AppName}"; Filename: "{app}\doc2md.exe"; IconFilename: "{app}\icon.ico"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional tasks:"; Flags: unchecked

[Registry]
Root: HKCU; Subkey: "Software\Classes\*\shell\doc2md"; ValueType: string; ValueName: ""; ValueData: "Convert to Token-Optimized Markdown"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\doc2md"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\doc2md.exe"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\*\shell\doc2md\command"; ValueType: string; ValueName: ""; ValueData: """{app}\doc2md.exe"" ""%1"" -c -s"; Flags: uninsdeletekey

[Run]
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden waituntilterminated skipifsilent
Filename: "{app}\doc2md.exe"; Parameters: "--version"; Description: "Verify installation"; Flags: runhidden nowait skipifsilent
Filename: "{app}\doc2md.exe"; Description: "Launch {#AppName} Converter"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
const
  EnvKey = 'Environment';
  EnvValue = 'Path';

function DirInPath(const FullPath, Dir: string): Boolean;
var
  UpperPath, UpperDir: string;
begin
  UpperPath := ';' + Uppercase(FullPath) + ';';
  UpperDir := ';' + Uppercase(Dir) + ';';
  Result := Pos(UpperDir, UpperPath) > 0;
end;

function RemoveDirFromPath(const CurrentPath, DirToRemove: string): string;
var
  WorkUpper, UpperDirWithSemi: string;
  Idx: Integer;
begin
  Result := CurrentPath;
  if Uppercase(Trim(Result)) = Uppercase(DirToRemove) then
  begin
    Result := '';
    Exit;
  end;
  UpperDirWithSemi := ';' + Uppercase(DirToRemove) + ';';
  WorkUpper := ';' + Uppercase(Result) + ';';
  while Pos(UpperDirWithSemi, WorkUpper) > 0 do
  begin
    Idx := Pos(UpperDirWithSemi, WorkUpper);
    Delete(Result, Idx, Length(DirToRemove) + 1);
    WorkUpper := ';' + Uppercase(Result) + ';';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Path, AppDir: string;
begin
  if CurStep = ssPostInstall then
  begin
    AppDir := ExpandConstant('{app}');
    if not RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, EnvValue, Path) then
      Path := '';
    if not DirInPath(Path, AppDir) then
    begin
      if Trim(Path) = '' then
        Path := AppDir
      else if Copy(Path, Length(Path), 1) = ';' then
        Path := Path + AppDir
      else
        Path := Path + ';' + AppDir;
      RegWriteStringValue(HKEY_CURRENT_USER, EnvKey, EnvValue, Path);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Path, AppDir, NewPath: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    AppDir := ExpandConstant('{app}');
    if RegQueryStringValue(HKEY_CURRENT_USER, EnvKey, EnvValue, Path) then
    begin
      NewPath := RemoveDirFromPath(Path, AppDir);
      if NewPath <> Path then
        RegWriteStringValue(HKEY_CURRENT_USER, EnvKey, EnvValue, NewPath);
    end;
  end;
end;
