@echo off
setlocal
cd /d "%~dp0"
echo Iniciando M Vision e coleta AISStream no computador...
echo Acesse http://127.0.0.1:8000 quando o servidor estiver pronto.
echo Para encerrar, pressione Ctrl+C nesta janela.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-aisstream.ps1"
set "MVISION_EXIT_CODE=%ERRORLEVEL%"
if not "%MVISION_EXIT_CODE%"=="0" (
    echo.
    echo Nao foi possivel concluir a execucao. Confira a mensagem acima.
    pause
)
exit /b %MVISION_EXIT_CODE%
