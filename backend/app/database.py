from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import logging
from pathlib import Path
from .config import settings

logger = logging.getLogger(__name__)

# Определяем URL базы данных
if settings.DB_USE_MYSQL:
    database_url = settings.mysql_database_url
    connect_args = {}
else:
    database_url = settings.DATABASE_URL
    # Создаем папку для базы данных если её нет
    if database_url.startswith("sqlite"):
        # Для SQLite нужно убрать префикс и создать путь
        db_path = database_url.replace("sqlite:///", "")
        db_path_dir = Path(db_path).parent
        if db_path_dir != Path("."):
            db_path_dir.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if "sqlite" in database_url else {}

# Создаем движок базы данных
try:
    logger.info(f"🔄 Подключение к базе данных: {database_url.split('@')[-1] if '@' in database_url else database_url}")
    engine = create_engine(
        database_url,
        connect_args=connect_args,
        echo=False,  # Включить echo=True для отладки SQL запросов
        pool_pre_ping=True if settings.DB_USE_MYSQL else False,  # Для MySQL проверка соединения
        # Для MySQL добавляем параметры для надежности транзакций
        pool_recycle=3600 if settings.DB_USE_MYSQL else None,  # Переиспользование соединений
        isolation_level="READ COMMITTED" if settings.DB_USE_MYSQL else None,  # Уровень изоляции для MySQL
        # Для MySQL добавляем параметры для надежности транзакций
        pool_size=10 if settings.DB_USE_MYSQL else None,  # Размер пула соединений
        max_overflow=20 if settings.DB_USE_MYSQL else None  # Максимальное количество дополнительных соединений
    )
    logger.info("✅ Движок базы данных создан успешно")
except Exception as e:
    logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось создать движок базы данных: {e}", exc_info=True)
    raise

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для моделей
Base = declarative_base()


def get_db():
    """Dependency для получения сессии БД"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"❌ Ошибка в сессии БД: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        try:
            db.close()
        except Exception as e:
            logger.error(f"❌ Ошибка при закрытии сессии БД: {e}", exc_info=True)


def init_db():
    """Инициализация базы данных - создание таблиц"""
    from .models import User, Chat, Message
    
    try:
        logger.info("🔄 Инициализация базы данных...")
        Base.metadata.create_all(bind=engine)
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: Не удалось инициализировать базу данных: {e}", exc_info=True)
        raise
