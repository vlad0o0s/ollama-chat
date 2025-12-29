# Ollama Chat Backend (Python FastAPI)

## Запуск

1. Создайте виртуальное окружение:
```bash
python -m venv venv
```

2. Активируйте окружение:

**Windows (PowerShell):**
```powershell
.\venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
venv\Scripts\activate.bat
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте файл `.env` из `.env.example` и настройте `JWT_SECRET`

5. Запустите сервер:
```bash
python run.py
```

Сервер будет доступен на `http://localhost:5000`

## Структура проекта

```
backend/
├── app/
│   ├── main.py              # Точка входа FastAPI
│   ├── config.py            # Конфигурация (настройки из .env)
│   ├── database.py          # Подключение к БД (SQLAlchemy)
│   ├── models/              # SQLAlchemy модели
│   │   ├── user.py          # Модель пользователя
│   │   ├── chat.py          # Модель чата
│   │   └── message.py       # Модель сообщения (поддерживает текст и изображения)
│   ├── routes/              # API маршруты
│   │   ├── auth.py          # Авторизация (register, login, verify, profile)
│   │   ├── chats.py         # Управление чатами и сообщениями
│   │   ├── admin.py         # Админ панель (управление пользователями)
│   │   ├── search_chat.py    # Чат с поиском в интернете (Tavily)
│   │   └── image_generation.py  # Генерация изображений (ComfyUI)
│   ├── schemas/             # Pydantic схемы (валидация данных)
│   │   ├── auth.py
│   │   ├── user.py
│   │   ├── chat.py
│   │   ├── message.py
│   │   └── search.py
│   ├── services/            # Бизнес-логика
│   │   ├── search_service.py      # Сервис поиска через Tavily API
│   │   ├── comfyui_service.py     # Сервис для работы с ComfyUI API
│   │   └── prompt_service.py     # Сервис перевода промптов через Ollama
│   ├── auth/                # JWT аутентификация
│   │   ├── jwt.py           # Создание и проверка JWT токенов
│   │   └── dependencies.py  # Зависимости для проверки токенов и ролей
│   └── utils/               # Утилиты
│       ├── image_storage.py       # Хранение сгенерированных изображений
│       └── add_image_fields_to_messages.py  # Миграция БД для поддержки изображений
├── static/                  # Статические файлы
│   └── images/              # Сгенерированные изображения (организованы по датам)
├── venv/                    # Виртуальное окружение (не коммитится)
├── requirements.txt         # Python зависимости
├── run.py                   # Скрипт запуска сервера
└── README.md
```

## API Endpoints

**Аутентификация:**
- `POST /api/auth/register` - Регистрация
- `POST /api/auth/login` - Вход
- `GET /api/auth/verify` - Проверка токена
- `PUT /api/auth/profile` - Обновление профиля

**Чаты:**
- `GET /api/chats` - Список чатов пользователя
- `POST /api/chats` - Создание нового чата
- `GET /api/chats/{id}` - Получение чата с сообщениями
- `PUT /api/chats/{id}` - Обновление чата
- `DELETE /api/chats/{id}` - Удаление чата

**Чат с поиском:**
- `POST /api/chat/search` - Отправка сообщения с поиском в интернете (Tavily API)

**Генерация изображений:**
- `POST /api/image/generate` - Генерация изображения по текстовому описанию (ComfyUI)
- `GET /api/image/{message_id}` - Получение метаданных изображения

**Административная панель:**
- `GET /api/admin/users` - Список пользователей (только для админов)
- `PUT /api/admin/users/{id}/role` - Изменение роли (только для админов)
- `DELETE /api/admin/users/{id}` - Удаление пользователя (только для админов)

## Документация API

После запуска доступна автоматическая документация:
- Swagger UI: http://localhost:5000/docs
- ReDoc: http://localhost:5000/redoc

## Генерация изображений

### Архитектура

1. **Prompt Service** - Переводит русское описание в английский промпт через Ollama
2. **ComfyUI Service** - Создает workflow, добавляет в очередь и получает готовое изображение
3. **Image Storage** - Сохраняет изображения локально с организацией по датам (YYYY/MM/DD)
4. **Database** - Сохраняет метаданные изображения в таблице messages (message_type='image')

### Настройка

В `.env` файле:
```env
COMFYUI_URL=http://your-comfyui-server:8188
COMFYUI_MODEL=flux1-dev-fp8
COMFYUI_TIMEOUT=300
IMAGE_STORAGE_PATH=static/images
```

### Workflow

ComfyUI workflow автоматически создается для модели Flux с параметрами:
- Размер: 1024x1024 (по умолчанию)
- Steps: 20
- CFG Scale: 7.0
- Sampler: euler
- Scheduler: normal

### Хранение изображений

Изображения сохраняются в `backend/static/images/YYYY/MM/DD/{uuid}.png` и доступны через `/static/images/...`
