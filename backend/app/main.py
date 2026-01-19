from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os
import logging
from .config import settings
from .database import init_db
from .routes import auth, chats, admin, search_chat, image_generation, process
from .models.user import User
from .database import get_db, SessionLocal
from .utils.add_edit_delete_fields_to_messages import add_edit_delete_fields
from .services.process_manager_service import process_manager_service
from .services.service_types import ServiceType

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Устанавливаем уровень логирования для всех модулей
logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)  # Логи SQL только при ошибках
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

# Глобальный обработчик исключений
import sys
import asyncio
def handle_exception(exc_type, exc_value, exc_traceback):
    """Глобальный обработчик необработанных исключений"""
    # Игнорируем KeyboardInterrupt и CancelledError (нормальное завершение)
    if issubclass(exc_type, (KeyboardInterrupt, asyncio.CancelledError)):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logging.critical(
        "❌ КРИТИЧЕСКАЯ ОШИБКА: Необработанное исключение",
        exc_info=(exc_type, exc_value, exc_traceback)
    )

sys.excepthook = handle_exception

app = FastAPI(
    title="Ollama Chat API",
    description="Backend API для чат-приложения с Ollama",
    version="1.0.0-beta.1"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключение роутов
app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(admin.router)
app.include_router(search_chat.router)
app.include_router(image_generation.router)
app.include_router(process.router)


@app.on_event("startup")
async def startup_event():
    """Инициализация при запуске"""
    logging.info("🚀 Backend запускается...")
    # Инициализация базы данных
    init_db()
    
    # Добавляем поля для редактирования и удаления сообщений (тихо, только при ошибках)
    try:
        add_edit_delete_fields()
    except Exception as e:
        logging.error(f"❌ Ошибка при добавлении полей для редактирования/удаления: {e}")
    
    # Назначаем пользователя vlad0o0s администратором при запуске сервера
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.name == "vlad0o0s").first()
        if user:
            if user.role != "admin":
                user.role = "admin"
                db.commit()
                logging.info("✅ Пользователь vlad0o0s назначен администратором")
            # else: убрано логирование - пользователь уже админ
        else:
            logging.debug("⚠️ Пользователь vlad0o0s не найден в базе данных")
    except Exception as e:
        logging.error(f"❌ Ошибка назначения админа: {e}")
        db.rollback()
    finally:
        db.close()
    
    # Автозапуск Ollama при старте backend (если используется Process Manager)
    if settings.PROCESS_MANAGER_API_URL:
        try:
            logging.info("🔄 Проверка и автозапуск Ollama...")
            # Проверяем доступность Ollama
            ollama_available = await process_manager_service.check_service_available(ServiceType.OLLAMA)
            if not ollama_available:
                logging.info("🔄 Ollama не запущена, запускаем автоматически...")
                # Пытаемся переключиться на Ollama (это запустит её, если возможно)
                success = await process_manager_service.switch_to_service(ServiceType.OLLAMA)
                if success:
                    # Ждем немного, чтобы Ollama успела запуститься
                    import asyncio
                    await asyncio.sleep(3)
                    # Проверяем еще раз
                    ollama_available = await process_manager_service.check_service_available(ServiceType.OLLAMA)
                    if ollama_available:
                        logging.info("✅ Ollama успешно запущена и доступна")
                    else:
                        logging.warning("⚠️ Ollama запускается, но еще не доступна (может потребоваться больше времени)")
                else:
                    logging.warning("⚠️ Не удалось автоматически запустить Ollama")
            else:
                logging.info("✅ Ollama уже запущена и доступна")
        except Exception as e:
            logging.warning(f"⚠️ Ошибка при автозапуске Ollama: {e}")
            # Не критично, продолжаем работу


@app.on_event("shutdown")
async def shutdown_event():
    """Обработка завершения работы"""
    import asyncio
    try:
        logging.info("🛑 Backend завершает работу...")
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Игнорируем ошибки при shutdown
        pass
    except Exception as e:
        # Логируем только реальные ошибки
        logging.error(f"❌ Ошибка при shutdown: {e}", exc_info=True)


@app.get("/")
async def root():
    """Корневой endpoint"""
    return {"message": "Ollama Chat API", "version": "1.0.0-beta.1"}


@app.get("/health")
async def health_check():
    """Проверка здоровья сервера"""
    return {"status": "ok"}


@app.get("/favicon.ico")
async def favicon():
    """Обработчик для favicon.ico - возвращает 204 No Content"""
    from fastapi import Response
    return Response(status_code=204)


# Обслуживание статических файлов для изображений
images_path = Path(settings.IMAGE_STORAGE_PATH)
if images_path.exists():
    app.mount("/static/images", StaticFiles(directory=str(images_path)), name="images")

# Обслуживание статических файлов React приложения (если build папка существует)
build_path = Path("../lastV/build")
if build_path.exists():
    app.mount("/static", StaticFiles(directory=str(build_path / "static")), name="static")
    
    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        """Все остальные маршруты направляем на React приложение"""
        if full_path.startswith("api") or full_path.startswith("static"):
            return {"error": "Not found"}
        
        index_path = build_path / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"error": "React app not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True
    )

