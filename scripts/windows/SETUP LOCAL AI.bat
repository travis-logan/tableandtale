@echo off
title Table and Tale Local AI Beta Setup
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%CD%\SETUP-LOCAL-AI.ps1"
