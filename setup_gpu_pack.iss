; doc2md GPU Pack - optional NVIDIA CUDA runtime for GPU-accelerated transcription.
; Built by build_gpu_pack.py, which stages the DLLs into build\gpu_pack\cuda
; and verifies they can initialise CUDA on their own before this runs.

[Setup]
AppName=doc2md GPU Pack
AppVersion={#Version}
VersionInfoVersion={#Version}
AppPublisher=Passagain P.
DefaultDirName={localappdata}\doc2md\cuda
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=doc2md_GPU_Pack_v{#Version}
LicenseFile=LICENSE
WizardStyle=modern
PrivilegesRequired=lowest
Compression=lzma2/max
SolidCompression=yes
ShowLanguageDialog=no
UninstallDisplayName=doc2md GPU Pack {#Version}
CloseApplications=yes

[Messages]
WelcomeLabel2=This installs the NVIDIA CUDA runtime that doc2md needs for GPU-accelerated transcription.%n%nRequires an NVIDIA graphics card. AMD and Intel GPUs cannot be used for transcription and will continue to run on CPU.%n%ndoc2md detects this automatically - no configuration needed.

[Files]
Source: "build\gpu_pack\cuda\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssInstall then
  begin
    // doc2md loads these DLLs into its own process, so a running instance
    // holds file locks that would block the upgrade.
    Exec('taskkill.exe', '/F /IM doc2md.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
