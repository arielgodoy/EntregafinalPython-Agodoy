@echo off
set "repoRoot=%~dp0.."
set "python=%repoRoot%\venv\Scripts\python.exe"
if not exist "%python%" set "python=%repoRoot%\..\venv\Scripts\python.exe"
set "port=%1"

if "%port%"=="" set "port=8000"

if not exist "%python%" (
    echo Python venv no encontrado en: %python%
    exit /b 1
)

pushd "%repoRoot%"
"%python%" manage.py runserver %port%
popd
