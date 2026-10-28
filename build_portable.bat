@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\fetch_mpv.ps1"
if errorlevel 1 exit /b 1

python -m pip install -q --upgrade pip pyinstaller streamlink
python -m PyInstaller ^
  --noconfirm ^
  --windowed ^
  --name TV-Win ^
  --onedir ^
  --clean ^
  --add-binary "player\mpv.exe;player" ^
  --collect-all streamlink ^
  --hidden-import streamlink.plugins.atresplayer ^
  main.py
if errorlevel 1 exit /b 1

mkdir "dist\TV-Win\player" 2>nul
copy /Y "player\mpv.exe" "dist\TV-Win\player\mpv.exe" >nul

echo.
echo Portable: dist\TV-Win\TV-Win.exe
echo.
