# Process Management API

API сервер для управления процессами Ollama и ComfyUI на Windows ПК.

## Установка

1. Установите зависимости:
```bash
pip install -r requirements.txt
```

2. Настройте переменные окружения (опционально):
- `COMFYUI_PATH` - путь к ComfyUI (по умолчанию: `C:\ComfyUI_windows_portable`)
- `OLLAMA_PATH` - путь к папке с ollama.exe (по умолчанию: ищется в PATH)
- `PROCESS_API_PORT` - порт API (по умолчанию: 8888)
- `PROCESS_STARTUP_WAIT` - время ожидания запуска процесса в секундах (по умолчанию: 10)

## Запуск

```bash
python process_manager_api.py
```

Или через uvicorn:
```bash
uvicorn process_manager_api:app --host 0.0.0.0 --port 8888
```

## API Endpoints

### GET /
Информация о сервисе и доступных эндпоинтах.

### GET /process/status
Получает статус всех процессов (Ollama и ComfyUI).

### POST /process/switch?service={ollama|comfyui}
Переключает на указанный сервис:
- Останавливает текущий процесс (если запущен)
- Запускает указанный процесс
- Возвращает информацию о переключении

### POST /process/stop?service={ollama|comfyui}
Останавливает указанный процесс.

### POST /process/start?service={ollama|comfyui}
Запускает указанный процесс.

## Примеры использования

### Переключение на Ollama
```bash
curl -X POST "http://localhost:8888/process/switch?service=ollama"
```

### Переключение на ComfyUI
```bash
curl -X POST "http://localhost:8888/process/switch?service=comfyui"
```

### Проверка статуса
```bash
curl http://localhost:8888/process/status
```

## Безопасность

⚠️ **Важно**: Этот API должен быть доступен только из внутренней сети. Не открывайте его в интернет без дополнительной аутентификации.

