@echo off
title IBVAP - Instant GitHub Push
cls
echo ===================================================
echo             IBVAP Instant GitHub Push
echo ===================================================
set /p msg="Enter commit message (Press Enter for auto-timestamp): "
if "%msg%"=="" (
    for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
    set msg=Manual Sync: %date% %time%
)

echo.
echo Staging files...
git add .

echo Committing...
git commit -m "%msg%"

echo Pushing to GitHub (origin main)...
git push origin main

echo.
if %ERRORLEVEL% equ 0 (
    echo ===================================================
    echo    SUCCESS: Pushed to https://github.com/kunalvish08/IBVAP
    echo ===================================================
) else (
    echo ===================================================
    echo    FAILED: Check network connection or git credentials.
    echo ===================================================
)
echo.
pause
