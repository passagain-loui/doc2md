if ($LASTEXITCODE -ne 0) {
    if ($LASTEXITCODE -eq 126) {
        # Apply Protocol Fallback
        .\tools\verify_fallback.ps1
    } else {
        exit $LASTEXITCODE
    }
}