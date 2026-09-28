@echo off
REM Replay a recorded session in the dashboard with play / pause / speed controls.
cd /d "%~dp0"
if not exist recordings\*.jsonl (
  echo No recordings yet. Recordings are written to the recordings folder every live session.
  pause
  exit /b 1
)
echo Recordings (newest last):
dir /b /o:d recordings\*.jsonl
echo.
set /p F=Type the file name to replay (or press Enter for the newest): 
if "%F%"=="" for /f "delims=" %%i in ('dir /b /o:d recordings\*.jsonl') do set F=%%i
python run_twiney.py --replay "recordings\%F%" --speed 5
pause
