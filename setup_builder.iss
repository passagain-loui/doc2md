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
