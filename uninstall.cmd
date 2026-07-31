@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PREFIX=%LOCALAPPDATA%\Programs\imr-sqliblind"
set "NO_PATH=0"

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--prefix" (
  if "%~2"=="" (
    echo [x] --prefix requires a path 1>&2
    exit /b 2
  )
  set "PREFIX=%~f2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--no-path" (
  set "NO_PATH=1"
  shift
  goto parse_args
)
if /I "%~1"=="--help" goto usage
if /I "%~1"=="-h" goto usage
echo [x] Unknown option: %~1 1>&2
exit /b 2

:usage
echo Usage: uninstall.cmd [--prefix PATH] [--no-path]
exit /b 0

:args_done
set "BIN_DIR=%PREFIX%\bin"
if exist "%PREFIX%\install.env" (
  for /f "usebackq tokens=1,* delims==" %%A in ("%PREFIX%\install.env") do (
    if /I "%%A"=="SQLIBLIND_BIN" set "BIN_DIR=%%B"
  )
)

if "%NO_PATH%"=="0" (
  set "SQLIBLIND_ENV_BIN=%BIN_DIR%"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$bin=$env:SQLIBLIND_ENV_BIN; $current=[Environment]::GetEnvironmentVariable('Path','User'); $items=@(); if($current){$items=$current.Split(';') ^| Where-Object { $_ -and $_.TrimEnd('\') -ine $bin.TrimEnd('\') }}; [Environment]::SetEnvironmentVariable('Path',($items -join ';'),'User'); [Environment]::SetEnvironmentVariable('IMR_SQLIBLIND_HOME',$null,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_PYTHON',$null,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_BIN',$null,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_COMMAND',$null,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_NATIVE_COMMAND',$null,'User')" || exit /b 1
)

if exist "%BIN_DIR%\sqliblind.cmd" del /q "%BIN_DIR%\sqliblind.cmd"
if exist "%PREFIX%" rmdir /s /q "%PREFIX%"
echo imr-sqliblind was removed. Open a new CMD window to refresh PATH.
exit /b 0
