"""
Роуты для чата с поиском в интернете
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import httpx
import json
import asyncio
from ..database import get_db, SessionLocal
from ..models.user import User
from ..models.chat import Chat
from ..models.message import Message
from ..schemas.search import SearchRequest, SearchMetadata
from ..schemas.message import MessageCreate
from ..auth.dependencies import get_current_user
from ..services.search_service import search_service
from ..config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["search-chat"])


@router.post("/search")
async def chat_with_search(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Чат с поиском в интернете
    
    Выполняет поиск по запросу пользователя, затем отправляет запрос в Ollama
    с контекстом поиска для генерации ответа
    """
    # Проверяем существование чата
    chat = db.query(Chat).filter(
        Chat.id == request.chat_id,
        Chat.user_id == current_user.id
    ).first()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    # Сохраняем сообщение пользователя
    user_message = Message(
        chat_id=request.chat_id,
        role="user",
        content=request.message
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)
    
    # Выполняем поиск, если включен
    search_metadata = None
    search_context = ""
    
    if request.use_search:
        try:
            search_result = await search_service.search(request.message)
            search_metadata = SearchMetadata(
                query=search_result["query"],
                sources=search_result["sources"],
                results_count=len(search_result["results"]),
                success=search_result["success"],
                error=search_result.get("error")
            )
            
            if search_result["success"] and search_result["results"]:
                search_context = search_service.format_search_context(search_result)
            else:
                # Если поиск не дал результатов, продолжаем без контекста поиска
                logger.warning(f"Поиск не дал результатов для запроса: {request.message}")
        except Exception as e:
            # Если поиск не удался, продолжаем без него
            logger.error(f"Ошибка поиска: {e}")
            search_metadata = SearchMetadata(
                query=request.message,
                sources=[],
                results_count=0,
                success=False,
                error=str(e)
            )
    
    # Формируем сообщения для Ollama
    # Получаем историю сообщений
    previous_messages = db.query(Message).filter(
        Message.chat_id == request.chat_id
    ).order_by(Message.created_at).all()
    
    # Формируем контекст для LLM
    messages_for_llm = []
    
    # Добавляем системное сообщение с контекстом поиска, если есть
    if search_context:
        messages_for_llm.append({
            "role": "system",
            "content": "Ты полезный ассистент. Используй предоставленную информацию из интернета для ответа на вопросы пользователя. Всегда указывай источники информации, если используешь данные из поиска."
        })
        
        # Добавляем предыдущие сообщения для контекста
        for msg in previous_messages:
            if msg.id != user_message.id:  # Исключаем только что добавленное сообщение
                messages_for_llm.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Добавляем контекст поиска и текущий вопрос
        messages_for_llm.append({
            "role": "user",
            "content": search_context + f"\n\nВопрос пользователя: {request.message}"
        })
    else:
        # Добавляем предыдущие сообщения
        for msg in previous_messages:
            if msg.id != user_message.id:  # Исключаем только что добавленное сообщение
                messages_for_llm.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Добавляем текущее сообщение
        messages_for_llm.append({
            "role": "user",
            "content": request.message
        })
    
    # Создаем потоковый ответ
    async def generate_response():
        assistant_content = ""
        
        try:
            # Отправляем запрос в Ollama
            async with httpx.AsyncClient(timeout=300.0) as client:
                ollama_url = f"{settings.OLLAMA_URL}/api/chat"
                
                payload = {
                    "model": settings.OLLAMA_DEFAULT_MODEL,
                    "messages": messages_for_llm,
                    "stream": True
                }
                
                async with client.stream(
                    "POST",
                    ollama_url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=300.0
                ) as response:
                    if response.status_code != 200:
                        try:
                            error_text = await response.aread()
                            error_msg = error_text.decode() if error_text else "Unknown error"
                        except:
                            error_msg = f"HTTP {response.status_code}"
                        logger.error(f"Ошибка Ollama: {error_msg}")
                        error_data = {
                            "error": f"Ошибка Ollama: {error_msg}",
                            "done": True
                        }
                        yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                        return
                    
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        
                        try:
                            data = json.loads(line)
                            
                            if "message" in data and "content" in data["message"]:
                                content = data["message"]["content"]
                                assistant_content += content
                                
                                # Отправляем чанк клиенту в формате SSE
                                chunk_data = {
                                    "content": content,
                                    "done": False
                                }
                                yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                            
                            if data.get("done", False):
                                # Отправляем финальный чанк с метаданными
                                final_data = {
                                    "content": "",
                                    "done": True,
                                    "search_metadata": search_metadata.dict() if search_metadata else None
                                }
                                yield f"data: {json.dumps(final_data, ensure_ascii=False)}\n\n"
                                break
                                
                        except json.JSONDecodeError:
                            continue
                        except Exception as e:
                            error_data = {
                                "error": str(e),
                                "done": True
                            }
                            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                            break
            
            # Сохраняем ответ ассистента в БД (синхронная операция в отдельном потоке)
            if assistant_content:
                def save_message():
                    db_session = SessionLocal()
                    try:
                        assistant_message = Message(
                            chat_id=request.chat_id,
                            role="assistant",
                            content=assistant_content
                        )
                        db_session.add(assistant_message)
                        db_session.commit()
                    finally:
                        db_session.close()
                
                # Выполняем сохранение в отдельном потоке
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, save_message)
                
        except Exception as e:
            error_data = {
                "error": f"Ошибка генерации ответа: {str(e)}",
                "done": True
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

