# Windows integration test. Uses a random test target, never the real AIS key.
param([switch]$ReadOnly, [string]$Target)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../scripts/windows-credentials.ps1')

function Assert-Secret([System.Security.SecureString]$Secret, [string]$Expected) {
    if ($null -eq $Secret) { throw 'Test credential not found.' }
    $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
    try {
        if ($Secret.Length -ne $Expected.Length) { throw 'Stored credential length differs.' }
        for ($i = 0; $i -lt $Expected.Length; $i++) {
            $actual = [uint16]([int][System.Runtime.InteropServices.Marshal]::ReadInt16($pointer, $i * 2) -band 65535)
            if ($actual -ne [int][char]$Expected[$i]) { throw 'Stored credential content differs.' }
        }
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $Secret.Dispose()
    }
}

if ($ReadOnly) {
    if ($Target -notmatch '^M_Vision/CredentialTest-[a-f0-9]{32}$') { throw 'Invalid test target.' }
    Assert-Secret ([MVision.Security.WindowsCredentialStore]::Read($Target)) ('test-only-key-'+[char]0xE7)
    Write-Host 'PASS: credential persisted across PowerShell processes.'
    exit 0
}

$testTarget = 'M_Vision/CredentialTest-' + [guid]::NewGuid().ToString('N')
$testSecret = $null
try {
    if ($null -ne [MVision.Security.WindowsCredentialStore]::Read($testTarget)) { throw 'Random test target already exists.' }
    $testSecret = ConvertTo-SecureString ('test-only-key-'+[char]0xE7) -AsPlainText -Force
    [MVision.Security.WindowsCredentialStore]::Write($testTarget, $testSecret)
    Assert-Secret ([MVision.Security.WindowsCredentialStore]::Read($testTarget)) ('test-only-key-'+[char]0xE7)
    & powershell.exe -NoProfile -ExecutionPolicy (Get-ExecutionPolicy) -File $PSCommandPath -ReadOnly -Target $testTarget
    if ($LASTEXITCODE -ne 0) { throw 'Cross-process credential test failed.' }
    $testSecret.Dispose()
    $testSecret = ConvertTo-SecureString 'test-only-rotated-key' -AsPlainText -Force
    [MVision.Security.WindowsCredentialStore]::Write($testTarget, $testSecret)
    Assert-Secret ([MVision.Security.WindowsCredentialStore]::Read($testTarget)) 'test-only-rotated-key'
    $blank = New-Object System.Security.SecureString
    $rejected = $false
    try { [MVision.Security.WindowsCredentialStore]::Write($testTarget, $blank) }
    catch { $rejected = $true }
    finally { $blank.Dispose() }
    if (-not $rejected) { throw 'Empty key was not rejected.' }
    Assert-Secret ([MVision.Security.WindowsCredentialStore]::Read($testTarget)) 'test-only-rotated-key'
    if (-not [MVision.Security.WindowsCredentialStore]::Delete($testTarget)) { throw 'Test credential removal failed.' }
    if ($null -ne [MVision.Security.WindowsCredentialStore]::Read($testTarget)) { throw 'Test credential remains after removal.' }
    Write-Host 'PASS: secure write, read, rotation, empty-key rejection and test-target cleanup.'
} finally {
    if ($null -ne $testSecret) { $testSecret.Dispose() }
    [void][MVision.Security.WindowsCredentialStore]::Delete($testTarget)
}
