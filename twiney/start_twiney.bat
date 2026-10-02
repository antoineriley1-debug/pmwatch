@echo off
REM TWINEY launcher for Windows. Double-click to run. Add --demo via start_demo.bat.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10+ from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)
REM your settings, key, plays and layout live in C:\Users\<you>\TWINEY - a new build never touches them
python -c "import PIL" >nul 2>nul || python -m pip install -q pillow >nul 2>nul
python run_twiney.py %*
pause
