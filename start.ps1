$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython app.py
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    python app.py
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 app.py
} elseif (Test-Path -LiteralPath $bundledPython) {
    & $bundledPython app.py
} else {
    Write-Error 'Instale Python 3.10 ou superior e execute novamente.'
}
exit $LASTEXITCODE

