@echo off
cd /d "%~dp0"
py -3 server.py
if errorlevel 1 (
  echo Python 3 is needed. Download it from https://www.python.org/downloads/windows/
  pause
)
