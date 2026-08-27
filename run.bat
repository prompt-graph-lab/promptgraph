@echo off
setlocal
cd /d "%~dp0"

set "VENV_PYTHON=.venv\Scripts\python.exe"
set "PYTHONDONTWRITEBYTECODE=1"
if not exist "%VENV_PYTHON%" (
    echo PromptGraph Pro environment is not installed. Run setup.bat first.
    exit /b 1
)

"%VENV_PYTHON%" -m core.runtime_environment --check
if errorlevel 1 (
    echo Runtime contract check failed. Run setup.bat for guidance.
    exit /b 1
)

"%VENV_PYTHON%" -m streamlit run app.py
set "STREAMLIT_EXIT=%ERRORLEVEL%"
exit /b %STREAMLIT_EXIT%
