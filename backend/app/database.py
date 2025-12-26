from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path
from .config import settings

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
engine = create_engine(
    database_url,
    connect_args=connect_args,
    echo=False,
    pool_pre_ping=True if settings.DB_USE_MYSQL else False  # Для MySQL проверка соединения
)

# Создаем фабрику сессий
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Базовый класс для моделей
Base = declarative_base()


def get_db():
    """Dependency для получения сессии БД"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Инициализация базы данных - создание таблиц"""
    from .models import User, Chat, Message
    
    Base.metadata.create_all(bind=engine)
    print("✅ База данных инициализирована")

