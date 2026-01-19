from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime
from typing import List, Optional
from ..database import get_db
from ..models.user import User
from ..models.chat import Chat
from ..models.message import Message
from ..schemas.chat import ChatCreate, ChatUpdate, ChatResponse, ChatWithMessages
from ..schemas.message import MessageCreate, MessageResponse, MessageUpdate
from ..auth.dependencies import get_current_user

router = APIRouter(prefix="/api/chats", tags=["chats"])


def get_chat_with_messages(chat_id: int, db: Session) -> Optional[ChatWithMessages]:
    """Получает чат с сообщениями (исключая удаленные)"""
    import logging
    logger = logging.getLogger(__name__)
    
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        logger.warning(f"⚠️ Чат не найден в БД (chat_id: {chat_id})")
        return None
    
    messages = db.query(Message).filter(
        Message.chat_id == chat_id,
        Message.deleted == False
    ).order_by(Message.created_at).all()
    
    logger.debug(f"📝 Загружено сообщений из БД: {len(messages)} (chat_id: {chat_id})")
    
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
        # Подсчитываем сообщения (исключая удаленные)
        message_count = db.query(func.count(Message.id)).filter(
            Message.chat_id == chat.id,
            Message.deleted == False
        ).scalar() or 0
        
        # Получаем последнее сообщение ассистента (исключая удаленные)
        last_message_obj = db.query(Message)\
            .filter(
                Message.chat_id == chat.id,
                Message.role == "assistant",
                Message.deleted == False
            )\
            .order_by(desc(Message.created_at))\
            .first()
        
        last_message = None
        last_message_at = None
        if last_message_obj:
            last_message = last_message_obj.content
            last_message_at = last_message_obj.created_at
            if len(last_message) > 20:
                last_message = last_message[:20] + "..."
        
        # Получаем максимальную дату сообщения (исключая удаленные)
        if not last_message_at:
            last_message_at = db.query(func.max(Message.created_at))\
                .filter(
                    Message.chat_id == chat.id,
                    Message.deleted == False
                )\
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
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"💾 Создание нового чата для пользователя {current_user.id}")
        # Удаляем все пустые чаты пользователя перед созданием нового
        user_chats = db.query(Chat).filter(Chat.user_id == current_user.id).all()
        
        # Подсчитываем сообщения для каждого чата (исключая удаленные)
        empty_chats = []
        for chat in user_chats:
            message_count = db.query(func.count(Message.id)).filter(
                Message.chat_id == chat.id,
                Message.deleted == False
            ).scalar()
            if message_count == 0:
                empty_chats.append(chat)
        
        # Удаляем пустые чаты
        if empty_chats:
            logger.info(f"🗑️ Удаление {len(empty_chats)} пустых чатов")
            for empty_chat in empty_chats:
                db.delete(empty_chat)
            
            try:
                db.commit()
                logger.info(f"✅ Пустые чаты удалены")
            except Exception as e:
                logger.error(f"❌ Ошибка при удалении пустых чатов: {e}", exc_info=True)
                db.rollback()
                raise
        
        # Дополнительная проверка - если все еще есть пустые чаты, возвращаем первый
        updated_user_chats = db.query(Chat).filter(Chat.user_id == current_user.id).all()
        still_empty_chats = []
        for chat in updated_user_chats:
            message_count = db.query(func.count(Message.id)).filter(
                Message.chat_id == chat.id,
                Message.deleted == False
            ).scalar()
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
        
        try:
            db.commit()
            db.refresh(new_chat)
            logger.info(f"✅ Новый чат создан (chat_id: {new_chat.id}, user_id: {current_user.id})")
        except Exception as e:
            logger.error(f"❌ Ошибка при создании чата: {e}", exc_info=True)
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка при создании чата: {str(e)}"
            )
        
        return ChatResponse(
            id=new_chat.id,
            user_id=new_chat.user_id,
            title=new_chat.title,
            pinned=new_chat.pinned,
            created_at=new_chat.created_at,
            updated_at=new_chat.updated_at,
            message_count=0
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА при создании чата: {e}", exc_info=True)
        try:
            db.rollback()
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.get("/{chat_id}", response_model=ChatWithMessages)
async def get_chat(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Получение чата с сообщениями"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"📖 Запрос на получение чата (chat_id: {chat_id}, user_id: {current_user.id})")
    
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    
    if not chat or chat.user_id != current_user.id:
        logger.warning(f"⚠️ Чат не найден или нет доступа (chat_id: {chat_id}, user_id: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    # Получаем сообщения
    chat_with_messages = get_chat_with_messages(chat_id, db)
    message_count = len(chat_with_messages.messages) if chat_with_messages else 0
    logger.info(f"✅ Чат загружен (chat_id: {chat_id}, сообщений: {message_count})")
    
    return chat_with_messages


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
    
    message_count = db.query(func.count(Message.id)).filter(
        Message.chat_id == chat.id,
        Message.deleted == False
    ).scalar()
    
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
    
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"💾 Создание сообщения (chat_id: {chat_id}, role: {message_data.role})")
        new_message = Message(
            chat_id=chat_id,
            role=message_data.role,
            content=message_data.content,
            message_type=message_data.message_type,
            image_url=message_data.image_url,
            image_metadata=message_data.image_metadata
        )
        db.add(new_message)
        
        try:
            db.commit()
            db.refresh(new_message)
            logger.info(f"✅ Сообщение создано (message_id: {new_message.id}, chat_id: {chat_id})")
        except Exception as e:
            logger.error(f"❌ Ошибка при создании сообщения: {e}", exc_info=True)
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка при создании сообщения: {str(e)}"
            )
        
        return MessageResponse.model_validate(new_message)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА при создании сообщения: {e}", exc_info=True)
        try:
            db.rollback()
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.put("/{chat_id}/messages/{message_id}", response_model=MessageResponse)
async def update_message(
    chat_id: int,
    message_id: int,
    message_update: MessageUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Редактирование сообщения"""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.chat_id == chat_id,
        Message.deleted == False
    ).first()
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сообщение не найдено"
        )
    
    # Только пользователь может редактировать свои сообщения
    if message.role != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Можно редактировать только свои сообщения"
        )
    
    message.content = message_update.content
    message.edited = True
    message.edited_at = datetime.utcnow()
    
    db.commit()
    db.refresh(message)
    
    return MessageResponse.model_validate(message)


@router.delete("/{chat_id}/messages/{message_id}")
async def delete_message(
    chat_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Удаление сообщения (soft delete)"""
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    
    if not chat or chat.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.chat_id == chat_id,
        Message.deleted == False
    ).first()
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сообщение не найдено"
        )
    
    # Только пользователь может удалять свои сообщения
    if message.role != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Можно удалять только свои сообщения"
        )
    
    message.deleted = True
    db.commit()
    
    return {"message": "Сообщение успешно удалено"}

