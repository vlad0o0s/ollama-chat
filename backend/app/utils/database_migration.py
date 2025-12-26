"""
Скрипт для миграции данных из существующей Node.js SQLite БД в новую структуру
"""
import sqlite3
import sys
from pathlib import Path
from datetime import datetime
from sqlalchemy.orm import Session
from ..database import SessionLocal, init_db
from ..models.user import User
from ..models.chat import Chat
from ..models.message import Message


def parse_datetime(date_str):
    """Парсит строку даты в объект datetime"""
    if not date_str:
        return None
    if isinstance(date_str, datetime):
        return date_str
    try:
        # Пробуем разные форматы дат
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%d'
        ]
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None
    except (ValueError, TypeError):
        return None


def migrate_from_old_db(old_db_path: str, new_db_session: Session):
    """Мигрирует данные из старой БД в новую"""
    print(f"🔍 Подключение к старой БД: {old_db_path}")
    
    # Подключаемся к старой БД
    old_conn = sqlite3.connect(old_db_path)
    old_conn.row_factory = sqlite3.Row
    old_cursor = old_conn.cursor()
    
    try:
        # Миграция пользователей
        print("📦 Миграция пользователей...")
        old_cursor.execute("SELECT * FROM users")
        users = old_cursor.fetchall()
        
        user_id_mapping = {}  # Старый ID -> Новый ID
        
        for old_user_row in users:
            # Преобразуем Row в словарь для удобной работы
            old_user = dict(old_user_row)
            
            # Проверяем, существует ли уже пользователь с таким именем
            existing_user = new_db_session.query(User).filter(User.name == old_user["name"]).first()
            
            if existing_user:
                print(f"  ⚠️ Пользователь {old_user['name']} уже существует, пропускаем")
                user_id_mapping[old_user["id"]] = existing_user.id
                continue
            
            new_user = User(
                id=old_user["id"],  # Сохраняем старый ID
                name=old_user["name"],
                password=old_user["password"],  # Пароль уже захеширован
                role=old_user.get("role", "user"),
                created_at=parse_datetime(old_user.get("created_at")),
                updated_at=parse_datetime(old_user.get("updated_at"))
            )
            new_db_session.add(new_user)
            user_id_mapping[old_user["id"]] = old_user["id"]
        
        new_db_session.commit()
        print(f"  ✅ Мигрировано {len(users)} пользователей")
        
        # Миграция чатов
        print("📦 Миграция чатов...")
        old_cursor.execute("SELECT * FROM chats")
        chats = old_cursor.fetchall()
        
        chat_id_mapping = {}  # Старый ID -> Новый ID
        
        for old_chat_row in chats:
            # Преобразуем Row в словарь для удобной работы
            old_chat = dict(old_chat_row)
            
            # Проверяем, существует ли уже чат с таким ID
            existing_chat = new_db_session.query(Chat).filter(Chat.id == old_chat["id"]).first()
            
            if existing_chat:
                print(f"  ⚠️ Чат {old_chat['id']} уже существует, пропускаем")
                chat_id_mapping[old_chat["id"]] = existing_chat.id
                continue
            
            # Проверяем, что user_id существует в новой БД
            if old_chat["user_id"] not in user_id_mapping:
                print(f"  ⚠️ Пользователь {old_chat['user_id']} не найден, пропускаем чат {old_chat['id']}")
                continue
            
            new_chat = Chat(
                id=old_chat["id"],  # Сохраняем старый ID
                user_id=user_id_mapping[old_chat["user_id"]],
                title=old_chat["title"],
                pinned=bool(old_chat.get("pinned", 0)),
                created_at=parse_datetime(old_chat.get("created_at")),
                updated_at=parse_datetime(old_chat.get("updated_at"))
            )
            new_db_session.add(new_chat)
            chat_id_mapping[old_chat["id"]] = old_chat["id"]
        
        new_db_session.commit()
        print(f"  ✅ Мигрировано {len(chats)} чатов")
        
        # Миграция сообщений
        print("📦 Миграция сообщений...")
        old_cursor.execute("SELECT * FROM messages ORDER BY created_at")
        messages = old_cursor.fetchall()
        
        migrated_count = 0
        skipped_count = 0
        
        for old_message_row in messages:
            # Преобразуем Row в словарь для удобной работы
            old_message = dict(old_message_row)
            
            # Проверяем, что chat_id существует в новой БД
            if old_message["chat_id"] not in chat_id_mapping:
                skipped_count += 1
                continue
            
            # Проверяем, существует ли уже сообщение с таким ID
            existing_message = new_db_session.query(Message).filter(Message.id == old_message["id"]).first()
            
            if existing_message:
                skipped_count += 1
                continue
            
            new_message = Message(
                id=old_message["id"],  # Сохраняем старый ID
                chat_id=chat_id_mapping[old_message["chat_id"]],
                role=old_message["role"],
                content=old_message["content"],
                created_at=parse_datetime(old_message.get("created_at"))
            )
            new_db_session.add(new_message)
            migrated_count += 1
        
        new_db_session.commit()
        print(f"  ✅ Мигрировано {migrated_count} сообщений")
        if skipped_count > 0:
            print(f"  ⚠️ Пропущено {skipped_count} сообщений (не найдены связанные чаты)")
        
        print("✅ Миграция завершена успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        new_db_session.rollback()
        raise
    finally:
        old_conn.close()


def run_migration():
    """Запускает миграцию"""
    # Путь к старой БД
    old_db_path = Path("../lastV/data/ollama_chat.db")
    
    if not old_db_path.exists():
        print(f"❌ Старая БД не найдена: {old_db_path}")
        print("   Продолжаем без миграции...")
        return
    
    # Инициализируем новую БД
    print("🔧 Инициализация новой БД...")
    init_db()
    
    # Создаем сессию для новой БД
    db = SessionLocal()
    
    try:
        migrate_from_old_db(str(old_db_path), db)
    finally:
        db.close()


if __name__ == "__main__":
    run_migration()

