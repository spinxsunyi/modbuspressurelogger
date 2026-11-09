@echo off
setlocal
cd /d "%~dp0"

py -3.12 -m venv .venv
if errorlevel 1 goto fail
.venv\Scripts\python -m pip install -r requirements.txt pyinstaller==6.19.0
if errorlevel 1 goto fail

rem Never include local recordings, settings, or lock files in a distributable.
rem Remove stale output so prior data folders cannot survive a rebuild.
if exist "dist\DigitalPressureRecorder" rmdir /s /q "dist\DigitalPressureRecorder"
if exist "dist\DigitalPressureRecorder" goto fail

.venv\Scripts\python -c "from app_icon import export_windows_icon; export_windows_icon('assets/pressure_gauge.ico')"
if errorlevel 1 goto fail
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed --onedir --name DigitalPressureRecorder --icon assets/pressure_gauge.ico --collect-all matplotlib --add-data "assets/pms970p.jpg;assets" app.py
if errorlevel 1 goto fail

copy /Y README.md "dist\DigitalPressureRecorder\README.md"
if errorlevel 1 goto fail
if exist "dist\DigitalPressureRecorder\data" (
    echo ERROR: data folder must not be present in the release package.
    goto fail
)

rem A locked build dependency can make Compress-Archive fail. Check exit status.
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Compress-Archive -Path 'dist\DigitalPressureRecorder' -DestinationPath 'DigitalPressureRecorder-Windows-portable.zip' -Force"
if errorlevel 1 goto fail

echo.
echo Build succeeded: DigitalPressureRecorder-Windows-portable.zip
pause
exit /b 0

:fail
echo.
echo Build failed. Check the error above. Close any running app before retrying.
pause
exit /b 1
