# Input tests use fake clipboard and terminal functions, never the real clipboard.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../scripts/windows-credentials.ps1')

function Get-Clipboard {
    [CmdletBinding()]
    param([switch]$Raw)
    if (-not $Raw) { throw 'Clipboard must be read as raw text.' }
    return $script:testClipboard
}

function Read-Host {
    param([string]$Prompt, [switch]$AsSecureString)
    if (-not $AsSecureString) { throw 'Terminal input must be hidden.' }
    return ConvertTo-SecureString -String $script:testInput -AsPlainText -Force
}

function Assert-Input([System.Security.SecureString]$Secret, [string]$Expected) {
    try {
        if ([System.Net.NetworkCredential]::new('', $Secret).Password -cne $Expected) {
            throw 'Input content differs.'
        }
    } finally { $Secret.Dispose() }
}

$script:testClipboard = 'test-only-clipboard-key'
Assert-Input (Read-MVisionApiKey -FromClipboard) $script:testClipboard
$script:testInput = 'test-only-terminal-key'
Assert-Input (Read-MVisionApiKey) $script:testInput
$script:testInput = [string][char]22
$rejected = $false
try { Read-MVisionApiKey | Out-Null }
catch {
    $rejected = $_.Exception.Message -like '*Ctrl+V*-Clipboard*'
}
if (-not $rejected) { throw 'Ctrl+V input did not produce actionable guidance.' }
$script:testClipboard = " `t`r`n"
$rejected = $false
try { Read-MVisionApiKey -FromClipboard | Out-Null }
catch { $rejected = $_.Exception.Message -like '*vazia*' }
if (-not $rejected) { throw 'Blank clipboard was not rejected.' }
Write-Host 'PASS: hidden input, direct clipboard input, blank rejection and Ctrl+V guidance.'
