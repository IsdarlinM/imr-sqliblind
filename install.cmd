@echo off
setlocal EnableExtensions

set "APP_NAME=imr-sqliblind"
set "COMMAND_NAME=sqliblind"
set "MANAGED_PYTHON=3.12"
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
set "PREFIX=%LOCALAPPDATA%\Programs\imr-sqliblind"
set "NO_PATH=0"
set "PYTHON_OVERRIDE="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--prefix" (
  if "%~2"=="" goto missing_prefix
  set "PREFIX=%~f2"
  shift
  shift
  goto parse_args
)
if /I "%~1"=="--python" (
  if "%~2"=="" goto missing_python
  set "PYTHON_OVERRIDE=%~f2"
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

:missing_prefix
echo [x] --prefix requires a path 1>&2
exit /b 2

:missing_python
echo [x] --python requires an executable path 1>&2
exit /b 2

:usage
echo Usage: install.cmd [options]
echo.
echo Installs imr-sqliblind and the realtime web console for the current user.
echo.
echo Options:
echo   --prefix PATH     Custom installation directory.
echo   --python PATH     Preferred Python executable ^(must be Python 3.10+^).
echo   --no-path         Do not persist environment variables or modify PATH.
echo   -h, --help        Show this help.
exit /b 0

:args_done
set "BIN_DIR=%PREFIX%\bin"
set "VENV_DIR=%PREFIX%\venv"
set "BOOTSTRAP_DIR=%PREFIX%\bootstrap"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_COMMAND=%VENV_DIR%\Scripts\sqliblind.exe"
set "PYTHON_EXE="
set "PYTHON_ARGS="

if not exist "%PREFIX%" mkdir "%PREFIX%" || goto mkdir_failed

if defined PYTHON_OVERRIDE (
  if not exist "%PYTHON_OVERRIDE%" (
    echo [x] Python executable not found: %PYTHON_OVERRIDE% 1>&2
    exit /b 1
  )
  "%PYTHON_OVERRIDE%" -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,10) else 1)" >nul 2>&1
  if errorlevel 1 (
    echo [x] --python must point to Python 3.10 or newer 1>&2
    exit /b 1
  )
  set "PYTHON_EXE=%PYTHON_OVERRIDE%"
  goto python_ready
)

where py.exe >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PYTHON_EXE=py.exe"
    set "PYTHON_ARGS=-3"
    goto python_ready
  )
)

where python.exe >nul 2>&1
if not errorlevel 1 (
  python.exe -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('where python.exe') do if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
    goto python_ready
  )
)

where python3.exe >nul 2>&1
if not errorlevel 1 (
  python3.exe -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('where python3.exe') do if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
    goto python_ready
  )
)

call :install_uv || exit /b 1
echo [+] Installing managed Python %MANAGED_PYTHON%
"%UV_EXE%" python install %MANAGED_PYTHON% || exit /b 1
set "PYTHON_FILE=%TEMP%\imr-sqliblind-python-%RANDOM%.txt"
"%UV_EXE%" python find %MANAGED_PYTHON% > "%PYTHON_FILE%" || exit /b 1
set /p "PYTHON_EXE=" < "%PYTHON_FILE%"
del /q "%PYTHON_FILE%" >nul 2>&1
if not defined PYTHON_EXE (
  echo [x] uv did not return a Python executable 1>&2
  exit /b 1
)

:python_ready
"%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [x] Unable to locate Python 3.10 or newer 1>&2
  exit /b 1
)
for /f "delims=" %%V in ('"%PYTHON_EXE%" %PYTHON_ARGS% --version 2^>^&1') do echo [+] Using %%V

if exist "%VENV_PYTHON%" (
  "%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info ^>= (3,10) else 1)" >nul 2>&1
  if errorlevel 1 rmdir /s /q "%VENV_DIR%"
)

if not exist "%VENV_PYTHON%" (
  echo [+] Creating isolated environment at %VENV_DIR%
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%" >nul 2>&1
  if errorlevel 1 (
    call :install_uv || exit /b 1
    if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
    "%UV_EXE%" venv --python %MANAGED_PYTHON% "%VENV_DIR%" || exit /b 1
  )
)

if not exist "%VENV_PYTHON%" (
  echo [x] Failed to create the Python environment 1>&2
  exit /b 1
)

echo [+] Installing project dependencies and web console
"%VENV_PYTHON%" -m ensurepip --upgrade >nul 2>&1
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel || exit /b 1
"%VENV_PYTHON%" -m pip install --disable-pip-version-check --upgrade "%PROJECT_ROOT%[web]" || exit /b 1
if not exist "%VENV_COMMAND%" (
  echo [x] Installation completed without creating %VENV_COMMAND% 1>&2
  exit /b 1
)

if not exist "%BIN_DIR%" mkdir "%BIN_DIR%" || goto mkdir_failed
> "%BIN_DIR%\sqliblind.cmd" echo @echo off
>> "%BIN_DIR%\sqliblind.cmd" echo "%VENV_COMMAND%" %%*

> "%PREFIX%\install.env" echo IMR_SQLIBLIND_HOME=%PREFIX%
>> "%PREFIX%\install.env" echo SQLIBLIND_PYTHON=%VENV_PYTHON%
>> "%PREFIX%\install.env" echo SQLIBLIND_BIN=%BIN_DIR%

if "%NO_PATH%"=="0" call :persist_environment || exit /b 1
set "IMR_SQLIBLIND_HOME=%PREFIX%"
set "SQLIBLIND_PYTHON=%VENV_PYTHON%"
set "SQLIBLIND_BIN=%BIN_DIR%"
call :activate_current_environment || exit /b 1

echo [+] Verifying CLI, service config, and web console
call sqliblind --version || exit /b 1
call sqliblind config init >nul || exit /b 1
call sqliblind web --help >nul || exit /b 1
echo.
echo Installation completed.
echo   Home:    %PREFIX%
echo   Python:  %VENV_PYTHON%
echo   Command: %BIN_DIR%\sqliblind.cmd
if "%NO_PATH%"=="0" (
  echo.
  echo PATH and user environment variables were configured automatically.
  echo Open a new CMD or PowerShell window to inherit the persisted PATH.
)
exit /b 0

:install_uv
set "UV_EXE=%BOOTSTRAP_DIR%\uv.exe"
if exist "%UV_EXE%" exit /b 0
if not exist "%BOOTSTRAP_DIR%" mkdir "%BOOTSTRAP_DIR%" || exit /b 1
echo [+] Installing the uv runtime bootstrapper
set "UV_INSTALL_DIR=%BOOTSTRAP_DIR%"
set "UV_NO_MODIFY_PATH=1"
set "UV_INSTALLER=%TEMP%\imr-sqliblind-uv-%RANDOM%%RANDOM%.ps1"
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://astral.sh/uv/install.ps1' -OutFile $env:UV_INSTALLER"
if errorlevel 1 (
  del /q "%UV_INSTALLER%" >nul 2>&1
  echo [x] Unable to download the official uv installer 1>&2
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%UV_INSTALLER%"
set "UV_INSTALL_EXIT=%ERRORLEVEL%"
del /q "%UV_INSTALLER%" >nul 2>&1
if not "%UV_INSTALL_EXIT%"=="0" (
  echo [x] The official uv installer failed with exit code %UV_INSTALL_EXIT% 1>&2
  exit /b %UV_INSTALL_EXIT%
)
if not exist "%UV_EXE%" (
  echo [x] uv installation did not create %UV_EXE% 1>&2
  exit /b 1
)
exit /b 0

:persist_environment
set "SQLIBLIND_ENV_HOME=%PREFIX%"
set "SQLIBLIND_ENV_PYTHON=%VENV_PYTHON%"
set "SQLIBLIND_ENV_BIN=%BIN_DIR%"
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $homePath=$env:SQLIBLIND_ENV_HOME; $pythonPath=$env:SQLIBLIND_ENV_PYTHON; $bin=$env:SQLIBLIND_ENV_BIN; [Environment]::SetEnvironmentVariable('IMR_SQLIBLIND_HOME',$homePath,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_PYTHON',$pythonPath,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_BIN',$bin,'User'); $current=[Environment]::GetEnvironmentVariable('Path','User'); $items=@(); if($current){ foreach($item in $current.Split(';')){ if($item -and $item.TrimEnd('\') -ine $bin.TrimEnd('\')){ $items += $item } } }; $items += $bin; [Environment]::SetEnvironmentVariable('Path',($items -join ';'),'User'); $persisted=[Environment]::GetEnvironmentVariable('Path','User').Split(';'); $found=$false; foreach($item in $persisted){ if($item -and $item.TrimEnd('\') -ieq $bin.TrimEnd('\')){ $found=$true } }; if(-not $found){ throw 'The sqliblind bin directory was not persisted in the user PATH' }" || exit /b 1
exit /b 0

:activate_current_environment
set "PATH=%BIN_DIR%;%PATH%"
where /Q sqliblind
if errorlevel 1 (
  echo [x] sqliblind is still unavailable after updating PATH 1>&2
  exit /b 1
)
exit /b 0

:mkdir_failed
echo [x] Unable to create installation directory: %PREFIX% 1>&2
exit /b 1
