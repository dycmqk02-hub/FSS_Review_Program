@echo off
REM 반기검토 사전리뷰 프로그램 - PyInstaller EXE 빌드 스크립트
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
    --collect-all xlrd ^
    --add-data "resources;resources" ^
    main.py
if errorlevel 1 (
    echo.
    echo 빌드 실패 - 위 오류 메시지를 확인하세요.
    pause
    exit /b 1
)

REM secrets.json(API 키)은 dist 폴더를 통째로 지우고 다시 만들 때 함께 삭제되므로,
REM 빌드 후 프로젝트 루트에 있는 secrets.json을 dist로 복사해 계속 유지되게 한다.
if exist "secrets.json" copy /y "secrets.json" "dist\secrets.json" >nul

echo.
echo 빌드 완료: dist\FSS_ReviewProgram.exe
pause
