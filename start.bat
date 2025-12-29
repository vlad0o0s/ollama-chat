@echo off
chcp 65001 >nul
echo ========================================
echo   Запуск Ollama Chat
echo ========================================
echo.

REM Проверка наличия виртуального окружения Process Manager
if not exist "process_manager\venv\Scripts\python.exe" (
    echo [ПРЕДУПРЕЖДЕНИЕ] Виртуальное окружение Process Manager не найдено!
    echo Создаю виртуальное окружение для Process Manager...
    cd process_manager
    python -m venv venv
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось создать виртуальное окружение!
        pause
        exit /b 1
    )
    call venv\Scripts\activate.bat
    echo Установка зависимостей Process Manager...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости Process Manager!
        pause
        exit /b 1
    )
    cd ..
    echo.
)

REM Проверка наличия виртуального окружения Backend
if not exist "backend\venv\Scripts\python.exe" (
    echo [ОШИБКА] Виртуальное окружение Backend не найдено!
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

echo [1/3] Запуск Process Management API...
start "Process Management API" cmd /k "cd /d %~dp0process_manager && venv\Scripts\activate.bat && python process_manager_api.py"

timeout /t 3 /nobreak >nul

echo [2/3] Запуск бэкенда...
start "Ollama Chat Backend" cmd /k "cd /d %~dp0backend && venv\Scripts\activate.bat && python run.py"

timeout /t 3 /nobreak >nul

echo [3/3] Запуск фронтенда...
start "Ollama Chat Frontend" cmd /k "cd /d %~dp0frontend && npm start"

echo.
echo ========================================
echo   Все серверы запускаются...
echo ========================================
echo.
echo Process Management API: http://localhost:8888
echo Бэкенд: http://localhost:5000
echo Фронтенд: http://localhost:3000
echo.
echo Закройте окна CMD для остановки серверов.
echo.
pause
