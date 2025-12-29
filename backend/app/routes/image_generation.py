"""
Роуты для генерации изображений через ComfyUI
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import time
import json
import asyncio
import logging
from ..database import get_db
from ..models.user import User
from ..models.chat import Chat
from ..models.message import Message
from ..auth.dependencies import get_current_user
from ..services.comfyui_service import comfyui_service
from ..services.prompt_service import prompt_service
from ..services.resource_manager import resource_manager
from ..services.service_types import ServiceType
from ..utils.image_storage import image_storage
from ..config import settings
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/image", tags=["image-generation"])


class ImageGenerationRequest(BaseModel):
    chat_id: int
    description: str = Field(..., min_length=1, max_length=2000, description="Описание изображения на русском языке")


class ImageGenerationResponse(BaseModel):
    message_id: int
    image_url: str
    prompt_positive: str
    prompt_negative: str
    generation_time: float
    success: bool
    error: Optional[str] = None


@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Генерирует изображение на основе описания пользователя (синхронный endpoint)
    
    Процесс:
    1. Проверка существования чата и прав доступа
    2. Перевод описания в английский промпт через Ollama
    3. Генерация изображения через ComfyUI
    4. Сохранение изображения
    5. Создание сообщения в БД
    """
    start_time = time.time()
    
    # Проверяем существование чата и прав доступа
    chat = db.query(Chat).filter(
        Chat.id == request.chat_id,
        Chat.user_id == current_user.id
    ).first()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    # Валидация описания
    if not request.description or len(request.description.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Описание изображения не может быть пустым"
        )
    
    if len(request.description) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Описание слишком длинное (максимум 2000 символов)"
        )
    
    try:
        # Шаг 1: Сохраняем сообщение пользователя
        user_message = Message(
            chat_id=request.chat_id,
            role="user",
            content=request.description,
            message_type="text"
        )
        db.add(user_message)
        db.commit()
        db.refresh(user_message)
        
        # Шаг 2: Переводим описание в промпты через Ollama
        logger.info(f"🔄 Перевод описания в промпты для пользователя {current_user.name}")
        prompt_result = await prompt_service.translate_and_enhance_prompt(request.description, user_id=current_user.id)
        
        if not prompt_result.get("success"):
            error_msg = prompt_result.get("error", "Ошибка перевода промпта")
            logger.error(f"❌ Ошибка перевода промпта: {error_msg}")
            
            # Создаем сообщение об ошибке
            error_message = Message(
                chat_id=request.chat_id,
                role="assistant",
                content=f"Извините, не удалось обработать описание изображения. Ошибка: {error_msg}",
                message_type="text"
            )
            db.add(error_message)
            db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка перевода промпта: {error_msg}"
            )
        
        positive_prompt = prompt_result["positive"]
        negative_prompt = prompt_result["negative"]
        
        logger.info(f"✅ Промпты сгенерированы")
        logger.debug(f"   Positive: {positive_prompt[:100]}...")
        logger.debug(f"   Negative: {negative_prompt[:100]}...")
        
        # Шаг 3: Генерируем изображение через ComfyUI с управлением ресурсами
        logger.info(f"🔄 Генерация изображения через ComfyUI...")
        generation_result = await comfyui_service.generate_image(
            prompt=positive_prompt,
            negative_prompt=negative_prompt,
            width=settings.IMAGE_DEFAULT_WIDTH,
            height=settings.IMAGE_DEFAULT_HEIGHT,
            user_id=current_user.id
        )
        
        if not generation_result.get("success"):
            error_msg = generation_result.get("error", "Ошибка генерации изображения")
            logger.error(f"❌ Ошибка генерации изображения: {error_msg}")
            
            # Создаем сообщение об ошибке
            error_message = Message(
                chat_id=request.chat_id,
                role="assistant",
                content=f"Извините, не удалось сгенерировать изображение. Ошибка: {error_msg}",
                message_type="text"
            )
            db.add(error_message)
            db.commit()
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка генерации изображения: {error_msg}"
            )
        
        image_bytes = generation_result["image"]
        filename = generation_result["filename"]
        
        # Шаг 4: Сохраняем изображение
        logger.info(f"🔄 Сохранение изображения...")
        image_url, image_path = image_storage.save_image(image_bytes, filename)
        
        # Шаг 5: Создаем сообщение с изображением в БД
        image_metadata = {
            "prompt_positive": positive_prompt,
            "prompt_negative": negative_prompt,
            "filename": filename,
            "width": settings.IMAGE_DEFAULT_WIDTH,
            "height": settings.IMAGE_DEFAULT_HEIGHT,
            "model": settings.COMFYUI_MODEL
        }
        
        assistant_message = Message(
            chat_id=request.chat_id,
            role="assistant",
            content=f"Изображение сгенерировано на основе описания: {request.description}",
            message_type="image",
            image_url=image_url,
            image_metadata=image_metadata
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)
        
        generation_time = time.time() - start_time
        logger.info(f"✅ Изображение успешно сгенерировано за {generation_time:.2f} секунд")
        
        return ImageGenerationResponse(
            message_id=assistant_message.id,
            image_url=image_url,
            prompt_positive=positive_prompt,
            prompt_negative=negative_prompt,
            generation_time=generation_time,
            success=True
        )
        
    except HTTPException:
        # Пробрасываем HTTP исключения дальше
        raise
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка при генерации изображения: {e}", exc_info=True)
        db.rollback()
        
        # Создаем сообщение об ошибке
        try:
            error_message = Message(
                chat_id=request.chat_id,
                role="assistant",
                content=f"Произошла ошибка при генерации изображения. Пожалуйста, попробуйте позже.",
                message_type="text"
            )
            db.add(error_message)
            db.commit()
        except:
            pass
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@router.post("/generate/stream")
async def generate_image_stream(
    request: ImageGenerationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Генерирует изображение с потоковой передачей прогресса через SSE
    """
    async def generate():
        start_time = time.time()
        
        # Проверяем существование чата
        chat = db.query(Chat).filter(
            Chat.id == request.chat_id,
            Chat.user_id == current_user.id
        ).first()
        
        if not chat:
            yield f"data: {json.dumps({'error': 'Чат не найден', 'done': True})}\n\n"
            return
        
        # Валидация описания
        if not request.description or len(request.description.strip()) == 0:
            yield f"data: {json.dumps({'error': 'Описание изображения не может быть пустым', 'done': True})}\n\n"
            return
        
        try:
            # Шаг 1: Сохраняем сообщение пользователя
            user_message = Message(
                chat_id=request.chat_id,
                role="user",
                content=request.description,
                message_type="text"
            )
            db.add(user_message)
            db.commit()
            db.refresh(user_message)
            
            yield f"data: {json.dumps({'stage': 'translating', 'message': 'Перевод описания в промпт...', 'done': False})}\n\n"
            
            # Шаг 2: Переводим описание в промпты
            prompt_result = await prompt_service.translate_and_enhance_prompt(request.description, user_id=current_user.id)
            
            if not prompt_result.get("success"):
                error_msg = prompt_result.get("error", "Ошибка перевода промпта")
                error_message = Message(
                    chat_id=request.chat_id,
                    role="assistant",
                    content=f"Извините, не удалось обработать описание изображения. Ошибка: {error_msg}",
                    message_type="text"
                )
                db.add(error_message)
                db.commit()
                yield f"data: {json.dumps({'error': error_msg, 'done': True})}\n\n"
                return
            
            positive_prompt = prompt_result["positive"]
            negative_prompt = prompt_result["negative"]
            
            yield f"data: {json.dumps({'stage': 'generating', 'message': 'Генерация изображения...', 'done': False})}\n\n"
            
            # Шаг 3: Генерируем изображение
            generation_result = await comfyui_service.generate_image(
                prompt=positive_prompt,
                negative_prompt=negative_prompt,
                width=settings.IMAGE_DEFAULT_WIDTH,
                height=settings.IMAGE_DEFAULT_HEIGHT,
                user_id=current_user.id
            )
            
            if not generation_result.get("success"):
                error_msg = generation_result.get("error", "Ошибка генерации изображения")
                error_message = Message(
                    chat_id=request.chat_id,
                    role="assistant",
                    content=f"Извините, не удалось сгенерировать изображение. Ошибка: {error_msg}",
                    message_type="text"
                )
                db.add(error_message)
                db.commit()
                yield f"data: {json.dumps({'error': error_msg, 'done': True})}\n\n"
                return
            
            yield f"data: {json.dumps({'stage': 'saving', 'message': 'Сохранение изображения...', 'done': False})}\n\n"
            
            image_bytes = generation_result["image"]
            filename = generation_result["filename"]
            
            # Шаг 4: Сохраняем изображение
            image_url, image_path = image_storage.save_image(image_bytes, filename)
            
            # Шаг 5: Создаем сообщение с изображением
            image_metadata = {
                "prompt_positive": positive_prompt,
                "prompt_negative": negative_prompt,
                "filename": filename,
                "width": settings.IMAGE_DEFAULT_WIDTH,
                "height": settings.IMAGE_DEFAULT_HEIGHT,
                "model": settings.COMFYUI_MODEL
            }
            
            assistant_message = Message(
                chat_id=request.chat_id,
                role="assistant",
                content=f"Изображение сгенерировано на основе описания: {request.description}",
                message_type="image",
                image_url=image_url,
                image_metadata=image_metadata
            )
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)
            
            generation_time = time.time() - start_time
            
            yield f"data: {json.dumps({
                'success': True,
                'message_id': assistant_message.id,
                'image_url': image_url,
                'generation_time': generation_time,
                'done': True
            })}\n\n"
            
        except Exception as e:
            logger.error(f"❌ Ошибка при генерации изображения: {e}", exc_info=True)
            db.rollback()
            try:
                error_message = Message(
                    chat_id=request.chat_id,
                    role="assistant",
                    content=f"Произошла ошибка при генерации изображения. Пожалуйста, попробуйте позже.",
                    message_type="text"
                )
                db.add(error_message)
                db.commit()
            except:
                pass
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/{message_id}")
async def get_image_metadata(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получает метаданные изображения по ID сообщения
    """
    message = db.query(Message).filter(
        Message.id == message_id,
        Message.message_type == "image"
    ).first()
    
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сообщение с изображением не найдено"
        )
    
    # Проверяем права доступа
    chat = db.query(Chat).filter(
        Chat.id == message.chat_id,
        Chat.user_id == current_user.id
    ).first()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к этому изображению"
        )
    
    return {
        "message_id": message.id,
        "image_url": message.image_url,
        "metadata": message.image_metadata,
        "created_at": message.created_at
    }

