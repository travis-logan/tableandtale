@echo off
setlocal
cd /d "%~dp0"
title Table ^& Tale Installer v3.2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0LAUNCHER.ps1"
endlocal
