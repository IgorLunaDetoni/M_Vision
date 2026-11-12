$ErrorActionPreference = 'Stop'
$previousSource = $env:VESSEL_SOURCE
$previousKey = $env:AISSTREAM_API_KEY
$aisSecret = $null
try {
    $env:VESSEL_SOURCE = 'aisstream'
    if ([string]::IsNullOrWhiteSpace($env:AISSTREAM_API_KEY)) {
        . (Join-Path $PSScriptRoot 'scripts/windows-credentials.ps1')
        $aisSecret = [MVision.Security.WindowsCredentialStore]::Read('M_Vision/AISStream')
        if ($null -eq $aisSecret) {
            $aisSecret = Read-MVisionApiKey -Prompt 'Chave AISStream para salvar no Windows (entrada oculta)'
            [MVision.Security.WindowsCredentialStore]::Write('M_Vision/AISStream', $aisSecret)
            $aisSecret.Dispose()
            $aisSecret = [MVision.Security.WindowsCredentialStore]::Read('M_Vision/AISStream')
            Write-Host 'Chave salva no Gerenciador de Credenciais do Windows.'
        } else {
            Write-Host 'Usando a chave salva no Gerenciador de Credenciais do Windows.'
        }
        $env:AISSTREAM_API_KEY = [System.Net.NetworkCredential]::new('', $aisSecret).Password
        if ([string]::IsNullOrWhiteSpace($env:AISSTREAM_API_KEY)) {
            throw 'Informe uma chave criada em https://aisstream.io/.'
        }
    }
    Write-Host 'Iniciando coleta AISStream. Area padrao: Brasil e aguas proximas.'
    & (Join-Path $PSScriptRoot 'start.ps1')
    $appExitCode = $LASTEXITCODE
} finally {
    $env:VESSEL_SOURCE = $previousSource
    $env:AISSTREAM_API_KEY = $previousKey
    if ($null -ne $aisSecret) { $aisSecret.Dispose() }
}
exit $appExitCode
