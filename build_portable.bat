@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\fetch_mpv.ps1"
if errorlevel 1 exit /b 1

python -m pip install -q --upgrade pip pyinstaller -r requirements.txt
python -m PyInstaller ^
  --noconfirm ^
  --windowed ^
  --name TV-Win ^
  --onedir ^
  --clean ^
  --icon "assets\tv-win.ico" ^
  --add-data "assets;assets" ^
  --add-binary "player\mpv.exe;player" ^
  --collect-all streamlink ^
  --collect-all pystray ^
  --hidden-import streamlink.plugins.atresplayer ^
  --hidden-import PIL ^
  --hidden-import PIL._tkinter_finder ^
  main.py
if errorlevel 1 exit /b 1

mkdir "dist\TV-Win\player" 2>nul
copy /Y "player\mpv.exe" "dist\TV-Win\player\mpv.exe" >nul
mkdir "dist\TV-Win\assets" 2>nul
xcopy /E /I /Y "assets\*" "dist\TV-Win\assets\" >nul
python -c "from tvwin import __version__; open(r'dist/TV-Win/version.txt','w',encoding='utf-8').write(__version__)"

echo.
echo Portable: dist\TV-Win\TV-Win.exe
echo.
