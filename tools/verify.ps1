$ErrorActionPreference = "Stop"
$LocalCoreExe = "C:\Program Files\LocalCore\localcore.exe"

if (-not (Test-Path $LocalCoreExe)) {
    Write-Host "❌ ERROR: LocalCore executable not found at: $LocalCoreExe" -ForegroundColor Red
    exit 1
}

Write-Host "🛡️ [Gatekeeper] Executing LocalCore CLI Verification..." -ForegroundColor Cyan
$argList = @("--verify", "--model", "Qwen-2.5-Coder-14B", "--mode", "fast")

$process = Start-Process -FilePath $LocalCoreExe -ArgumentList $argList -NoNewWindow -PassThru
$process.WaitForExit()

$exitCode = $process.ExitCode
if ($exitCode -eq 0) {
    Write-Host "✅ [Gatekeeper Passed] Exit Code: 0" -ForegroundColor Green
} else {
    Write-Host "❌ [Gatekeeper Failed] Exit Code: $exitCode" -ForegroundColor Red
}
exit $exitCode
