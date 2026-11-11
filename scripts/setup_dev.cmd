@echo off
REM Windows launcher for setup_dev.ps1 that bypasses a Restricted execution policy.
REM Does not activate .venv in the caller; for that, after a one-time:
REM   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
REM run:  . .\scripts\setup_dev.ps1
setlocal
where pwsh >nul 2>&1
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_dev.ps1" %*
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_dev.ps1" %*
)
exit /b %ERRORLEVEL%
