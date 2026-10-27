@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller==6.19.0
if errorlevel 1 goto fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --onedir --name PMSLogger --collect-all matplotlib app.py
if errorlevel 1 goto fail
copy README.md dist\PMSLogger\README.md
xcopy data dist\PMSLogger\data\ /E /I /Y
powershell -NoProfile -Command "Compress-Archive -Path dist\PMSLogger -DestinationPath PMSLogger-Windows-portable.zip -Force"
echo Done: PMSLogger-Windows-portable.zip
pause
exit /b 0
:fail
echo Build failed. Check the error above. Build machine needs Python 3.12 and internet.
pause
exit /b 1
