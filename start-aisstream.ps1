$ErrorActionPreference = 'Stop'
$previousSource = $env:VESSEL_SOURCE
$previousKey = $env:AISSTREAM_API_KEY
try {
    $env:VESSEL_SOURCE = 'aisstream'
    if ([string]::IsNullOrWhiteSpace($env:AISSTREAM_API_KEY)) {
        $aisSecret = Read-Host 'Chave da API AISStream (entrada oculta)' -AsSecureString
        $env:AISSTREAM_API_KEY = [System.Net.NetworkCredential]::new('', $aisSecret).Password
        if ([string]::IsNullOrWhiteSpace($env:AISSTREAM_API_KEY)) {
            throw 'Informe uma chave criada em https://aisstream.io/.'
        }
    }
    Write-Host 'Iniciando coleta AISStream. Area padrao: Brasil e aguas proximas.'
    & powershell.exe -NoProfile -File (Join-Path $PSScriptRoot 'start.ps1')
} finally {
    $env:VESSEL_SOURCE = $previousSource
    $env:AISSTREAM_API_KEY = $previousKey
    if ($null -ne $aisSecret) { $aisSecret.Dispose() }
}
