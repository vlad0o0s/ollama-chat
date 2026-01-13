"""
Роуты для генерации изображений через ComfyUI
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from pathlib import Path
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


def _check_img2img_available(chat_id: int, db: Session, reference_image_id: Optional[int] = None) -> Optional[Message]:
    """
    Проверяет наличие изображений пользователя в чате для использования в img-to-img режиме
    
    Args:
        chat_id: ID чата
        db: Сессия базы данных
        reference_image_id: Опциональный ID конкретного сообщения с изображением
        
    Returns:
        Message с изображением пользователя или None если не найдено
    """
    if reference_image_id:
        # Если указан конкретный ID, проверяем его
        message = db.query(Message).filter(
            Message.id == reference_image_id,
            Message.chat_id == chat_id,
            Message.role == "user",
            Message.message_type == "image",
            Message.image_url.isnot(None)
        ).first()
        
        if message:
            logger.info(f"✅ Найдено изображение пользователя по ID {reference_image_id}")
            return message
        else:
            logger.warning(f"⚠️ Изображение с ID {reference_image_id} не найдено или недоступно")
            return None
    
    # Ищем последние изображения пользователя в чате (последние 10 сообщений)
    messages = db.query(Message).filter(
        Message.chat_id == chat_id,
        Message.role == "user",
        Message.message_type == "image",
        Message.image_url.isnot(None)
    ).order_by(Message.created_at.desc()).limit(10).all()
    
    if messages:
        # Возвращаем самое последнее изображение
        latest_image = messages[0]
        logger.info(f"✅ Найдено изображение пользователя в чате {chat_id} (message_id: {latest_image.id})")
        return latest_image
    
    logger.debug(f"🔍 Изображения пользователя не найдены в чате {chat_id}")
    return None


class ImageGenerationRequest(BaseModel):
    chat_id: int
    description: str = Field(..., min_length=1, max_length=2000, description="Описание изображения на русском языке")
    width: Optional[int] = Field(None, description="Ширина изображения (если не указано, используется значение по умолчанию)")
    height: Optional[int] = Field(None, description="Высота изображения (если не указано, используется значение по умолчанию)")
    reference_image_id: Optional[int] = Field(None, description="ID сообщения с изображением для img-to-img (опционально)")
    batch_count: Optional[int] = Field(1, ge=1, le=4, description="Количество вариантов для генерации (1-4)")


class ImageGenerationResponse(BaseModel):
    message_id: Optional[int] = None  # Для batch может быть None
    message_ids: Optional[list[int]] = None  # Для batch - список ID сообщений
    image_url: Optional[str] = None  # Для batch может быть None
    image_urls: Optional[list[str]] = None  # Для batch - список URL изображений
    prompt_positive: str
    prompt_negative: str
    generation_time: float
    success: bool
    error: Optional[str] = None
    batch_mode: bool = False  # Флаг batch режима


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
        # Шаг 1: Сохраняем сообщение пользователя только если нет загруженного изображения с описанием
        # Если изображение уже загружено с описанием, сообщение уже создано в /upload
        # Проверяем, есть ли последнее сообщение пользователя с изображением и таким же описанием (за последние 10 секунд)
        from datetime import datetime, timedelta
        time_threshold = datetime.utcnow() - timedelta(seconds=10)
        
        last_user_message = db.query(Message).filter(
            Message.chat_id == request.chat_id,
            Message.role == "user",
            Message.message_type == "image",
            Message.content == request.description,
            Message.created_at >= time_threshold
        ).order_by(Message.created_at.desc()).first()
        
        if not last_user_message:
            # Создаем новое текстовое сообщение
            user_message = Message(
                chat_id=request.chat_id,
                role="user",
                content=request.description,
                message_type="text"
            )
            db.add(user_message)
            db.commit()
            db.refresh(user_message)
        else:
            # Используем существующее сообщение с изображением
            user_message = last_user_message
        
        # Шаг 2: Проверяем наличие изображений пользователя для img-to-img и анализируем их
        reference_image_path = None
        reference_image_bytes = None
        reference_image_filename = None
        ksampler_settings = None
        reference_image_url = None
        image_description = None  # Описание изображения от LLaVA
        source_image_dimensions = None  # Размеры исходного изображения (original, processed)
        llava_time = 0.0  # Время анализа LLaVA
        ksampler_time = 0.0  # Время анализа настроек KSampler
        
        reference_message = _check_img2img_available(
            request.chat_id, 
            db, 
            request.reference_image_id
        )
        
        if reference_message:
            logger.info(f"🔄 Найдено изображение пользователя для img-to-img (message_id: {reference_message.id})")
            reference_image_url = reference_message.image_url
            
            # Загружаем изображение из хранилища
            try:
                # Получаем путь к файлу из URL
                if reference_image_url.startswith("/static/images/"):
                    image_relative_path = reference_image_url.replace("/static/images/", "")
                    image_full_path = Path(settings.IMAGE_STORAGE_PATH) / image_relative_path
                    
                    if image_full_path.exists():
                        with open(image_full_path, "rb") as f:
                            image_bytes = f.read()
                        
                        # Получаем имя файла
                        filename = image_full_path.name
                        
                        # Анализируем изображение через LLaVA (обязательно для img-to-img)
                        logger.info(f"🔄 Анализ изображения через LLaVA...")
                        llava_start_time = time.time()
                        vision_result = await prompt_service.analyze_image_with_vision(
                            image_bytes,
                            user_id=current_user.id
                        )
                        llava_time = time.time() - llava_start_time
                        
                        if vision_result.get("success") and vision_result.get("description"):
                            image_description = vision_result.get("description")
                            logger.info(f"✅ Изображение проанализировано через LLaVA за {llava_time:.2f} секунд")
                            logger.info(f"📝 Описание изображения от LLaVA:\n{image_description}")
                        else:
                            error_msg = vision_result.get("error", "Неизвестная ошибка")
                            logger.error(f"❌ Не удалось проанализировать изображение через LLaVA: {error_msg}")
                            
                            # Создаем сообщение об ошибке
                            error_message = Message(
                                chat_id=request.chat_id,
                                role="assistant",
                                content=f"Извините, не удалось проанализировать загруженное изображение через LLaVA. Ошибка: {error_msg}. Генерация изображения невозможна без анализа исходного изображения.",
                                message_type="text"
                            )
                            db.add(error_message)
                            db.commit()
                            
                            raise HTTPException(
                                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                detail=f"Не удалось проанализировать изображение: {error_msg}"
                            )
                        
                        # Получаем размеры исходного изображения и информацию о сжатии
                        from PIL import Image
                        from io import BytesIO
                        original_image = Image.open(BytesIO(image_bytes))
                        original_width, original_height = original_image.size
                        
                        # Определяем размеры после сжатия (если будет сжато)
                        max_size = settings.IMAGE_MAX_SIZE_FOR_GENERATION
                        max_dimension = max(original_width, original_height)
                        if max_dimension > max_size:
                            if original_width > original_height:
                                processed_width = max_size
                                processed_height = int(original_height * (max_size / original_width))
                            else:
                                processed_height = max_size
                                processed_width = int(original_width * (max_size / original_height))
                        else:
                            processed_width = original_width
                            processed_height = original_height
                        
                        source_image_dimensions = {
                            "original": {"width": original_width, "height": original_height},
                            "processed": {"width": processed_width, "height": processed_height}
                        }
                        logger.info(f"📐 Размеры исходного изображения: оригинал {original_width}x{original_height}, после обработки {processed_width}x{processed_height}")
                        
                        # Сохраняем данные изображения для загрузки ПОСЛЕ переключения процесса на ComfyUI
                        # Загрузка будет выполнена внутри generate_image после того, как ComfyUI станет доступен
                        logger.info(f"🔄 Изображение подготовлено для загрузки в ComfyUI (будет загружено после переключения процесса)")
                        
                        # Передаем данные изображения для загрузки после переключения процесса
                        reference_image_bytes = image_bytes
                        reference_image_filename = filename
                        reference_image_path = None  # Будет установлен после загрузки
                    else:
                        logger.warning(f"⚠️ Файл изображения не найден: {image_full_path}")
                else:
                    logger.warning(f"⚠️ Неподдерживаемый формат URL изображения: {reference_image_url}")
            except Exception as e:
                logger.error(f"❌ Ошибка при подготовке изображения для ComfyUI: {e}", exc_info=True)
                reference_image_bytes = None
                reference_image_filename = None
        
        # Шаг 3: Переводим описание в промпты через Ollama (с учетом описания изображения, если есть)
        logger.info(f"🔄 Перевод описания в промпты для пользователя {current_user.name}")
        prompt_start_time = time.time()
        prompt_result = await prompt_service.translate_and_enhance_prompt(
            request.description, 
            user_id=current_user.id,
            image_description=image_description
        )
        prompt_time = time.time() - prompt_start_time
        
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
        
        logger.info(f"✅ Промпты сгенерированы за {prompt_time:.2f} секунд")
        logger.info(f"📝 Полный positive промпт: {positive_prompt}")
        logger.info(f"📝 Полный negative промпт: {negative_prompt}")
        
        # Шаг 4: Получаем настройки KSampler через LLM (с учетом описания изображения, если есть)
        if reference_image_bytes and reference_image_filename:
            logger.info(f"🔄 Анализ настроек KSampler для img-to-img...")
            ksampler_start_time = time.time()
            ksampler_result = await prompt_service.analyze_img2img_settings(
                request.description,
                user_id=current_user.id,
                image_description=image_description
            )
            ksampler_time = time.time() - ksampler_start_time
            
            if ksampler_result.get("success"):
                ksampler_settings = {
                    "denoise": ksampler_result.get("denoise", 0.6),  # Оптимальное значение для Flux.1-dev (0.55-0.65)
                    "steps": ksampler_result.get("steps", 30),
                    "cfg": ksampler_result.get("cfg", 1.0),
                    "sampler_name": ksampler_result.get("sampler_name", "euler")
                }
                logger.info(f"✅ Настройки KSampler определены за {ksampler_time:.2f} секунд:")
                logger.info(f"   - denoise: {ksampler_settings['denoise']}")
                logger.info(f"   - steps: {ksampler_settings['steps']}")
                logger.info(f"   - cfg: {ksampler_settings['cfg']}")
                logger.info(f"   - sampler_name: {ksampler_settings['sampler_name']}")
                if "seed" in ksampler_settings:
                    logger.info(f"   - seed: {ksampler_settings['seed']}")
            else:
                logger.warning(f"⚠️ Не удалось получить настройки KSampler, используются значения по умолчанию")
        
        # Шаг 5: Генерируем изображение через ComfyUI с управлением ресурсами
        
        # Проверяем наличие данных изображения для img-to-img (будет загружено после переключения процесса)
        mode = "img2img" if (reference_image_bytes and reference_image_filename) else "text2img"
        logger.info(f"🔄 Генерация изображения через ComfyUI (режим: {mode})...")
        
        # Для img-to-img не передаем запрошенные размеры - будут использованы размеры исходного изображения
        # Для text-to-img используем запрошенные размеры или значения по умолчанию
        if mode == "img2img":
            # Для img-to-img размеры будут определены из исходного изображения
            image_width = None  # Будет определено из исходного изображения
            image_height = None
            logger.info(f"📐 Для img-to-img размеры будут определены из исходного изображения")
        else:
            image_width = request.width or settings.IMAGE_DEFAULT_WIDTH
            image_height = request.height or settings.IMAGE_DEFAULT_HEIGHT
        
        # Определяем batch режим
        batch_count = request.batch_count or 1
        batch_mode = batch_count > 1
        
        comfyui_start_time = time.time()
        
        # Генерируем изображения (batch или одиночное)
        generated_images = []
        message_ids = []
        image_urls = []
        
        import random
        
        for batch_idx in range(batch_count):
            logger.info(f"🔄 Генерация варианта {batch_idx + 1}/{batch_count}...")
            
            # Для batch режима генерируем разные seed
            batch_ksampler_settings = ksampler_settings.copy() if ksampler_settings else {}
            if batch_mode:
                # Генерируем случайный seed для каждого варианта
                batch_ksampler_settings["seed"] = random.randint(1, 2**31 - 1)
                logger.info(f"   Используется seed: {batch_ksampler_settings['seed']}")
            
            generation_result = await comfyui_service.generate_image(
                prompt=positive_prompt,
                negative_prompt=negative_prompt,
                width=image_width or settings.IMAGE_DEFAULT_WIDTH,  # Временное значение, будет переопределено для img-to-img
                height=image_height or settings.IMAGE_DEFAULT_HEIGHT,
                user_id=current_user.id,
                reference_image_path=reference_image_path,
                reference_image_bytes=reference_image_bytes,
                reference_image_filename=reference_image_filename,
                ksampler_settings=batch_ksampler_settings if batch_ksampler_settings else None
            )
            
            if not generation_result.get("success"):
                error_msg = generation_result.get("error", "Ошибка генерации изображения")
                logger.error(f"❌ Ошибка генерации варианта {batch_idx + 1}: {error_msg}")
                
                # Для batch режима продолжаем с другими вариантами
                if batch_mode and batch_idx < batch_count - 1:
                    logger.warning(f"⚠️ Пропускаем вариант {batch_idx + 1}, продолжаем генерацию...")
                    continue
                else:
                    # Для одиночного режима или если это последний вариант в batch - возвращаем ошибку
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
            
            # Получаем фактические размеры из результата
            actual_width = generation_result.get("width", image_width or settings.IMAGE_DEFAULT_WIDTH)
            actual_height = generation_result.get("height", image_height or settings.IMAGE_DEFAULT_HEIGHT)
            
            # Получаем seed из результата
            seed_used = generation_result.get("seed")
            
            # Сохраняем изображение
            logger.info(f"🔄 Сохранение изображения варианта {batch_idx + 1}...")
            image_url, image_path = image_storage.save_image(image_bytes, filename)
            image_urls.append(image_url)
            
            # Создаем метаданные для изображения
            image_metadata = {
                "prompt_positive": positive_prompt,
                "prompt_negative": negative_prompt,
                "filename": filename,
                "width": actual_width,
                "height": actual_height,
                "model": settings.COMFYUI_MODEL,
                "mode": generation_result.get("mode", "text2img"),
                "reference_image_url": reference_image_url,
                "batch_index": batch_idx if batch_mode else None,
                "batch_total": batch_count if batch_mode else None
            }
            
            # Сохраняем seed для воспроизводимости
            if seed_used is not None:
                image_metadata["seed"] = seed_used
            
            # Добавляем информацию о размерах исходного изображения для img-to-img
            if mode == "img2img" and source_image_dimensions:
                image_metadata["source_image_dimensions"] = source_image_dimensions
            
            if batch_ksampler_settings:
                image_metadata["ksampler_settings"] = batch_ksampler_settings
                if "seed" in batch_ksampler_settings:
                    image_metadata["seed"] = batch_ksampler_settings["seed"]
            
            # Добавляем описание изображения от LLaVA в метаданные
            if image_description:
                image_metadata["llava_analysis"] = image_description
            
            # Создаем сообщение с изображением в БД
            assistant_message = Message(
                chat_id=request.chat_id,
                role="assistant",
                content="",  # Пустой контент - только изображение
                message_type="image",
                image_url=image_url,
                image_metadata=image_metadata
            )
            db.add(assistant_message)
            db.commit()
            db.refresh(assistant_message)
            
            message_ids.append(assistant_message.id)
            generated_images.append(assistant_message)
        
        comfyui_time = time.time() - comfyui_start_time
        generation_time = time.time() - start_time
        
        logger.info(f"✅ {'Изображения' if batch_mode else 'Изображение'} успешно {'сгенерированы' if batch_mode else 'сгенерировано'} ({len(generated_images)}/{batch_count})")
        logger.info(f"⏱️ Метрики времени выполнения:")
        if mode == "img2img" and llava_time > 0:
            logger.info(f"   - Анализ LLaVA: {llava_time:.2f} секунд")
        logger.info(f"   - Генерация промптов: {prompt_time:.2f} секунд")
        if mode == "img2img" and ksampler_time > 0:
            logger.info(f"   - Анализ настроек KSampler: {ksampler_time:.2f} секунд")
        logger.info(f"   - Генерация в ComfyUI: {comfyui_time:.2f} секунд")
        logger.info(f"   - Общее время: {generation_time:.2f} секунд")
        
        # Формируем ответ в зависимости от режима
        if batch_mode:
            return ImageGenerationResponse(
                message_ids=message_ids,
                image_urls=image_urls,
                prompt_positive=positive_prompt,
                prompt_negative=negative_prompt,
                generation_time=generation_time,
                success=True,
                batch_mode=True
            )
        else:
            return ImageGenerationResponse(
                message_id=message_ids[0] if message_ids else None,
                image_url=image_urls[0] if image_urls else None,
                prompt_positive=positive_prompt,
                prompt_negative=negative_prompt,
                generation_time=generation_time,
                success=True,
                batch_mode=False
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
            # Шаг 1: Сохраняем сообщение пользователя только если нет загруженного изображения с описанием
            # Если изображение уже загружено с описанием, сообщение уже создано в /upload
            from datetime import datetime, timedelta
            time_threshold = datetime.utcnow() - timedelta(seconds=10)
            
            last_user_message = db.query(Message).filter(
                Message.chat_id == request.chat_id,
                Message.role == "user",
                Message.message_type == "image",
                Message.content == request.description,
                Message.created_at >= time_threshold
            ).order_by(Message.created_at.desc()).first()
            
            if not last_user_message:
                # Создаем новое текстовое сообщение
                user_message = Message(
                    chat_id=request.chat_id,
                    role="user",
                    content=request.description,
                    message_type="text"
                )
                db.add(user_message)
                db.commit()
                db.refresh(user_message)
            else:
                # Используем существующее сообщение с изображением
                user_message = last_user_message
            
            # Шаг 2: Проверяем наличие изображений пользователя для img-to-img и анализируем их
            reference_image_path = None
            reference_image_bytes = None
            reference_image_filename = None
            ksampler_settings = None
            reference_image_url = None
            image_description = None  # Описание изображения от LLaVA
            source_image_dimensions = None  # Размеры исходного изображения (original, processed)
            
            reference_message = _check_img2img_available(
                request.chat_id, 
                db, 
                request.reference_image_id
            )
            
            if reference_message:
                yield f"data: {json.dumps({'stage': 'analyzing_image', 'message': 'Анализ изображения через LLaVA...', 'done': False})}\n\n"
                logger.info(f"🔄 Найдено изображение пользователя для img-to-img (message_id: {reference_message.id})")
                reference_image_url = reference_message.image_url
                
                # Загружаем изображение из хранилища
                try:
                    if reference_image_url.startswith("/static/images/"):
                        image_relative_path = reference_image_url.replace("/static/images/", "")
                        image_full_path = Path(settings.IMAGE_STORAGE_PATH) / image_relative_path
                        
                        if image_full_path.exists():
                            with open(image_full_path, "rb") as f:
                                image_bytes = f.read()
                            
                            filename = image_full_path.name
                            
                            # Анализируем изображение через LLaVA (обязательно для img-to-img)
                            vision_result = await prompt_service.analyze_image_with_vision(
                                image_bytes,
                                user_id=current_user.id
                            )
                            
                            if vision_result.get("success") and vision_result.get("description"):
                                image_description = vision_result.get("description")
                                logger.info(f"✅ Изображение проанализировано через LLaVA")
                                logger.info(f"📝 Описание изображения от LLaVA:\n{image_description}")
                                
                                # Отправляем описание через SSE
                                yield f"data: {json.dumps({'stage': 'image_analyzed', 'message': 'Изображение проанализировано', 'description': image_description, 'done': False})}\n\n"
                            else:
                                error_msg = vision_result.get("error", "Неизвестная ошибка")
                                logger.error(f"❌ Не удалось проанализировать изображение через LLaVA: {error_msg}")
                                
                                # Создаем сообщение об ошибке
                                error_message = Message(
                                    chat_id=request.chat_id,
                                    role="assistant",
                                    content=f"Извините, не удалось проанализировать загруженное изображение через LLaVA. Ошибка: {error_msg}. Генерация изображения невозможна без анализа исходного изображения.",
                                    message_type="text"
                                )
                                db.add(error_message)
                                db.commit()
                                
                                yield f"data: {json.dumps({'error': f'Не удалось проанализировать изображение: {error_msg}', 'done': True})}\n\n"
                                return
                            
                            # Получаем размеры исходного изображения и информацию о сжатии
                            from PIL import Image
                            from io import BytesIO
                            original_image = Image.open(BytesIO(image_bytes))
                            original_width, original_height = original_image.size
                            
                            # Определяем размеры после сжатия (если будет сжато)
                            max_size = settings.IMAGE_MAX_SIZE_FOR_GENERATION
                            max_dimension = max(original_width, original_height)
                            if max_dimension > max_size:
                                if original_width > original_height:
                                    processed_width = max_size
                                    processed_height = int(original_height * (max_size / original_width))
                                else:
                                    processed_height = max_size
                                    processed_width = int(original_width * (max_size / original_height))
                            else:
                                processed_width = original_width
                                processed_height = original_height
                            
                            source_image_dimensions = {
                                "original": {"width": original_width, "height": original_height},
                                "processed": {"width": processed_width, "height": processed_height}
                            }
                            logger.info(f"📐 Размеры исходного изображения: оригинал {original_width}x{original_height}, после обработки {processed_width}x{processed_height}")
                            
                            # Сохраняем данные изображения для загрузки ПОСЛЕ переключения процесса на ComfyUI
                            # Загрузка будет выполнена внутри generate_image после того, как ComfyUI станет доступен
                            logger.info(f"🔄 Изображение подготовлено для загрузки в ComfyUI (будет загружено после переключения процесса)")
                            
                            # Передаем данные изображения для загрузки после переключения процесса
                            reference_image_bytes = image_bytes
                            reference_image_filename = filename
                            reference_image_path = None  # Будет установлен после загрузки
                        else:
                            logger.warning(f"⚠️ Файл изображения не найден: {image_full_path}")
                    else:
                        logger.warning(f"⚠️ Неподдерживаемый формат URL изображения: {reference_image_url}")
                except Exception as e:
                    logger.error(f"❌ Ошибка при подготовке изображения для ComfyUI: {e}", exc_info=True)
                    reference_image_bytes = None
                    reference_image_filename = None
            
            # Шаг 3: Переводим описание в промпты через Ollama (с учетом описания изображения, если есть)
            yield f"data: {json.dumps({'stage': 'translating', 'message': 'Перевод описания в промпт...', 'done': False})}\n\n"
            
            prompt_result = await prompt_service.translate_and_enhance_prompt(
                request.description, 
                user_id=current_user.id,
                image_description=image_description
            )
            
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
            
            # Шаг 4: Получаем настройки KSampler через LLM (с учетом описания изображения, если есть)
            if reference_image_bytes and reference_image_filename:
                yield f"data: {json.dumps({'stage': 'analyzing_settings', 'message': 'Анализ настроек генерации...', 'done': False})}\n\n"
                
                ksampler_result = await prompt_service.analyze_img2img_settings(
                    request.description,
                    user_id=current_user.id,
                    image_description=image_description
                )
                
                if ksampler_result.get("success"):
                    ksampler_settings = {
                        "denoise": ksampler_result.get("denoise", 0.5),
                        "steps": ksampler_result.get("steps", 30),
                        "cfg": ksampler_result.get("cfg", 1.0),
                        "sampler_name": ksampler_result.get("sampler_name", "euler")
                    }
                    logger.info(f"✅ Настройки KSampler определены: {ksampler_settings}")
                else:
                    logger.warning(f"⚠️ Не удалось получить настройки KSampler, используются значения по умолчанию")
            
            mode = "img2img" if (reference_image_bytes and reference_image_filename) else "text2img"
            yield f"data: {json.dumps({'stage': 'generating', 'message': f'Генерация изображения ({mode})...', 'done': False})}\n\n"
            
            # Шаг 5: Генерируем изображение
            # Для img-to-img не передаем запрошенные размеры - будут использованы размеры исходного изображения
            if mode == "img2img":
                image_width = None
                image_height = None
                logger.info(f"📐 Для img-to-img размеры будут определены из исходного изображения")
            else:
                image_width = request.width or settings.IMAGE_DEFAULT_WIDTH
                image_height = request.height or settings.IMAGE_DEFAULT_HEIGHT
            
            generation_result = await comfyui_service.generate_image(
                prompt=positive_prompt,
                negative_prompt=negative_prompt,
                width=image_width or settings.IMAGE_DEFAULT_WIDTH,  # Временное значение, будет переопределено для img-to-img
                height=image_height or settings.IMAGE_DEFAULT_HEIGHT,
                user_id=current_user.id,
                reference_image_path=reference_image_path,
                reference_image_bytes=reference_image_bytes,
                reference_image_filename=reference_image_filename,
                ksampler_settings=ksampler_settings
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
            
            # Получаем фактические размеры из результата (для img-to-img это размеры исходного изображения)
            actual_width = generation_result.get("width", image_width or settings.IMAGE_DEFAULT_WIDTH)
            actual_height = generation_result.get("height", image_height or settings.IMAGE_DEFAULT_HEIGHT)
            
            # Получаем seed из результата
            seed_used = generation_result.get("seed")
            
            # Шаг 5: Сохраняем изображение
            image_url, image_path = image_storage.save_image(image_bytes, filename)
            
            # Шаг 6: Создаем сообщение с изображением
            image_metadata = {
                "prompt_positive": positive_prompt,
                "prompt_negative": negative_prompt,
                "filename": filename,
                "width": actual_width,
                "height": actual_height,
                "model": settings.COMFYUI_MODEL,
                "mode": generation_result.get("mode", "text2img"),
                "reference_image_url": reference_image_url
            }
            
            # Сохраняем seed для воспроизводимости
            if seed_used is not None:
                image_metadata["seed"] = seed_used
            
            if ksampler_settings:
                image_metadata["ksampler_settings"] = ksampler_settings
                # Если seed был в настройках, он уже сохранен выше, но можно также сохранить в ksampler_settings
                if "seed" in ksampler_settings:
                    image_metadata["seed"] = ksampler_settings["seed"]
            
            # Добавляем описание изображения от LLaVA в метаданные
            if image_description:
                image_metadata["llava_analysis"] = image_description
            
            # Добавляем информацию о размерах исходного изображения для img-to-img
            if mode == "img2img" and source_image_dimensions:
                image_metadata["source_image_dimensions"] = source_image_dimensions
            
            assistant_message = Message(
                chat_id=request.chat_id,
                role="assistant",
                content="",  # Пустой контент - только изображение
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


@router.post("/upload")
async def upload_image(
    chat_id: int = Form(...),
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загружает изображение пользователем для использования в img-to-img генерации
    
    Args:
        chat_id: ID чата, в который загружается изображение
        file: Файл изображения (JPEG, PNG, WEBP)
        description: Описание изображения (опционально, будет добавлено в сообщение)
        
    Returns:
        {
            "message_id": int,
            "image_url": str,
            "success": bool
        }
    """
    # Проверяем существование чата и прав доступа
    chat = db.query(Chat).filter(
        Chat.id == chat_id,
        Chat.user_id == current_user.id
    ).first()
    
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Чат не найден"
        )
    
    # Проверяем тип файла
    allowed_content_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    if file.content_type not in allowed_content_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неподдерживаемый тип файла. Разрешены: {', '.join(allowed_content_types)}"
        )
    
    try:
        # Читаем содержимое файла
        image_bytes = await file.read()
        
        if len(image_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Файл пустой"
            )
        
        # Проверяем максимальный размер (например, 10MB)
        max_size = 10 * 1024 * 1024  # 10MB
        if len(image_bytes) > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Файл слишком большой. Максимальный размер: {max_size // (1024 * 1024)}MB"
            )
        
        # Валидируем изображение
        from PIL import Image
        from io import BytesIO
        validation = comfyui_service._validate_image(image_bytes)
        if not validation["valid"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Изображение не прошло валидацию: {validation['error']}"
            )
        
        # Получаем размеры изображения
        try:
            image = Image.open(BytesIO(image_bytes))
            original_width, original_height = image.size
            
            # Определяем размеры после сжатия (если будет сжато при генерации)
            max_size = settings.IMAGE_MAX_SIZE_FOR_GENERATION
            max_dimension = max(original_width, original_height)
            if max_dimension > max_size:
                if original_width > original_height:
                    processed_width = max_size
                    processed_height = int(original_height * (max_size / original_width))
                else:
                    processed_height = max_size
                    processed_width = int(original_width * (max_size / original_height))
            else:
                processed_width = original_width
                processed_height = original_height
            
            dimensions_info = {
                "original": {"width": original_width, "height": original_height},
                "processed": {"width": processed_width, "height": processed_height}
            }
        except Exception as e:
            logger.warning(f"⚠️ Не удалось определить размеры изображения: {e}")
            dimensions_info = None
        
        # Сохраняем изображение
        logger.info(f"🔄 Загрузка изображения пользователем {current_user.name} в чат {chat_id}")
        image_url, image_path = image_storage.save_image(image_bytes, file.filename)
        
        # Создаем сообщение с изображением и описанием (если есть)
        metadata = {
            "filename": file.filename,
            "content_type": file.content_type,
            "size": len(image_bytes),
            "uploaded_by": current_user.id
        }
        
        if dimensions_info:
            metadata["dimensions"] = dimensions_info
        
        user_message = Message(
            chat_id=chat_id,
            role="user",
            content=description or "",  # Описание, если указано
            message_type="image",
            image_url=image_url,
            image_metadata=metadata
        )
        db.add(user_message)
        db.commit()
        db.refresh(user_message)
        
        logger.info(f"✅ Изображение успешно загружено: {image_url}")
        
        return {
            "message_id": user_message.id,
            "image_url": image_url,
            "success": True
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка при загрузке изображения: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка при загрузке изображения: {str(e)}"
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

