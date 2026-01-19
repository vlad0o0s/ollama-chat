@echo off
echo ========================================
echo   Start Ollama Chat
echo   Service Supervisor Mode
echo ========================================
echo.

REM Check Process Manager venv
if not exist "process_manager\venv\Scripts\python.exe" (
    echo [WARNING] Process Manager venv not found.
    echo Creating virtual environment for Process Manager...
    cd process_manager
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    call venv\Scripts\activate.bat
    echo Installing Process Manager dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install Process Manager dependencies.
        pause
        exit /b 1
    )
    cd ..
    echo.
)

REM Check Backend venv
if not exist "backend\venv\Scripts\python.exe" (
    echo [ERROR] Backend venv not found.
    echo Please create it with:
    echo   cd backend
    echo   python -m venv venv
    echo   .\venv\Scripts\Activate.ps1
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Check node_modules
if not exist "frontend\node_modules" (
    echo [WARNING] node_modules not found.
    echo Installing frontend dependencies...
    cd frontend
    call npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install frontend dependencies.
        pause
        exit /b 1
    )
    cd ..
    echo.
)

echo ========================================
echo   Start Service Supervisor
echo ========================================
echo.
echo Service Supervisor will start:
echo   - Backend (FastAPI)
echo   - Frontend (React)
echo.
echo Launching Service Supervisor...
echo.

start "Service Supervisor" cmd /k "cd /d %~dp0process_manager && venv\Scripts\activate.bat && python process_manager_api.py"

timeout /t 5 /nobreak >nul

echo.
echo ========================================
echo   Services are starting...
echo ========================================
echo.
echo Service Supervisor API: http://localhost:8888
echo   - GET  /health           - Status of all services
echo   - POST /restart/{name}   - Restart service
echo   - POST /stop/{name}      - Stop service
echo   - GET  /logs/{name}      - View logs
echo.
echo Backend (managed by Supervisor): http://localhost:5000
echo Frontend (managed by Supervisor): http://localhost:3000
echo.
echo Service logs: process_manager\logs\
echo.
echo To stop all services, close the Service Supervisor window.
echo Or use API: POST http://localhost:8888/stop/backend
echo             POST http://localhost:8888/stop/frontend
echo.
pause
