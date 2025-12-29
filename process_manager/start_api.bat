@echo off
echo ========================================
echo    Process Management API Server
echo ========================================
echo.

REM Проверяем наличие виртуального окружения
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Виртуальное окружение не найдено!
    echo.
    echo Создайте виртуальное окружение командой:
    echo   python -m venv venv
    echo.
    echo Затем установите зависимости:
    echo   venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Активация виртуального окружения...
call venv\Scripts\activate.bat

echo.
echo Проверка зависимостей...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Установка зависимостей...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Не удалось установить зависимости!
        pause
        exit /b 1
    )
)

echo.
echo ========================================
echo    Запуск Process Management API
echo ========================================
echo.
echo API будет доступен на: http://0.0.0.0:8888
echo.
echo Для остановки нажмите Ctrl+C
echo.

REM Запускаем API сервер
python process_manager_api.py

echo.
echo API сервер остановлен.
pause

