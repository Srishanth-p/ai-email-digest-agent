@echo off
cd /d "C:\Users\srish\OneDrive\Desktop\Email Agent"
".venv\Scripts\python.exe" agent.py --run-now
if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: agent exited with code %ERRORLEVEL%
    echo Check agent.log for details.
    pause
)
