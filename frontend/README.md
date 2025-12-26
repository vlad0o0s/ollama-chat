# Ollama Chat - Frontend

React фронтенд для чат-приложения с Ollama.

## Установка

1. Установите зависимости:
```bash
npm install
```

2. Создайте файл `.env` на основе `.env.example`:
```bash
cp .env.example .env
```

3. Настройте переменные окружения в `.env`:
```
REACT_APP_API_URL=http://localhost:5000
```

## Запуск

### Режим разработки

```bash
npm start
```

Приложение откроется на `http://localhost:3000`.

В режиме разработки все запросы к `/api/*` автоматически проксируются на бэкенд (http://localhost:5000) благодаря настройке `proxy` в `package.json`.

### Сборка для продакшена

```bash
npm build
```

Собранные файлы будут в папке `build/`.

## Интеграция с Python бэкендом

Фронтенд работает с Python FastAPI бэкендом. Убедитесь, что:

1. Бэкенд запущен на порту 5000 (или измените `proxy` в `package.json` и `REACT_APP_API_URL` в `.env`)
2. CORS настроен правильно в бэкенде для разрешения запросов с `http://localhost:3000`

## Структура проекта

```
frontend/
├── public/
│   └── index.html          # HTML шаблон
├── src/
│   ├── components/         # React компоненты
│   │   ├── AdminPanel.js   # Админ панель
│   │   ├── ChatManager.js  # Менеджер чатов
│   │   ├── Login.js        # Форма входа
│   │   ├── Register.js     # Форма регистрации
│   │   ├── UserProfile.js  # Профиль пользователя
│   │   └── MarkdownRenderer.js # Рендерер Markdown
│   ├── App.js              # Главный компонент
│   ├── App.css             # Стили главного компонента
│   ├── AuthContext.js      # Контекст аутентификации
│   ├── index.js            # Точка входа
│   └── index.css           # Глобальные стили
├── package.json            # Зависимости и скрипты
├── .env.example           # Пример переменных окружения
└── README.md              # Документация
```

## API совместимость

Фронтенд полностью совместим с Python FastAPI бэкендом. Все эндпоинты идентичны:

- `/api/auth/register` - Регистрация
- `/api/auth/login` - Вход
- `/api/auth/verify` - Проверка токена
- `/api/auth/profile` - Обновление профиля
- `/api/chats` - Управление чатами
- `/api/chats/{id}` - Операции с чатом
- `/api/chats/{id}/messages` - Сообщения чата
- `/api/admin/*` - Админ функции

## Обработка ошибок

Фронтенд поддерживает оба формата ошибок:
- FastAPI: `{ "detail": "Сообщение" }`
- Node.js (legacy): `{ "message": "Сообщение" }`

## Технологии

- React 18.2.0
- React Markdown для отображения ответов ИИ
- React Icons для иконок
- KaTeX для математических формул
- Highlight.js для подсветки синтаксиса

## Лицензия

Бета версия - для тестирования.

