@echo off
echo ========================================
echo   Запуск Ollama Chat
echo ========================================
echo.

echo [1/2] Запуск бэкенда...
start "Ollama Chat Backend" powershell -NoExit -Command "cd backend; .\venv\Scripts\Activate.ps1; python run.py"

timeout /t 3 /nobreak >nul

echo [2/2] Запуск фронтенда...
start "Ollama Chat Frontend" powershell -NoExit -Command "cd frontend; npm start"

echo.
echo ========================================
echo   Серверы запускаются...
echo ========================================
echo.
echo Бэкенд: http://localhost:5000
echo Фронтенд: http://localhost:3000
echo.
echo Закройте окна PowerShell для остановки серверов.
echo.
pause

