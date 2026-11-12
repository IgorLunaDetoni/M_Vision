# Verify environment handoff/cleanup without a real key, server, or API call.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$testDirectory = Join-Path $projectRoot ('data/launcher-test-' + [guid]::NewGuid().ToString('N'))
$previousKey = $env:AISSTREAM_API_KEY
$previousSource = $env:VESSEL_SOURCE
try {
    [void](New-Item -ItemType Directory -Path $testDirectory)
    Copy-Item -LiteralPath (Join-Path $projectRoot 'start-aisstream.ps1') -Destination $testDirectory
    @'
if ($env:AISSTREAM_API_KEY -ne 'test-only-launcher-key') { throw 'Child did not receive the test credential.' }
if ($env:VESSEL_SOURCE -ne 'aisstream') { throw 'Child did not receive the AIS source.' }
exit 7
'@ | Set-Content -LiteralPath (Join-Path $testDirectory 'start.ps1') -Encoding UTF8
    $env:AISSTREAM_API_KEY = 'test-only-launcher-key'
    $env:VESSEL_SOURCE = 'disabled'
    & (Join-Path $testDirectory 'start-aisstream.ps1')
    if ($LASTEXITCODE -ne 7) { throw 'Launcher did not preserve the application exit code.' }
    if ($env:AISSTREAM_API_KEY -ne 'test-only-launcher-key' -or $env:VESSEL_SOURCE -ne 'disabled') {
        throw 'Launcher did not restore the prior environment.'
    }
    Set-Content -LiteralPath (Join-Path $testDirectory 'start.ps1') -Value "throw 'Simulated application failure.'"
    $failed = $false
    try { & (Join-Path $testDirectory 'start-aisstream.ps1') } catch { $failed = $true }
    if (-not $failed -or $env:AISSTREAM_API_KEY -ne 'test-only-launcher-key' -or $env:VESSEL_SOURCE -ne 'disabled') {
        throw 'Launcher did not restore the environment after application failure.'
    }
    Write-Host 'PASS: child handoff, exit code and environment cleanup on success/failure.'
} finally {
    $env:AISSTREAM_API_KEY = $previousKey
    $env:VESSEL_SOURCE = $previousSource
    foreach ($name in @('start-aisstream.ps1','start.ps1')) {
        $testFile = Join-Path $testDirectory $name
        if (Test-Path -LiteralPath $testFile) { Remove-Item -LiteralPath $testFile }
    }
    if (Test-Path -LiteralPath $testDirectory) { Remove-Item -LiteralPath $testDirectory }
}
