@echo off
REM Ensure a virtual environment exists and is activated
set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%venv"

if "%VIRTUAL_ENV%"=="" (
    if not exist "%VENV_DIR%" (
        echo Creating virtual environment...
        python -m venv "%VENV_DIR%"
    )
    echo Activating virtual environment...
    call "%VENV_DIR%\Scripts\activate"
)

echo Installing required packages...
pip install -r "%SCRIPT_DIR%requirements.txt"

REM Launch DumpBehandler using Python
python "%SCRIPT_DIR%main.py" %*
pause
