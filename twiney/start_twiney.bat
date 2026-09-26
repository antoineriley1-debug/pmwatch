@echo off
REM TWINEY launcher for Windows. Double-click to run. Add --demo via start_demo.bat.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10+ from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)
if not exist config.json (
  copy config.example.json config.json >nul
  echo Created config.json - check the "port" matches TWS: 7497 paper, 7496 live.
)
if not exist plays.json (
  copy plays.example.json plays.json >nul
  echo Created plays.json with PLACEHOLDER plays - edit it with your real PS60 levels.
)
python run_twiney.py %*
pause
