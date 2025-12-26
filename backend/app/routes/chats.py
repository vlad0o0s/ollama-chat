from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from ..database import get_db
from ..models.user import User
from ..models.chat import Chat
from ..models.message import Message
from ..schemas.chat import ChatCreate, ChatUpdate, ChatResponse, ChatWithMessages
from ..schemas.message import MessageCreate, MessageResponse
from ..auth.dependencies import get_current_user

router = APIRouter(prefix="/api/chats", tags=["chats"])


def get_chat_with_messages(chat_id: int, db: Session) -> Optional[ChatWithMessages]:
    """Получает чат с сообщениями"""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        return None
    
    messages = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at).all()
    
    chat_dict = {
        "id": chat.id,
        "user_id": chat.user_id,
        "title": chat.title,
        "pinned": chat.pinned,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "messages": [MessageResponse.model_validate(msg) for msg in messages]
    }
    
    return ChatWithMessages(**chat_dict)


@router.get("", response_model=List[ChatResponse])
async def get_chats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение всех чатов пользователя"""
    # Получаем все чаты пользователя
    chats = db.query(Chat).filter(Chat.user_id == current_user.id)\
     .order_by(desc(Chat.pinned), desc(Chat.updated_at))\
     .all()
    
    result = []
    for chat in chats:
        # Подсчитываем сообщения
        message_count = db.query(func.count(Message.id)).filter(Message.chat_id == chat.id).scalar() or 0
        
        # Получаем последнее сообщение ассистента
        last_message_obj = db.query(Message)\
            .filter(Message.chat_id == chat.id, Message.role == "assistant")\
            .order_by(desc(Message.created_at))\
            .first()
        
        last_message = None
        last_message_at = None
        if last_message_obj:
            last_message = last_message_obj.content
            last_message_at = last_message_obj.created_at
            if len(last_message) > 20:
                last_message = last_message[:20] + "..."
        
        # Получаем максимальную дату сообщения
        if not last_message_at:
            last_message_at = db.query(func.max(Message.created_at))\
                .filter(Message.chat_id == chat.id)\
                .scalar()
        
        chat_dict = {
            "id": chat.id,
            "user_id": chat.user_id,
            "title": chat.title,
            "pinned": chat.pinned,
            "created_at": chat.created_at,
            "updated_at": chat.updated_at,
            "message_count": message_count,
            "last_message_at": last_message_at,
            "last_message": last_message
        }
        result.append(ChatResponse(**chat_dict))
    
    return result


@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    chat_data: ChatCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Создание нового чата (с удалением пустых чатов)"""
    # Удаляем все пустые чаты пользователя перед созданием нового
    user_chats = db.query(Chat).filter(Chat.user_id == current_user.id).all()
    
    # Подсчитываем сообщения для каждого чата
    empty_chats = []
    for chat in user_chats:
        message_count = db.query(func.count(Message.id)).filter(Message.chat_id == chat.id).scalar()
        if message_count == 0:
            empty_chats.append(chat)
    
    # Удаляем пустые чаты
    for empty_chat in empty_chats:
        db.delete(empty_chat)
    
    db.commit()
    
    # Дополнительная проверка - если все еще есть пустые чаты, возвращаем первый
    updated_user_chats = db.query(Chat).filter(Chat.user_id == current_user.id).all()
    still_empty_chats = []
    for chat in updated_user_chats:
        message_count = db.query(func.count(Message.id)).filter(Message.chat_id == chat.id).scalar()
        if message_count == 0:
            still_empty_chats.append(chat)
    
    if still_empty_chats:
        chat = still_empty_chats[0]
        return ChatResponse(
            id=chat.id,
            user_id=chat.user_id,
            title=chat.title,
            pinned=chat.pinned,
            created_at=chat.created_at,
            updated_at=chat.updated_at,
            message_count=0
        )
    
    # Создаем новый чат
    new_chat = Chat(
        user_id=current_user.id,
        title=chat_data.title or "Новый чат"
    )
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)
    
    return ChatResponse(
        id=new_chat.id,
        user_id=new_chat.user_id,
        title=new_chat.title,
        pinned=new_chat.pinned,
        created_at=new_chat.created_at,
        updated_at=new_chat.updated_at,
        message_count=0
    )


@router.get("/{chat_id}", response_model=ChatWithMessages)
async def get_chat(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение чата с сообщениями"""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    return get_chat_with_messages(chat_id, db)


@router.put("/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat_id: int,
    chat_update: ChatUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Обновление чата"""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    if chat_update.title is not None:
        chat.title = chat_update.title
    if chat_update.pinned is not None:
        chat.pinned = chat_update.pinned
    
    db.commit()
    db.refresh(chat)
    
    message_count = db.query(func.count(Message.id)).filter(Message.chat_id == chat.id).scalar()
    
    return ChatResponse(
        id=chat.id,
        user_id=chat.user_id,
        title=chat.title,
        pinned=chat.pinned,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        message_count=message_count or 0
    )


@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление чата"""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    db.delete(chat)
    db.commit()
    
    return {"message": "Чат успешно удален"}


@router.post("/{chat_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    chat_id: int,
    message_data: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Добавление сообщения в чат"""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    new_message = Message(
        chat_id=chat_id,
        role=message_data.role,
        content=message_data.content
    )
    db.add(new_message)
    db.commit()
    db.refresh(new_message)
    
    return MessageResponse.model_validate(new_message)

