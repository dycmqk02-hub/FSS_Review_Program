@echo off
chcp 65001 >nul
REM ============================================================
REM  보고서 Review 프로그램 - 로컬 실행 스크립트 (Windows)
REM  처음 실행 시 가상환경(.venv)을 만들고 필요한 패키지를 설치합니다.
REM  두 번째부터는 바로 프로그램이 열립니다.
REM ============================================================
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [오류] Python을 찾을 수 없습니다.
    echo   https://www.python.org/downloads/ 에서 Python 3.10 이상을 설치하고
    echo   설치 첫 화면의 "Add python.exe to PATH" 를 반드시 체크하세요.
    pause
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo [오류] Python 3.10 이상이 필요합니다. 현재 버전:
    python --version
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] 가상환경 생성 중... ^(최초 1회^)
    python -m venv .venv
    if errorlevel 1 (
        echo [오류] 가상환경 생성 실패
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import customtkinter, pdfplumber, pypdf, openpyxl" >nul 2>nul
if errorlevel 1 (
    echo [2/2] 패키지 설치 중... ^(최초 1회, 인터넷 필요^)
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install customtkinter pypdf pdfplumber openpyxl
    if errorlevel 1 (
        echo [오류] 패키지 설치 실패 - 회사망 프록시/방화벽을 확인하세요.
        pause
        exit /b 1
    )
)

echo 프로그램을 실행합니다...
".venv\Scripts\python.exe" main.py
if errorlevel 1 (
    echo.
    echo [오류] 프로그램이 비정상 종료되었습니다. 위 메시지를 캡처해 공유해 주세요.
    pause
)
