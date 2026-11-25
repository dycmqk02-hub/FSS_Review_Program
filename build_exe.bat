@echo off
chcp 65001 >nul
REM 보고서 Review 프로그램 - PyInstaller EXE 빌드 스크립트 (dist\FSS_ReviewProgram.exe 생성)
setlocal

cd /d "%~dp0"

if not exist ".venv" (
    echo [1/4] 가상환경 생성 중...
    python -m venv .venv
)

echo [2/4] 패키지 설치 중...
call .venv\Scripts\activate.bat
pip install --upgrade pip >nul
pip install -r requirements.txt

echo [3/4] 이전 빌드 정리 중...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /q FSS_ReviewProgram.spec 2>nul

echo [4/4] PyInstaller 빌드 중...
pyinstaller --noconfirm --onefile --windowed ^
    --name FSS_ReviewProgram ^
    --collect-all customtkinter ^
    --collect-all pdfplumber ^
    --collect-all pdfminer ^
    --collect-all pypdfium2 ^
    main.py
if errorlevel 1 (
    echo.
    echo 빌드 실패 - 위 오류 메시지를 확인하세요.
    pause
    exit /b 1
)


echo.
echo 빌드 완료: dist\FSS_ReviewProgram.exe
pause
