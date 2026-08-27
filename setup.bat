@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYTHON=.venv\Scripts\python.exe"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PYTHONDONTWRITEBYTECODE=1"

if exist "%VENV_PYTHON%" goto validate_venv
if exist ".venv" (
    echo Existing .venv is incomplete or does not contain Scripts\python.exe.
    echo Rename or delete .venv manually, then run setup.bat again.
    exit /b 1
)

echo Selecting supported CPython 3.14 x64...
where py >nul 2>nul
if not errorlevel 1 (
    py -3.14 -c "import platform,struct,sys; sys.exit(0 if platform.system() == 'Windows' and platform.python_implementation() == 'CPython' and sys.version_info[:2] == (3,14) and struct.calcsize('P') * 8 == 64 else 1)" >nul 2>nul
    if not errorlevel 1 (
        py -3.14 -m venv .venv
        if errorlevel 1 goto venv_create_failed
        goto validate_venv
    )
)

where python >nul 2>nul
if errorlevel 1 goto python_missing
python -c "import platform,struct,sys; sys.exit(0 if platform.system() == 'Windows' and platform.python_implementation() == 'CPython' and sys.version_info[:2] == (3,14) and struct.calcsize('P') * 8 == 64 else 1)" >nul 2>nul
if errorlevel 1 goto python_missing
python -m venv .venv
if errorlevel 1 goto venv_create_failed

:validate_venv
"%VENV_PYTHON%" -m core.runtime_environment --check
if errorlevel 1 (
    echo.
    echo Existing .venv does not satisfy Windows 11 x64 with CPython 3.14.
    echo Rename or delete .venv manually, then run setup.bat again.
    exit /b 1
)

echo.
echo Installing bootstrap tooling pip==26.1.1...
"%VENV_PYTHON%" -m pip install --no-cache-dir --only-binary=:all: pip==26.1.1
if errorlevel 1 exit /b 1

echo.
echo Installing the exact runtime lock...
"%VENV_PYTHON%" -m pip install --no-cache-dir --only-binary=:all: -r requirements.txt
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" -m pip check
if errorlevel 1 exit /b 1

echo.
echo Verifying the exact installed runtime set...
"%VENV_PYTHON%" -m core.runtime_lock --requirements requirements.txt --check
if errorlevel 1 (
    echo Existing .venv does not exactly match the committed runtime lock.
    echo Rename or delete .venv manually, then run setup.bat again.
    exit /b 1
)

echo.
echo Interpreter: %CD%\%VENV_PYTHON%
"%VENV_PYTHON%" --version
"%VENV_PYTHON%" -m pip --version
echo Setup completed successfully.
echo Launch PromptGraph Pro with: run.bat
exit /b 0

:python_missing
echo Supported CPython 3.14 x64 was not found.
echo Install CPython 3.14 for 64-bit Windows, then run setup.bat again.
exit /b 1

:venv_create_failed
echo Failed to create .venv. No existing environment was deleted.
echo Rename or delete any partial .venv manually, then run setup.bat again.
exit /b 1
