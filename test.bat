@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pytest
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
