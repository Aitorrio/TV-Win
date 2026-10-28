@echo off
setlocal
cd /d "%~dp0"
python -m tvwin
if errorlevel 1 pause
