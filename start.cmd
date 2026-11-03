@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
    exit /b
)
where python >nul 2>&1
if not errorlevel 1 (
    python app.py
    exit /b
)
where py >nul 2>&1
if not errorlevel 1 (
    py -3 app.py
    exit /b
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
    "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" app.py
    exit /b
)
echo Instale Python 3.10 ou superior e execute novamente.
exit /b 1
