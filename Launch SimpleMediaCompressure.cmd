@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
    exit /b
)
where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw "%~dp0main.py"
    exit /b
)
echo Install Python and the dependencies first. See README.md for setup instructions.
pause
