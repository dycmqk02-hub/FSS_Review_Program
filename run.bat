@echo off
REM ============================================================
REM  FSS Review Program - local launcher for Windows
REM  First run: creates a virtual environment (.venv) and installs
REM  the required packages. Later runs start the program directly.
REM
REM  NOTE: keep this file ASCII-only with CRLF line endings.
REM  cmd.exe misreads UTF-8 (Korean) text and LF-only line endings
REM  in batch files and splits commands into garbage.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "VENV_PY=.venv\Scripts\python.exe"

REM ---- 1. Find Python 3.10+ (py launcher first, then python) ----
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto have_python

echo [ERROR] Python 3.10 or newer was not found.
echo   Install Python from https://www.python.org/downloads/
echo   and check "Add python.exe to PATH" on the first installer screen.
echo   If Python is installed, turn off the "App execution aliases"
echo   for python.exe in Windows Settings and run this file again.
goto fail

:have_python
echo Using Python:
%PY% --version

REM ---- 2. tkinter is required for the GUI ----
%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] tkinter is missing from this Python installation.
    echo   Re-run the Python installer, choose Modify, and enable
    echo   "tcl/tk and IDLE", then run this file again.
    goto fail
)

REM ---- 3. Create or repair the virtual environment ----
if exist "%VENV_PY%" (
    "%VENV_PY%" -m pip --version >nul 2>nul
    if errorlevel 1 (
        echo Existing .venv is broken. Recreating it...
        rmdir /s /q .venv
    )
)
if not exist "%VENV_PY%" (
    echo [1/2] Creating virtual environment - first run only...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        goto fail
    )
)

REM ---- 4. Install packages if any are missing ----
"%VENV_PY%" -c "import customtkinter, pdfplumber, pypdf, openpyxl" >nul 2>nul
if not errorlevel 1 goto start_app

echo [2/2] Installing packages - first run only, internet required...
REM Upgrading pip is optional; continue even if it fails.
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 echo [WARN] pip upgrade failed - continuing with the current pip.

"%VENV_PY%" -m pip install "customtkinter>=5.2.2" "pypdf>=4.0.0" "pdfplumber>=0.11.0" "openpyxl>=3.1.0"
if errorlevel 1 (
    echo.
    echo [ERROR] Package installation failed.
    echo   - On a company network, check the proxy or firewall settings.
    echo   - Delete the .venv folder and run this file again.
    echo   - Capture the messages above and share them.
    goto fail
)

"%VENV_PY%" -c "import customtkinter, pdfplumber, pypdf, openpyxl"
if errorlevel 1 (
    echo [ERROR] Packages were installed but could not be imported.
    goto fail
)

:start_app
echo Starting the program...
"%VENV_PY%" main.py
if errorlevel 1 (
    echo.
    echo [ERROR] The program exited with an error.
    echo   Capture the messages above and share them.
    goto fail
)
endlocal
exit /b 0

:fail
echo.
pause
endlocal
exit /b 1
