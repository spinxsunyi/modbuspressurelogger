@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller==6.19.0
if errorlevel 1 goto fail
.venv\Scripts\python seed_demo.py
if errorlevel 1 goto fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --onedir --name DigitalPressureRecorder --collect-all matplotlib app.py
if errorlevel 1 goto fail
copy README.md dist\DigitalPressureRecorder\README.md
xcopy data dist\DigitalPressureRecorder\data\ /E /I /Y
powershell -NoProfile -Command "Compress-Archive -Path dist\DigitalPressureRecorder -DestinationPath DigitalPressureRecorder-Windows-portable.zip -Force"
echo Done: DigitalPressureRecorder-Windows-portable.zip
pause
exit /b 0
:fail
echo Build failed. Check the error above. Build machine needs Python 3.12 and internet.
pause
exit /b 1
