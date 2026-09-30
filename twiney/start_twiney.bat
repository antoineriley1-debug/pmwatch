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
  python -c "import json;json.dump({'plays':[{'symbol':s,'watch':True} for s in ('SPY','QQQ','AAPL','NVDA','TSLA','AMD')]},open('plays.json','w'),indent=2)"
  echo Created a blank plays.json - type tickers into the desk and draw your own stop, target and 2nd entry.
)
python -c "import PIL" >nul 2>nul || python -m pip install -q pillow >nul 2>nul
python run_twiney.py %*
pause
