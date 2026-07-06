@echo off
setlocal enabledelayedexpansion
title XDRabbit Setup
color 0A

echo ================================================
echo    XDRabbit Automated Setup
echo ================================================
echo.

REM ── Check Admin privileges ──────────────────────
net session >nul 2>&1
if errorlevel 1 (
    echo ✗ Please run this script as Administrator.
    echo   Right-click setup.bat → Run as administrator
    pause
    exit /b 1
)


REM ════════════════════════════════════════════════
REM   STEP 1 — Install Python 3.14.3
REM ════════════════════════════════════════════════
echo [1/6] Checking Python 3.14.3...
python --version 2>&1 | findstr "3.14.3" >nul
if errorlevel 1 (
    echo → Python 3.14.3 not found. Downloading...
    curl -o python_installer.exe https://www.python.org/ftp/python/3.14.3/python-3.14.3-amd64.exe
    if errorlevel 1 (
        echo ✗ Failed to download Python installer.
        pause
        exit /b 1
    )
    echo → Installing Python 3.14.3...
    python_installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
    del python_installer.exe
    echo ✓ Python 3.14.3 installed.
) else (
    python --version
    echo ✓ Python 3.14.3 already installed.
)
echo.


REM ════════════════════════════════════════════════
REM   STEP 2 — Install Node.js v24.14.0
REM ════════════════════════════════════════════════
echo [2/6] Checking Node.js v24.14.0...
node --version 2>&1 | findstr "v24.14.0" >nul
if errorlevel 1 (
    echo → Node.js v24.14.0 not found. Downloading...
    curl -o node_installer.msi https://nodejs.org/dist/v24.14.0/node-v24.14.0-x64.msi
    if errorlevel 1 (
        echo ✗ Failed to download Node.js installer.
        pause
        exit /b 1
    )
    echo → Installing Node.js v24.14.0...
    msiexec /i node_installer.msi /quiet /norestart
    del node_installer.msi
    echo ✓ Node.js v24.14.0 installed.
) else (
    node --version
    echo ✓ Node.js v24.14.0 already installed.
)
echo.


REM ════════════════════════════════════════════════
REM   STEP 3 — Install Appium + UiAutomator2
REM ════════════════════════════════════════════════
echo [3/6] Checking Appium...
appium --version >nul 2>&1
if errorlevel 1 (
    echo → Installing Appium...
    call npm install -g appium
    if errorlevel 1 (
        echo ✗ Failed to install Appium.
        pause
        exit /b 1
    )
    echo ✓ Appium installed.
) else (
    appium --version
    echo ✓ Appium already installed.
)

echo → Installing UiAutomator2 driver v7.0.0...
call appium driver install uiautomator2@7.0.0
if errorlevel 1 (
    echo ✗ Failed to install UiAutomator2 driver.
    pause
    exit /b 1
)
echo ✓ UiAutomator2@7.0.0 installed.
echo.


REM ════════════════════════════════════════════════
REM   STEP 4 — Setup Android folder to C:\Android
REM ════════════════════════════════════════════════
echo [4/6] Setting up Android SDK...
if exist Android (
    echo → Android folder found in project.
    if exist C:\Android (
        echo → C:\Android already exists. Replacing...
        rmdir /s /q C:\Android
    )
    echo → Copying Android folder to C:\Android...
    xcopy /e /i /q Android C:\Android
    if errorlevel 1 (
        echo ✗ Failed to copy Android folder.
        pause
        exit /b 1
    )
    echo ✓ Android SDK copied to C:\Android.
) else (
    echo ✗ Android folder not found in project directory.
    echo   Make sure Android folder is in the same directory as setup.bat.
    pause
    exit /b 1
)

REM ── Add ADB to PATH ─────────────────────────────
echo → Adding ADB to PATH...
setx PATH "%PATH%;C:\Android\platform-tools" /M
set PATH=%PATH%;C:\Android\platform-tools

REM ── Add Android SDK to ANDROID_HOME ─────────────
setx ANDROID_HOME "C:\Android" /M
set ANDROID_HOME=C:\Android

echo ✓ ADB added to PATH.
echo ✓ ANDROID_HOME set to C:\Android.

REM ── Verify ADB ──────────────────────────────────
adb --version >nul 2>&1
if errorlevel 1 (
    echo ⚠ ADB not detected yet. May need to restart terminal.
) else (
    echo ✓ ADB verified.
)
echo.


REM ════════════════════════════════════════════════
REM   STEP 5 — Install Python dependencies
REM ════════════════════════════════════════════════
echo [5/6] Installing Python dependencies...
pip install appium-python-client==5.3.0
if errorlevel 1 (
    echo ✗ Failed to install appium-python-client.
    pause
    exit /b 1
)
echo ✓ appium-python-client==5.3.0 installed.

pip install python-dotenv==1.2.2
if errorlevel 1 (
    echo ✗ Failed to install python-dotenv.
    pause
    exit /b 1
)
echo ✓ python-dotenv==1.2.2 installed.
echo.


REM ════════════════════════════════════════════════
REM   STEP 6 — Setup .env file
REM ════════════════════════════════════════════════
echo [6/6] Setting up .env file...
if exist .env (
    echo ✓ .env file already exists. Skipping.
) else (
    if exist .env.example (
        copy .env.example .env >nul
        echo ✓ .env created from .env.example.
        echo ⚠ Please fill in your .env values before running.
    ) else (
        echo → Creating default .env file...
        (
            echo WEBDRIVER_URL=http://localhost:4723
            echo APP_PACKAGE=com.view.ytrabbit
            echo APP_MAIN_ACTIVITY=com.view.ytrabbit.MainActivity
            echo NEW_COMMAND_TIMEOUT=300
            echo SKIP_TIME_VALUE=0
        ) > .env
        echo ✓ Default .env file created.
        echo ⚠ Please fill in your .env values before running.
    )
)
echo.


REM ════════════════════════════════════════════════
REM   VERIFY INSTALLATIONS
REM ════════════════════════════════════════════════
echo ================================================
echo    🔍  Verifying Installations
echo ================================================
echo.
echo Python:
python --version
echo.
echo Node.js:
node --version
echo.
echo NPM:
npm --version
echo.
echo Appium:
appium --version
echo.
echo ADB:
adb --version
echo.
echo ANDROID_HOME:
echo %ANDROID_HOME%
echo.
echo Python packages:
pip show appium-python-client | findstr "Version"
pip show python-dotenv | findstr "Version"
echo.


REM ════════════════════════════════════════════════
REM   DONE
REM ════════════════════════════════════════════════
echo ================================================
echo    ✓  Setup Complete!
echo ================================================
echo.
echo Next steps:
echo   1. Open .env and fill in your values
echo   2. Start LDPlayer emulators
echo   3. Double click start.bat to run the script
echo.
pause
