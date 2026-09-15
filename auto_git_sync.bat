@echo off
title IBVAP - GitHub Live Auto Sync
cls
echo ===================================================
echo     Starting IBVAP Live Auto-Sync to GitHub
echo ===================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0auto_git_sync.ps1"
pause
