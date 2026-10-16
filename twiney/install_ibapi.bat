@echo off
REM Installs IBKR's official TWS API Python package after you've run IBKR's TWS API installer.
set "SRC=C:\TWS API\source\pythonclient"
if not exist "%SRC%\setup.py" if not exist "%SRC%\pyproject.toml" (
  echo Could not find "%SRC%".
  echo Run IBKR's TWS API installer first: https://interactivebrokers.github.io/
  pause
  exit /b 1
)
pushd "%SRC%"
python -m pip install .
popd
REM screenshots (P key) need Pillow
python -m pip install pillow
python -c "import ibapi; print(); print('ibapi installed OK - you can now double-click start_twiney')"
if errorlevel 1 echo Install FAILED - send a photo of this window.
pause
