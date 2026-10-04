@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-personal.ps1"
if errorlevel 1 (echo Startup failed. & pause & exit /b 1)
