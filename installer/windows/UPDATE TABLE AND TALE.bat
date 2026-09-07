@echo off
title Table and Tale v3.2.2 Public Sharing Update
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -NoExit -File ""%CD%\UPDATE.ps1""'"
