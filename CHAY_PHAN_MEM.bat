@echo off
REM Bam dup file nay la chay. Khong can biet terminal.
chcp 65001 >nul
cd /d "%~dp0"
title Tro ly video

echo ==================================================================
echo   TRO LY VIDEO - dang chuan bi (lan dau se lau, vai phut)
echo ==================================================================
echo.

where python >/dev/null 2>nul
if errorlevel 1 (
  echo   [X] CHUA CAI PYTHON
  echo.
  echo   Tai o: https://www.python.org/downloads/
  echo   Khi cai NHO TICH o "Add Python to PATH"
  echo.
  pause
  exit /b 1
)

if not exist ".venv" (
  echo   Tao moi truong Python rieng...
  python -m venv .venv || goto :fail
)

echo   Cai thu vien...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :fail

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo   Da tao file .env. Mo no ra dien GEMINI_API_KEY vao.
  echo   Lay key mien phi: https://aistudio.google.com/apikey
  echo.
  notepad .env
)

echo.
".venv\Scripts\python.exe" run.py
pause
exit /b 0

:fail
echo.
echo   [X] Cai dat that bai. Chay lenh nay de biet vi sao:
echo       .venv\Scripts\python.exe doctor.py
echo.
pause
exit /b 1
