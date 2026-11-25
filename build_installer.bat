@echo off
rem Builds standalone dist\iPhoneMirror\iPhoneMirror.exe and dist\iPhoneMirror-Setup.exe.
setlocal
set "PY=%LOCALAPPDATA%\iPhoneMirror\venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Run install.bat first to create %LOCALAPPDATA%\iPhoneMirror\venv.
  exit /b 1
)
pushd "%~dp0"
"%PY%" packaging\build.py
set "CODE=%ERRORLEVEL%"
popd
exit /b %CODE%
