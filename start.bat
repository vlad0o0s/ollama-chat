@echo off
chcp 65001 >nul
echo ========================================
echo   Запуск Ollama Chat
echo ========================================
echo.

REM Проверка наличия виртуального окружения
if not exist "backend\venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение не найдено!
    echo Пожалуйста, создайте его командой:
    echo   cd backend
    echo   python -m venv venv
    echo   .\venv\Scripts\Activate.ps1
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM Проверка наличия node_modules
if not exist "frontend\node_modules" (
    echo [ПРЕДУПРЕЖДЕНИЕ] node_modules не найдены!
    echo Устанавливаю зависимости фронтенда...
    cd frontend
    call npm install
    cd ..
    echo.
)

echo [1/2] Запуск бэкенда...
start "Ollama Chat Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\activate.bat && python run.py"

timeout /t 3 /nobreak >nul

echo [2/2] Запуск фронтенда...
start "Ollama Chat Frontend" cmd /k "cd /d %~dp0frontend && npm start"

echo.
echo ========================================
echo   Серверы запускаются...
echo ========================================
echo.
echo Бэкенд: http://localhost:5000
echo Фронтенд: http://localhost:3000
echo.
echo Закройте окна CMD для остановки серверов.
echo.
pause
