@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo Creating the project virtual environment...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%PROJECT_ROOT%.venv"
    ) else (
        python -m venv "%PROJECT_ROOT%.venv"
    )
    if errorlevel 1 goto :failed
)

"%PYTHON%" -c "import fastapi, uvicorn, pydantic, yaml, requests, streamlit" >nul 2>&1
if errorlevel 1 (
    echo Installing project dependencies...
    "%PYTHON%" -m pip install -r "%PROJECT_ROOT%requirements.txt"
    if errorlevel 1 goto :failed
)

echo Starting the FastAPI server in a separate window...
start "API Change Guard - API" /D "%PROJECT_ROOT%" "%PYTHON%" -m uvicorn api.main:app --reload --app-dir "%PROJECT_ROOT%"
if errorlevel 1 goto :failed

echo Starting the Streamlit dashboard...
"%PYTHON%" -m streamlit run "%PROJECT_ROOT%ui\app.py"
goto :end

:failed
echo.
echo Startup failed. Check the error above and confirm Python is installed.
pause
exit /b 1

:end
endlocal
