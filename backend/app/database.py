from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path
from .config import settings

# Создаем папку для базы данных если её нет
if settings.DATABASE_URL.startswith("sqlite"):
    # Для SQLite нужно убрать префикс и создать путь
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    db_path_dir = Path(db_path).parent
    if db_path_dir != Path("."):
        db_path_dir.mkdir(parents=True, exist_ok=True)

# Создаем движок базы данных
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
    echo=False
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

