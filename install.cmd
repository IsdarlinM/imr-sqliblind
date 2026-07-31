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
set "FORCE_MANAGED_PYTHON=0"

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
if /I "%~1"=="--managed-python" (
  set "FORCE_MANAGED_PYTHON=1"
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
echo   --prefix PATH       Custom installation directory.
echo   --python PATH       Preferred Python executable ^(must be Python 3.10+^).
echo   --managed-python    Force the isolated Python 3.12 managed by uv.
echo   --no-path           Do not persist environment variables or modify PATH.
echo   -h, --help          Show this help.
exit /b 0

:args_done
if "%FORCE_MANAGED_PYTHON%"=="1" if defined PYTHON_OVERRIDE (
  echo [x] --python and --managed-python cannot be used together 1>&2
  exit /b 2
)

set "BIN_DIR=%PREFIX%\bin"
set "VENV_DIR=%PREFIX%\venv"
set "BOOTSTRAP_DIR=%PREFIX%\bootstrap"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "VENV_COMMAND=%VENV_DIR%\Scripts\sqliblind.exe"
set "COMMAND_PATH=%BIN_DIR%\sqliblind.cmd"
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "USE_MANAGED_PYTHON=0"
set "PYTHON_VERSION_CHECK=import sys; raise SystemExit(0 if sys.version_info.major in range(4,100) or (sys.version_info.major == 3 and sys.version_info.minor in range(10,100)) else 1)"

if not exist "%PREFIX%" mkdir "%PREFIX%" || goto mkdir_failed

if "%FORCE_MANAGED_PYTHON%"=="1" (
  set "USE_MANAGED_PYTHON=1"
  echo [+] Managed Python %MANAGED_PYTHON% was explicitly requested
  goto python_ready
)

if defined PYTHON_OVERRIDE (
  if not exist "%PYTHON_OVERRIDE%" (
    echo [x] Python executable not found: %PYTHON_OVERRIDE% 1>&2
    exit /b 1
  )
  "%PYTHON_OVERRIDE%" -c "%PYTHON_VERSION_CHECK%" >nul 2>&1
  if errorlevel 1 (
    echo [x] --python must point to Python 3.10 or newer 1>&2
    exit /b 1
  )
  set "PYTHON_EXE=%PYTHON_OVERRIDE%"
  goto python_ready
)

where py.exe >nul 2>&1
if not errorlevel 1 (
  py -3 -c "%PYTHON_VERSION_CHECK%" >nul 2>&1
  if not errorlevel 1 (
    set "PYTHON_EXE=py.exe"
    set "PYTHON_ARGS=-3"
    goto python_ready
  )
)

where python.exe >nul 2>&1
if not errorlevel 1 (
  python.exe -c "%PYTHON_VERSION_CHECK%" >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('where python.exe') do if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
    goto python_ready
  )
)

where python3.exe >nul 2>&1
if not errorlevel 1 (
  python3.exe -c "%PYTHON_VERSION_CHECK%" >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('where python3.exe') do if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
    goto python_ready
  )
)

set "USE_MANAGED_PYTHON=1"
echo [+] No compatible system Python found; using managed Python %MANAGED_PYTHON%

:python_ready
if "%USE_MANAGED_PYTHON%"=="0" (
  "%PYTHON_EXE%" %PYTHON_ARGS% -c "%PYTHON_VERSION_CHECK%" >nul 2>&1
  if errorlevel 1 (
    echo [x] Unable to locate Python 3.10 or newer 1>&2
    exit /b 1
  )
)

if exist "%VENV_PYTHON%" (
  "%VENV_PYTHON%" -c "%PYTHON_VERSION_CHECK%" >nul 2>&1
  if errorlevel 1 rmdir /s /q "%VENV_DIR%"
)

if exist "%VENV_PYTHON%" goto environment_ready

echo [+] Creating isolated environment at %VENV_DIR%
if "%USE_MANAGED_PYTHON%"=="1" goto managed_environment

"%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%VENV_DIR%" >nul 2>&1
if errorlevel 1 goto managed_environment
goto environment_ready

:managed_environment
call :create_managed_environment || exit /b 1

:environment_ready
if not exist "%VENV_PYTHON%" (
  echo [x] Failed to create the Python environment 1>&2
  exit /b 1
)
"%VENV_PYTHON%" -c "%PYTHON_VERSION_CHECK%" >nul 2>&1
if errorlevel 1 (
  echo [x] The created Python environment is not Python 3.10 or newer 1>&2
  exit /b 1
)
for /f "delims=" %%V in ('"%VENV_PYTHON%" --version 2^>^&1') do echo [+] Using %%V

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
>> "%PREFIX%\install.env" echo SQLIBLIND_COMMAND=%COMMAND_PATH%
>> "%PREFIX%\install.env" echo SQLIBLIND_NATIVE_COMMAND=%VENV_COMMAND%

if "%NO_PATH%"=="0" (
  call :persist_environment || exit /b 1
  call :verify_persisted_environment || exit /b 1
)
set "IMR_SQLIBLIND_HOME=%PREFIX%"
set "SQLIBLIND_PYTHON=%VENV_PYTHON%"
set "SQLIBLIND_BIN=%BIN_DIR%"
set "SQLIBLIND_COMMAND=%COMMAND_PATH%"
set "SQLIBLIND_NATIVE_COMMAND=%VENV_COMMAND%"
set "PATH=%BIN_DIR%;%PATH%"
where sqliblind >nul 2>&1
if errorlevel 1 (
  echo [x] The sqliblind command is not available after configuring PATH 1>&2
  exit /b 1
)

echo [+] Verifying CLI, service config, and web console
call "%BIN_DIR%\sqliblind.cmd" --version || exit /b 1
call "%BIN_DIR%\sqliblind.cmd" config init >nul || exit /b 1
call "%BIN_DIR%\sqliblind.cmd" web --help >nul || exit /b 1
echo.
echo Installation completed.
echo   Home:    %PREFIX%
echo   Python:  %VENV_PYTHON%
echo   Command: %COMMAND_PATH%
echo   Native:  %VENV_COMMAND%
if "%NO_PATH%"=="0" (
  echo PATH was configured automatically for future terminals.
  echo When launched from CMD, the current CMD session is also refreshed.
  goto finish_with_environment
)
endlocal
exit /b 0

:finish_with_environment
set "FINAL_HOME=%PREFIX%"
set "FINAL_PYTHON=%VENV_PYTHON%"
set "FINAL_BIN=%BIN_DIR%"
set "FINAL_COMMAND=%COMMAND_PATH%"
set "FINAL_NATIVE=%VENV_COMMAND%"
set "FINAL_PATH=%PATH%"
endlocal & set "IMR_SQLIBLIND_HOME=%FINAL_HOME%" & set "SQLIBLIND_PYTHON=%FINAL_PYTHON%" & set "SQLIBLIND_BIN=%FINAL_BIN%" & set "SQLIBLIND_COMMAND=%FINAL_COMMAND%" & set "SQLIBLIND_NATIVE_COMMAND=%FINAL_NATIVE%" & set "PATH=%FINAL_PATH%"
exit /b 0

:create_managed_environment
call :install_uv || exit /b 1
echo [+] Installing managed Python %MANAGED_PYTHON%
"%UV_EXE%" python install --no-config "%MANAGED_PYTHON%" || exit /b 1
if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
"%UV_EXE%" venv --no-config --managed-python --python "%MANAGED_PYTHON%" "%VENV_DIR%" || exit /b 1
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
set "SQLIBLIND_ENV_COMMAND=%COMMAND_PATH%"
set "SQLIBLIND_ENV_NATIVE=%VENV_COMMAND%"
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $homePath=$env:SQLIBLIND_ENV_HOME; $pythonPath=$env:SQLIBLIND_ENV_PYTHON; $bin=$env:SQLIBLIND_ENV_BIN; $commandPath=$env:SQLIBLIND_ENV_COMMAND; $nativePath=$env:SQLIBLIND_ENV_NATIVE; [Environment]::SetEnvironmentVariable('IMR_SQLIBLIND_HOME',$homePath,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_PYTHON',$pythonPath,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_BIN',$bin,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_COMMAND',$commandPath,'User'); [Environment]::SetEnvironmentVariable('SQLIBLIND_NATIVE_COMMAND',$nativePath,'User'); $current=[Environment]::GetEnvironmentVariable('Path','User'); $items=@(); if($current){ foreach($item in $current.Split(';')){ if($item -and $item.TrimEnd('\') -ine $bin.TrimEnd('\')){ $items += $item } } }; $items += $bin; [Environment]::SetEnvironmentVariable('Path',($items -join ';'),'User')" || exit /b 1
exit /b 0

:verify_persisted_environment
set "SQLIBLIND_ENV_BIN=%BIN_DIR%"
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $bin=$env:SQLIBLIND_ENV_BIN.TrimEnd('\'); $current=[Environment]::GetEnvironmentVariable('Path','User'); if(-not $current){ exit 1 }; $found=$false; foreach($item in $current.Split(';')){ if($item -and $item.TrimEnd('\') -ieq $bin){ $found=$true; break } }; if(-not $found){ exit 1 }" || (
  echo [x] Unable to persist the sqliblind command directory in the user PATH 1>&2
  exit /b 1
)
exit /b 0

:mkdir_failed
echo [x] Unable to create installation directory: %PREFIX% 1>&2
exit /b 1
