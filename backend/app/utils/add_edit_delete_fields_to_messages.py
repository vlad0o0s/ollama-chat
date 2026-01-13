"""
Скрипт для добавления полей deleted, edited, edited_at в таблицу messages
"""
from sqlalchemy import text
from ..database import SessionLocal, engine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_edit_delete_fields():
    """Добавляет поля deleted, edited, edited_at в таблицу messages"""
    db = SessionLocal()
    try:
        # Проверяем, существует ли поле deleted
        if engine.url.drivername == 'sqlite':
            # Для SQLite
            result = db.execute(text("""
                SELECT COUNT(*) as cnt 
                FROM pragma_table_info('messages') 
                WHERE name = 'deleted'
            """))
            exists = result.scalar() > 0
        else:
            # Для MySQL/PostgreSQL
            result = db.execute(text("""
                SELECT COUNT(*) as cnt 
                FROM information_schema.COLUMNS 
                WHERE TABLE_NAME = 'messages' 
                AND COLUMN_NAME = 'deleted'
            """))
            exists = result.scalar() > 0
        
        if not exists:
            logger.info("Добавление поля deleted...")
            if engine.url.drivername == 'sqlite':
                db.execute(text("ALTER TABLE messages ADD COLUMN deleted BOOLEAN DEFAULT 0 NOT NULL"))
            else:
                db.execute(text("ALTER TABLE messages ADD COLUMN deleted BOOLEAN DEFAULT FALSE NOT NULL"))
            db.commit()
            logger.info("✅ Поле deleted добавлено")
        else:
            logger.debug("Поле deleted уже существует")
        
        # Проверяем, существует ли поле edited
        if engine.url.drivername == 'sqlite':
            result = db.execute(text("""
                SELECT COUNT(*) as cnt 
                FROM pragma_table_info('messages') 
                WHERE name = 'edited'
            """))
            exists = result.scalar() > 0
        else:
            result = db.execute(text("""
                SELECT COUNT(*) as cnt 
                FROM information_schema.COLUMNS 
                WHERE TABLE_NAME = 'messages' 
                AND COLUMN_NAME = 'edited'
            """))
            exists = result.scalar() > 0
        
        if not exists:
            logger.info("Добавление поля edited...")
            if engine.url.drivername == 'sqlite':
                db.execute(text("ALTER TABLE messages ADD COLUMN edited BOOLEAN DEFAULT 0 NOT NULL"))
            else:
                db.execute(text("ALTER TABLE messages ADD COLUMN edited BOOLEAN DEFAULT FALSE NOT NULL"))
            db.commit()
            logger.info("✅ Поле edited добавлено")
        else:
            logger.debug("Поле edited уже существует")
        
        # Проверяем, существует ли поле edited_at
        if engine.url.drivername == 'sqlite':
            result = db.execute(text("""
                SELECT COUNT(*) as cnt 
                FROM pragma_table_info('messages') 
                WHERE name = 'edited_at'
            """))
            exists = result.scalar() > 0
        else:
            result = db.execute(text("""
                SELECT COUNT(*) as cnt 
                FROM information_schema.COLUMNS 
                WHERE TABLE_NAME = 'messages' 
                AND COLUMN_NAME = 'edited_at'
            """))
            exists = result.scalar() > 0
        
        if not exists:
            logger.info("Добавление поля edited_at...")
            db.execute(text("ALTER TABLE messages ADD COLUMN edited_at DATETIME NULL"))
            db.commit()
            logger.info("✅ Поле edited_at добавлено")
        else:
            logger.debug("Поле edited_at уже существует")
        
        # Создаем индекс для поля deleted для улучшения производительности
        try:
            if engine.url.drivername == 'sqlite':
                # SQLite автоматически создает индекс для NOT NULL полей
                pass
            else:
                db.execute(text("CREATE INDEX IF NOT EXISTS idx_messages_deleted ON messages(deleted)"))
                db.commit()
                logger.debug("✅ Индекс для поля deleted создан")
        except Exception as e:
            logger.debug(f"Индекс для deleted уже существует или ошибка: {e}")
        
        logger.debug("✅ Все поля успешно добавлены")
        
    except Exception as e:
        logger.error(f"❌ Ошибка при добавлении полей: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    add_edit_delete_fields()

