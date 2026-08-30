[Setup]
AppName=doc2md
AppVersion={#Version}
VersionInfoVersion={#Version}
AppPublisher=Claude Code
DefaultDirName={autopf}\doc2md
DefaultGroupName=doc2md
OutputDir=dist
OutputBaseFilename=doc2md_Setup_v{#Version}
AllowNoIcons=yes
LicenseFile=LICENSE
WizardStyle=modern
PrivilegesRequired=lowest
SetupLogging=yes
Compression=lzma
SolidCompression=yes
ShowLanguageDialog=no
UninstallDisplayName=doc2md {#Version}
CloseApplications=yes
RestartApplications=yes

[Files]
Source: "dist\doc2md.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\doc2md"; Filename: "{app}\doc2md.exe"
Name: "{userdesktop}\doc2md"; Filename: "{app}\doc2md.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\doc2md.exe"; Description: "Launch doc2md"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    // Forcefully terminate all running doc2md.exe instances (and child processes)
    // /F = Force termination
    // /IM = Image name (executable filename)
    // /T = Terminate entire process tree (children included)
    Exec('taskkill.exe', '/F /IM doc2md.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    // Forcefully terminate all background ffmpeg.exe instances
    Exec('taskkill.exe', '/F /IM ffmpeg.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

    // Small delay to ensure processes are fully terminated
    Sleep(500);
  end;
end;
