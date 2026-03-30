@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "UI_SCRIPT=%SCRIPT_DIR%pc_server_setup_ui.py"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 "%UI_SCRIPT%"
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python "%UI_SCRIPT%"
    exit /b %ERRORLEVEL%
)

echo Python 3.11+ was not found.
echo Install Python or build the packaged EXE with scripts\build-pc-setup-ui.ps1
pause
exit /b 1
