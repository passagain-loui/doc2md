$ErrorActionPreference = "Stop"
$LocalCoreExe = "C:\Program Files\LocalCore\localcore.exe"

if (-not (Test-Path $LocalCoreExe)) {
    Write-Host "❌ ERROR: LocalCore executable not found at: $LocalCoreExe" -ForegroundColor Red
    exit 1
}

Write-Host "🛡️ [Gatekeeper] Executing LocalCore CLI Verification..." -ForegroundColor Cyan

# รัน pytest ผ่าน python module ล่วงหน้า ป้องกันปัญหา System PATH
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    python -m pytest tests/ -q --tb=line
}

$processInfo = New-Object System.Diagnostics.ProcessStartInfo
$processInfo.FileName = $LocalCoreExe
$processInfo.Arguments = "--verify --model Qwen-2.5-Coder-7B"
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

if ($exitCode -ne 0 -or $fullLog -match "VALIDATION FAILED" -or $fullLog -match "is not recognized" -or $fullLog -match "No command given") {
    Write-Host "❌ [Gatekeeper HARD STOP] LocalCore Internal Validation Failed!" -ForegroundColor Red
    exit 101
} else {
    Write-Host "✅ [Gatekeeper Passed] Real Exit Code: 0" -ForegroundColor Green
    exit 0
}
