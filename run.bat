@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" agent.py --run-now
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: agent exited with code %ERRORLEVEL%
    echo Check agent.log for details.
    pause
)
