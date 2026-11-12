[CmdletBinding(DefaultParameterSetName='Save')]
param(
    [Parameter(ParameterSetName='Status')][switch]$Status,
    [Parameter(ParameterSetName='Remove')][switch]$Remove
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts/windows-credentials.ps1')
$credentialTarget = 'M_Vision/AISStream'
$aisSecret = $null
try {
    if ($Status) {
        $aisSecret = [MVision.Security.WindowsCredentialStore]::Read($credentialTarget)
        if ($null -eq $aisSecret) {
            Write-Host 'Nenhuma chave AISStream salva para este usuario do Windows.'
        } else {
            Write-Host 'Chave AISStream salva no Gerenciador de Credenciais do Windows. Valor oculto.'
        }
    } elseif ($Remove) {
        $removed = [MVision.Security.WindowsCredentialStore]::Delete($credentialTarget)
        if ($removed) { Write-Host 'Chave AISStream removida do armazenamento local.' }
        else { Write-Host 'Nenhuma chave AISStream estava salva.' }
    } else {
        $aisSecret = Read-Host 'Nova chave AISStream (entrada oculta)' -AsSecureString
        [MVision.Security.WindowsCredentialStore]::Write($credentialTarget, $aisSecret)
        Write-Host 'Chave salva no Gerenciador de Credenciais do Windows, fora do projeto e do Git.'
        Write-Host 'Para iniciar o M Vision: .\start-aisstream.ps1'
    }
} finally {
    if ($null -ne $aisSecret) { $aisSecret.Dispose() }
}
