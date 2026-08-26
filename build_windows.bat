@echo off
REM Build a Windows executable for server/app.py using PyInstaller.
REM Run from the repo root on Windows (or under Wine) with Python installed.

pip install -r server\requirements-build.txt || goto :error
pyinstaller server.spec --noconfirm || goto :error

echo.
echo Build complete: dist\pressure-server\pressure-server.exe
goto :eof

:error
echo Build failed.
exit /b 1
