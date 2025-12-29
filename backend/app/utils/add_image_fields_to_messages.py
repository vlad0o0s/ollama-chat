"""
Скрипт миграции для добавления полей image_url, image_metadata, message_type в таблицу messages
"""
from sqlalchemy import text, inspect
from ..database import engine, SessionLocal
import logging

logger = logging.getLogger(__name__)


def migrate_messages_table():
    """Добавляет новые поля в таблицу messages"""
    db = SessionLocal()
    try:
        # Проверяем, существуют ли уже поля
        inspector = inspect(engine)
        columns = inspector.get_columns("messages")
        existing_columns = [col["name"] for col in columns]
        
        # Добавляем message_type, если его нет
        if "message_type" not in existing_columns:
            logger.info("Добавление поля message_type...")
            with engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE messages 
                    ADD COLUMN message_type VARCHAR(20) DEFAULT 'text' NOT NULL
                """))
                conn.commit()
            logger.info("✅ Поле message_type добавлено")
        else:
            logger.info("⚠️ Поле message_type уже существует")
        
        # Добавляем image_url, если его нет
        if "image_url" not in existing_columns:
            logger.info("Добавление поля image_url...")
            with engine.connect() as conn:
                conn.execute(text("""
                    ALTER TABLE messages 
                    ADD COLUMN image_url VARCHAR(500) NULL
                """))
                conn.commit()
            logger.info("✅ Поле image_url добавлено")
        else:
            logger.info("⚠️ Поле image_url уже существует")
        
        # Добавляем image_metadata, если его нет
        if "image_metadata" not in existing_columns:
            logger.info("Добавление поля image_metadata...")
            # Для MySQL используем JSON, для SQLite - TEXT
            try:
                with engine.connect() as conn:
                    conn.execute(text("""
                        ALTER TABLE messages 
                        ADD COLUMN image_metadata JSON NULL
                    """))
                    conn.commit()
            except Exception as e:
                # Fallback для SQLite или старых версий MySQL
                logger.warning(f"Не удалось добавить JSON поле, пробуем TEXT: {e}")
                with engine.connect() as conn:
                    conn.execute(text("""
                        ALTER TABLE messages 
                        ADD COLUMN image_metadata TEXT NULL
                    """))
                    conn.commit()
            logger.info("✅ Поле image_metadata добавлено")
        else:
            logger.info("⚠️ Поле image_metadata уже существует")
        
        # Добавляем constraint для message_type, если его нет
        try:
            # Проверяем существующие constraints
            constraints = inspector.get_check_constraints("messages")
            constraint_names = [c["name"] for c in constraints]
            
            if "check_message_type" not in constraint_names:
                with engine.connect() as conn:
                    conn.execute(text("""
                        ALTER TABLE messages 
                        ADD CONSTRAINT check_message_type 
                        CHECK (message_type IN ('text', 'image'))
                    """))
                    conn.commit()
                logger.info("✅ Constraint check_message_type добавлен")
            else:
                logger.info("⚠️ Constraint check_message_type уже существует")
        except Exception as e:
            # Constraint может не поддерживаться или уже существовать
            logger.debug(f"Не удалось добавить constraint (может быть не поддерживается): {e}")
        
        logger.info("✅ Миграция завершена успешно")
        
    except Exception as e:
        logger.error(f"❌ Ошибка миграции: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate_messages_table()

