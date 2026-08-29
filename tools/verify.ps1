$ErrorActionPreference = "Stop"
$LocalCoreExe = "C:\Program Files\LocalCore\localcore.exe"

if (-not (Test-Path $LocalCoreExe)) {
    Write-Host "❌ ERROR: LocalCore executable not found at: $LocalCoreExe" -ForegroundColor Red
    exit 1
}

Write-Host "🛡️ [Gatekeeper] Executing Real LocalCore CLI Verification..." -ForegroundColor Cyan

$processInfo = New-Object System.Diagnostics.ProcessStartInfo
$processInfo.FileName = $LocalCoreExe
$processInfo.Arguments = "--verify --model Qwen-2.5-Coder-14B"
$processInfo.RedirectStandardOutput = $true
$processInfo.RedirectStandardError = $true
$processInfo.UseShellExecute = $false
$processInfo.CreateNoWindow = $true

$process = [System.Diagnostics.Process]::Start($processInfo)
$stdout = $process.StandardOutput.ReadToEnd()
$stderr = $process.StandardError.ReadToEnd()
$process.WaitForExit()

$exitCode = $process.ExitCode
$fullLog = $stdout + $stderr

Write-Host $fullLog

# CRITICAL: Check for internal validation failures even if PowerShell exit code is 0
if ($exitCode -ne 0 -or $fullLog -match "VALIDATION FAILED" -or $fullLog -match "No command given" -or $fullLog -match "No project markers") {
    Write-Host "❌ [Gatekeeper HARD STOP] LocalCore Internal Validation Failed!" -ForegroundColor Red
    Write-Host "Exit Code: $exitCode" -ForegroundColor Red
    Write-Host "Internal Status: Check log above for VALIDATION FAILED or marker errors" -ForegroundColor Red
    exit 101
} else {
    Write-Host "✅ [Gatekeeper Passed] Real Exit Code: 0 - No internal validation failures detected" -ForegroundColor Green
    exit 0
}
