@echo off
:: ════════════════════════════════════════════════════════════════════════════
::  FredAI — Windows 10/11 Installer
::  Double-click this file to install FredAI
::  Requirements: Windows 10 v1809+ or Windows 11 (PowerShell 5.1 built-in)
:: ════════════════════════════════════════════════════════════════════════════
title FredAI Installer

echo.
echo ========================================
echo   FredAI Financial Intelligence
echo   Windows Installer
echo ========================================
echo.

:: Check Windows version (need 10+)
for /f "tokens=4-5 delims=. " %%i in ('ver') do (
    if %%i LSS 10 (
        echo ERROR: Windows 10 or later required.
        pause
        exit /b 1
    )
)

:: Request admin rights if not already elevated
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c %~f0' -Verb RunAs"
    exit /b
)

:: Run the PowerShell installer
echo Launching PowerShell installer...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"

if %errorLevel% neq 0 (
    echo.
    echo Installation encountered an error.
    echo Check the output above for details.
    pause
    exit /b 1
)

pause
