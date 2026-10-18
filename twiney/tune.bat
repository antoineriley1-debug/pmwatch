@echo off
REM Tune reload thresholds against the calls you graded (thumbs up / down on the dashboard).
cd /d "%~dp0"
echo Recordings (newest last):
dir /b /o:d recordings\*.jsonl | findstr /v grades
set /p F=Type the recording file name (Enter = newest): 
if "%F%"=="" for /f "delims=" %%i in ('dir /b /o:d recordings\*.jsonl ^| findstr /v grades') do set F=%%i
python tune.py "recordings\%F%"
pause
