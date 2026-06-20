@echo off
cd /d "%~dp0"
chcp 65001 >nul
title MindMargin YouTube Auth

echo ================================
echo  MindMargin - YouTube OAuth Setup
echo ================================
echo.

:: --- Search for Python ---
set PYTHON_CMD=
where python 2>nul | findstr /v WindowsApps >nul
if %errorlevel% equ 0 (
    for /f "tokens=*" %%a in ('where python') do (
        echo %%a | findstr /v WindowsApps >nul
        if not errorlevel 1 (
            set "PYTHON_CMD=%%a"
            goto :found
        )
    )
)

for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "C:\Program Files\Python314\python.exe"
) do (
    if exist %%p (
        set "PYTHON_CMD=%%p"
        goto :found
    )
)

set "PYTHON_CMD=C:\Users\A Center\AppData\Local\Programs\Python\Python314\python.exe"
if not exist "%PYTHON_CMD%" (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)

:found
echo [OK] Python: %PYTHON_CMD%
"%PYTHON_CMD%" --version
echo.

:: --- Verify client_secrets.json ---
if not exist "client_secrets.json" (
    echo [ERROR] client_secrets.json not found.
    pause
    exit /b 1
)
echo [OK] client_secrets.json found
echo.

:: --- Run OAuth ---
echo [INFO] Running OAuth...
echo.
"%PYTHON_CMD%" auth.py

echo.
if %errorlevel% equ 0 (
    echo [OK] Done.
) else (
    echo [WARN] Check messages above.
)
pause
