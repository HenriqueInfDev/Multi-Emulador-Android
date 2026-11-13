@echo off
REM Gera dist\AndroidEmulatorManager\AndroidEmulatorManager.exe
cd /d "%~dp0"
REM Procura um Python que funcione (o "python" da Microsoft Store e so um atalho)
set PY=
if exist "%LOCALAPPDATA%\Python\bin\python3.exe" set PY="%LOCALAPPDATA%\Python\bin\python3.exe"
if not defined PY ( py -3 -c "import sys" >nul 2>nul && set PY=py -3 )
if not defined PY ( python -c "import sys" >nul 2>nul && set PY=python )
if not defined PY (
  echo Python 3 nao encontrado. Instale em https://www.python.org/downloads/
  goto :erro
)
%PY% -m pip install -r requirements.txt --quiet || goto :erro
%PY% make_icon.py || goto :erro
%PY% -m PyInstaller --noconfirm --clean --windowed --name AndroidEmulatorManager ^
  --icon assets\app.ico ^
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.Qt3DCore --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtMultimedia --exclude-module PySide6.QtCharts ^
  --exclude-module PySide6.QtDataVisualization --exclude-module PySide6.QtPdf --exclude-module tkinter ^
  main.py || goto :erro
echo.
echo Pronto: dist\AndroidEmulatorManager\AndroidEmulatorManager.exe
exit /b 0
:erro
echo Falha no build.
exit /b 1
