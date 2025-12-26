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
│   ├── models/              # SQLAlchemy модели (User, Chat, Message)
│   ├── routes/               # API маршруты
│   │   ├── auth.py          # Авторизация (register, login, verify, profile)
│   │   ├── chats.py         # Управление чатами и сообщениями
│   │   └── admin.py         # Админ панель (управление пользователями)
│   ├── schemas/             # Pydantic схемы (валидация данных)
│   ├── auth/                # JWT аутентификация
│   │   ├── jwt.py           # Создание и проверка JWT токенов
│   │   └── dependencies.py  # Зависимости для проверки токенов и ролей
│   └── utils/               # Утилиты
│       └── database_migration.py  # Миграция данных из старой БД
├── venv/                    # Виртуальное окружение (не коммитится)
├── requirements.txt         # Python зависимости
├── run.py                   # Скрипт запуска сервера
└── README.md
```

## API Endpoints

- `/api/auth/register` - Регистрация
- `/api/auth/login` - Вход
- `/api/auth/verify` - Проверка токена
- `/api/auth/profile` - Обновление профиля
- `/api/chats` - Список/создание чатов
- `/api/chats/{id}` - Получение/обновление/удаление чата
- `/api/chats/{id}/messages` - Добавление сообщения
- `/api/admin/users` - Список пользователей (только для админов)
- `/api/admin/users/{id}/role` - Изменение роли (только для админов)
- `/api/admin/users/{id}` - Удаление пользователя (только для админов)

## Документация API

После запуска доступна автоматическая документация:
- Swagger UI: http://localhost:5000/docs
- ReDoc: http://localhost:5000/redoc
