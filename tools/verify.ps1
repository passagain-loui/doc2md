#Requires -Version 5.1
<#
.SYNOPSIS
    doc2md QA gatekeeper. Runs the real validation suite and returns a real exit code.

.DESCRIPTION
    The previous version of this script contained only an exit-code check with
    no command in front of it. At script start $LASTEXITCODE is $null, so the
    script fell through to `exit $null` and reported success (EXIT_CODE 0)
    without ever running a single test. Every release since then passed the
    gate unconditionally, which is why regressions kept reaching users.

    This version actually executes each check and fails loudly.
#>

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$failures = New-Object System.Collections.Generic.List[string]

function Invoke-Check {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Body
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan

    & $Body
    $code = $LASTEXITCODE

    if ($code -ne 0) {
        Write-Host "VALIDATION FAILED: $Name (exit $code)" -ForegroundColor Red
        $script:failures.Add($Name)
    } else {
        Write-Host "PASS: $Name" -ForegroundColor Green
    }
}

Write-Host "doc2md verification gate" -ForegroundColor White
Write-Host "Repo: $RepoRoot"

# 1. Version must agree between pyproject.toml and doc2md.__version__.
Invoke-Check -Name 'Version consistency' -Body {
    python tools/verify_checks.py version
}

# 2. Every module must be syntactically valid and importable in isolation.
Invoke-Check -Name 'Module import sweep' -Body {
    python tools/verify_checks.py imports
}

# 3. Release notes must exist for the current version.
Invoke-Check -Name 'Changelog coverage' -Body {
    python tools/verify_checks.py docs
}

# 4. The CLI entry point must respond.
Invoke-Check -Name 'CLI smoke test' -Body {
    python -m doc2md --version
}

# 5. Full test suite.
Invoke-Check -Name 'pytest suite' -Body {
    python -m pytest -q --tb=short
}

Write-Host ""
Write-Host "==============================================" -ForegroundColor White

if ($failures.Count -gt 0) {
    Write-Host "VALIDATION FAILED - $($failures.Count) check(s) failed:" -ForegroundColor Red
    foreach ($item in $failures) { Write-Host "  - $item" -ForegroundColor Red }
    Write-Host "==============================================" -ForegroundColor White
    exit 1
}

Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
Write-Host "==============================================" -ForegroundColor White
exit 0
