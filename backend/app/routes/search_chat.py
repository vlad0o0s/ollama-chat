"""
Роуты для чата с поиском в интернете
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import httpx
import json
import asyncio
from sqlalchemy.sql import func
from ..database import get_db, SessionLocal
from ..models.user import User
from ..models.chat import Chat
from ..models.message import Message
from ..schemas.search import SearchRequest, SearchMetadata
from ..schemas.message import MessageCreate
from ..auth.dependencies import get_current_user
from ..services.search_service import search_service
from ..services.resource_manager import resource_manager
from ..services.process_manager_service import process_manager_service
from ..services.service_types import ServiceType
from ..config import settings
from ..utils.date_replacer import replace_temporal_words
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
    Чат с поиском в интернете (или без поиска)
    
    Выполняет поиск по запросу пользователя (если включен), затем отправляет запрос в Ollama
    с контекстом поиска для генерации ответа.
    Сохраняет все сообщения в БД.
    """
    # Логируем начало обработки запроса
    logger.info(f"📨 Получен запрос на чат (chat_id: {request.chat_id}, user_id: {current_user.id}, message_length: {len(request.message)}, use_search: {request.use_search})")
    
    # Проверяем существование чата
    chat = db.query(Chat).filter(
        Chat.id == request.chat_id,
        Chat.user_id == current_user.id
    ).first()
    
    if not chat:
        logger.error(f"❌ Чат не найден (chat_id: {request.chat_id}, user_id: {current_user.id})")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    logger.info(f"✅ Чат найден (chat_id: {request.chat_id}, title: {chat.title})")
    
    # Заменяем временные слова на реальную дату в сообщении пользователя
    processed_message = replace_temporal_words(request.message)
    
    # Сохраняем оригинальное сообщение пользователя (без замены даты)
    logger.info(f"💾 Сохранение сообщения пользователя (chat_id: {request.chat_id}, content_length: {len(request.message)})")
    try:
        user_message = Message(
            chat_id=request.chat_id,
            role="user",
            content=request.message
        )
        db.add(user_message)
        
        # Обновляем updated_at у чата
        chat = db.query(Chat).filter(Chat.id == request.chat_id).first()
        if chat:
            # Обновляем updated_at у чата для отслеживания последней активности
            chat.updated_at = datetime.utcnow()
            logger.debug(f"Обновлен updated_at у чата {request.chat_id}")
        else:
            logger.warning(f"⚠️ Чат {request.chat_id} не найден при сохранении сообщения пользователя")
        
        # Принудительно сохраняем изменения
        try:
            db.flush()  # Отправляем изменения в БД без коммита (для получения ID)
            logger.debug(f"Flush выполнен для сообщения пользователя, message_id: {user_message.id}")
        except Exception as flush_error:
            logger.error(f"❌ Ошибка при flush сообщения пользователя: {flush_error}", exc_info=True)
            db.rollback()
            raise
        
        try:
            db.commit()  # Коммитим транзакцию
            logger.info(f"✅ Сообщение пользователя сохранено в БД (chat_id: {request.chat_id}, message_id: {user_message.id})")
        except Exception as commit_error:
            logger.error(f"❌ Ошибка при commit сообщения пользователя: {commit_error}", exc_info=True)
            db.rollback()
            raise
        
        db.refresh(user_message)
        
        # Проверяем, что сообщение действительно сохранено
        verify_message = db.query(Message).filter(Message.id == user_message.id).first()
        if verify_message:
            logger.info(f"✅ Сообщение пользователя подтверждено в БД (message_id: {user_message.id})")
        else:
            logger.error(f"❌ КРИТИЧНО: Сообщение пользователя не найдено после коммита! (message_id: {user_message.id})")
            
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА при сохранении сообщения пользователя: {e}", exc_info=True)
        try:
            db.rollback()
        except:
            pass
        raise
    
    # ВАЖНО: Не закрываем сессию db здесь, она будет закрыта автоматически после завершения функции
    # Но нужно убедиться, что коммит действительно произошел
    
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
    # Получаем историю сообщений (исключая удаленные)
    previous_messages = db.query(Message).filter(
        Message.chat_id == request.chat_id,
        Message.deleted == False
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
        
        # Добавляем контекст поиска и текущий вопрос (с замененной датой)
        messages_for_llm.append({
            "role": "user",
            "content": search_context + f"\n\nВопрос пользователя: {processed_message}"
        })
    else:
        # Добавляем предыдущие сообщения
        for msg in previous_messages:
            if msg.id != user_message.id:  # Исключаем только что добавленное сообщение
                messages_for_llm.append({
                    "role": msg.role,
                    "content": msg.content
                })
        
        # Добавляем текущее сообщение (с замененной датой)
        messages_for_llm.append({
            "role": "user",
            "content": processed_message
        })
    
    # Сохраняем user_id в переменную, чтобы использовать после закрытия сессии БД
    user_id = current_user.id
    
    # Создаем потоковый ответ
    logger.info(f"🔄 Начало генерации ответа для чата {request.chat_id}")
    
    async def generate_response():
        assistant_content = ""
        logger.info(f"📝 Генерация ответа начата (chat_id: {request.chat_id})")
        
        # Ollama должна быть запущена автоматически при старте backend
        # Если она все еще недоступна, ждем немного (она может еще запускаться)
        try:
            ollama_available = await process_manager_service.check_service_available(ServiceType.OLLAMA)
            if not ollama_available:
                logger.warning("⚠️ Ollama недоступна, ожидаем запуска (до 10 секунд)...")
                # Ждем до 10 секунд, пока Ollama запустится
                for _ in range(5):  # 5 попыток по 2 секунды = 10 секунд
                    await asyncio.sleep(2)
                    ollama_available = await process_manager_service.check_service_available(ServiceType.OLLAMA)
                    if ollama_available:
                        logger.info("✅ Ollama стала доступна")
                        break
                if not ollama_available:
                    logger.error("❌ Ollama все еще недоступна после ожидания")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при проверке Ollama: {e}")
            # Продолжаем работу, возможно Ollama уже запущена
        
        # Оцениваем требуемую VRAM для Ollama (обычно 2-4GB)
        estimated_vram_mb = 3072  # 3GB для безопасности
        
        # Получаем блокировку GPU через Resource Manager
        try:
            async with await resource_manager.acquire_gpu(
                service_type=ServiceType.OLLAMA,
                user_id=user_id,  # Используем сохраненный user_id вместо current_user.id
                required_vram_mb=estimated_vram_mb,
                timeout=300
            ) as gpu_lock:
                logger.info(f"🔒 GPU заблокирован для Ollama (чат, ID: {gpu_lock.lock_id[:8]})")
                
                try:
                    # Отправляем запрос в Ollama
                    # Если используется Process Manager, Ollama запускается локально на 127.0.0.1:11434
                    if settings.PROCESS_MANAGER_API_URL:
                        ollama_url = "http://127.0.0.1:11434/api/chat"
                    else:
                        ollama_url = f"{settings.OLLAMA_URL}/api/chat"
                    
                    async with httpx.AsyncClient(timeout=300.0) as client:
                        
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
                                    
                except Exception as e:
                    logger.error(f"❌ Ошибка при работе с Ollama: {e}")
                    error_data = {
                        "error": f"Ошибка при генерации ответа: {str(e)}",
                        "done": True
                    }
                    yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
                    
        except TimeoutError as e:
            logger.error(f"❌ Таймаут ожидания GPU для Ollama (чат): {e}")
            error_data = {
                "error": f"Таймаут ожидания GPU: {str(e)}",
                "done": True
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            return
        except Exception as e:
            logger.error(f"❌ Ошибка при работе с Resource Manager: {e}")
            error_data = {
                "error": f"Ошибка управления ресурсами: {str(e)}",
                "done": True
            }
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
            return
        
        # Сохраняем ответ ассистента в БД (синхронно в отдельном потоке для надежности)
        if assistant_content:
            def save_message():
                db_session = SessionLocal()
                try:
                    logger.info(f"💾 Начало сохранения сообщения ассистента в БД (chat_id: {request.chat_id}, content_length: {len(assistant_content)})")
                    
                    # Создаем сообщение ассистента
                    assistant_message = Message(
                        chat_id=request.chat_id,
                        role="assistant",
                        content=assistant_content
                    )
                    db_session.add(assistant_message)
                    
                    # Обновляем updated_at у чата
                    chat = db_session.query(Chat).filter(Chat.id == request.chat_id).first()
                    if chat:
                        chat.updated_at = datetime.utcnow()
                        logger.debug(f"Обновлен updated_at у чата {request.chat_id}")
                    else:
                        logger.warning(f"⚠️ Чат {request.chat_id} не найден при сохранении сообщения ассистента")
                    
                    # Принудительно сохраняем изменения
                    db_session.flush()  # Отправляем изменения в БД без коммита (для получения ID)
                    logger.debug(f"Flush выполнен, message_id: {assistant_message.id}")
                    
                    # Коммитим транзакцию
                    db_session.commit()
                    logger.info(f"✅ Commit выполнен для сообщения (chat_id: {request.chat_id}, message_id: {assistant_message.id})")
                    
                    # Проверяем, что сообщение действительно сохранено (в новой сессии для проверки)
                    verify_session = SessionLocal()
                    try:
                        saved_message = verify_session.query(Message).filter(Message.id == assistant_message.id).first()
                        if saved_message:
                            logger.info(f"✅ Сообщение ассистента подтверждено в БД (chat_id: {request.chat_id}, message_id: {assistant_message.id}, content_length: {len(saved_message.content)})")
                        else:
                            logger.error(f"❌ КРИТИЧНО: Сообщение не найдено после коммита! (chat_id: {request.chat_id}, message_id: {assistant_message.id})")
                    finally:
                        verify_session.close()
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка сохранения сообщения ассистента в БД: {e}", exc_info=True)
                    try:
                        db_session.rollback()
                        logger.error(f"❌ Rollback выполнен из-за ошибки")
                    except Exception as rollback_error:
                        logger.error(f"❌ Ошибка при rollback: {rollback_error}")
                finally:
                    try:
                        db_session.close()
                    except:
                        pass
            
            # Выполняем сохранение в отдельном потоке и ждем завершения
            loop = asyncio.get_event_loop()
            try:
                await loop.run_in_executor(None, save_message)
                logger.info(f"✅ Сохранение сообщения ассистента завершено (chat_id: {request.chat_id})")
            except Exception as e:
                logger.error(f"❌ Ошибка при выполнении сохранения сообщения ассистента в потоке: {e}", exc_info=True)
    
    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )