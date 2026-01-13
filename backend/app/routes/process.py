"""
Роуты для управления процессами (Ollama/ComfyUI)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Optional
from ..database import get_db
from ..models.user import User
from ..auth.dependencies import get_current_user
from ..services.process_manager_service import process_manager_service
from ..services.service_types import ServiceType
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/process", tags=["process-management"])


class SwitchResponse(BaseModel):
    """Ответ на переключение процесса"""
    success: bool
    message: str
    previous_service: Optional[str] = None
    current_service: Optional[str] = None


@router.post("/switch", response_model=SwitchResponse)
async def switch_process(
    service: str = Query(..., description="Тип сервиса для переключения: 'ollama' или 'comfyui'"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Переключает на указанный сервис (Ollama или ComfyUI)
    """
    try:
        # Валидация типа сервиса
        if service.lower() == "ollama":
            service_type = ServiceType.OLLAMA
        elif service.lower() == "comfyui":
            service_type = ServiceType.COMFYUI
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неизвестный тип сервиса. Используйте 'ollama' или 'comfyui'"
            )
        
        logger.info(f"🔄 Запрос на переключение на {service_type.value} от пользователя {current_user.name}")
        
        # Если пытаемся переключиться на Ollama, проверяем, не активен ли ComfyUI
        if service_type == ServiceType.OLLAMA:
            status_data = await process_manager_service.get_status()
            if status_data and status_data.get('comfyui') and status_data['comfyui'].get('running'):
                logger.warning("⚠️ ComfyUI активен, переключение на Ollama отменено, чтобы не прервать работу ComfyUI")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="ComfyUI активен. Переключение на Ollama отменено, чтобы не прервать работу ComfyUI"
                )
        
        # Получаем текущий сервис перед переключением
        previous_service = await process_manager_service.get_current_service()
        previous_service_name = previous_service.value if previous_service else None
        
        # Переключаем сервис
        success = await process_manager_service.switch_to_service(service_type)
        
        if success:
            current_service_name = service_type.value
            logger.info(f"✅ Успешно переключено на {current_service_name}")
            return SwitchResponse(
                success=True,
                message=f"Переключено на {current_service_name}",
                previous_service=previous_service_name,
                current_service=current_service_name
            )
        else:
            logger.error(f"❌ Не удалось переключиться на {service_type.value}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Не удалось переключиться на {service_type.value}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка переключения процесса: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка переключения процесса: {str(e)}"
        )


@router.get("/status")
async def get_process_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получает статус процессов
    """
    try:
        status_data = await process_manager_service.get_status()
        current_service = await process_manager_service.get_current_service()
        
        return {
            "status": status_data,
            "current_service": current_service.value if current_service else None
        }
    except Exception as e:
        logger.error(f"❌ Ошибка получения статуса процессов: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка получения статуса: {str(e)}"
        )

