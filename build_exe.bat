@echo off
REM ============================================================
REM  FSS Review Program - PyInstaller EXE build script
REM  Output: dist\FSS_ReviewProgram.exe
REM
REM  NOTE: keep this file ASCII-only with CRLF line endings.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "VENV_PY=.venv\Scripts\python.exe"

REM ---- Find Python 3.10+ (py launcher first, then python) ----
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto have_python
echo [ERROR] Python 3.10 or newer was not found.
goto fail

:have_python
if exist "%VENV_PY%" (
    "%VENV_PY%" -m pip --version >nul 2>nul
    if errorlevel 1 (
        echo Existing .venv is broken. Recreating it...
        rmdir /s /q .venv
    )
)
if not exist "%VENV_PY%" (
    echo [1/4] Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 goto fail
)

echo [2/4] Installing packages...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 echo [WARN] pip upgrade failed - continuing with the current pip.
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Package installation failed.
    goto fail
)

echo [3/4] Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist FSS_ReviewProgram.spec del /q FSS_ReviewProgram.spec

echo [4/4] Building with PyInstaller...
"%VENV_PY%" -m PyInstaller --noconfirm --onefile --windowed ^
    --name FSS_ReviewProgram ^
    --collect-all customtkinter ^
    --collect-all pdfplumber ^
    --collect-all pdfminer ^
    --collect-all pypdfium2 ^
    main.py
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed - check the messages above.
    goto fail
)

echo.
echo Build complete: dist\FSS_ReviewProgram.exe
pause
endlocal
exit /b 0

:fail
echo.
pause
endlocal
exit /b 1
