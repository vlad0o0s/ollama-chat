"""
Сервис для управления процессами Ollama и ComfyUI через Process Management API
"""
import httpx
import asyncio
import logging
from typing import Optional, Dict
from ..config import settings
from .service_types import ServiceType

logger = logging.getLogger(__name__)


class ProcessManagerService:
    """Сервис для управления процессами через Process Management API"""
    
    def __init__(self):
        """Инициализация сервиса"""
        self.api_url = settings.PROCESS_MANAGER_API_URL
        self.switch_timeout = settings.PROCESS_SWITCH_TIMEOUT
        self.startup_wait = settings.PROCESS_STARTUP_WAIT
        self.restore_on_release = settings.PROCESS_RESTORE_ON_RELEASE
        
        # Отслеживание состояния
        self._previous_service: Optional[ServiceType] = None
        self._current_service: Optional[ServiceType] = None
        self._service_before_request: Optional[ServiceType] = None
        
        if not self.api_url:
            logger.warning("⚠️ PROCESS_MANAGER_API_URL не установлен, управление процессами отключено")
        else:
            logger.info(f"✅ Process Management API настроен: {self.api_url}")
    
    async def check_api_available(self) -> bool:
        """Проверяет доступность Process Management API"""
        if not self.api_url:
            logger.warning("⚠️ PROCESS_MANAGER_API_URL не установлен")
            return False
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.api_url}/")
                if response.status_code == 200:
                    return True
                else:
                    logger.warning(f"⚠️ Process Management API вернул статус {response.status_code}")
                    return False
        except httpx.ConnectError as e:
            logger.warning(f"⚠️ Не удалось подключиться к Process Management API на {self.api_url}: {e}")
            return False
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки Process Management API: {e}")
            return False
    
    async def get_status(self) -> Optional[Dict]:
        """Получает статус процессов"""
        if not self.api_url:
            return None
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.api_url}/process/status")
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.warning(f"Ошибка получения статуса: {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Ошибка получения статуса процессов: {e}")
            return None
    
    async def get_current_service(self) -> Optional[ServiceType]:
        """Получает текущий активный сервис"""
        status = await self.get_status()
        if not status:
            return None
        
        current = status.get("current_service")
        if current == "ollama":
            return ServiceType.OLLAMA
        elif current == "comfyui":
            return ServiceType.COMFYUI
        else:
            return None
    
    async def switch_to_service(self, service_type: ServiceType, force_restart: bool = False) -> bool:
        """
        Переключает на указанный сервис
        
        Args:
            service_type: Тип сервиса для переключения
            force_restart: Если True, принудительно перезапускает сервис (даже если уже активен)
                          Используется для смены модели в Ollama (например, gpt-oss -> llava)
            
        Returns:
            True если переключение успешно, False в противном случае
        """
        if not self.api_url:
            logger.warning("⚠️ Process Management API недоступен, пропускаем переключение")
            # Fallback: проверяем доступность сервиса напрямую
            return await self.check_service_available(service_type)
        
        # Проверяем доступность API
        if not await self.check_api_available():
            logger.warning("⚠️ Process Management API недоступен, используем fallback")
            # Fallback: проверяем доступность сервиса напрямую
            return await self.check_service_available(service_type)
        
        # Сохраняем текущий сервис перед переключением
        if not self._service_before_request:
            self._service_before_request = await self.get_current_service()
        
        # Проверяем текущий активный сервис через Process Manager API
        current_active_service = await self.get_current_service()
        
        # Если нужный сервис уже активен и доступен, и не требуется принудительный перезапуск
        if current_active_service == service_type and not force_restart:
            logger.info(f"✅ {service_type.value} уже активен, проверяем доступность...")
            if await self.check_service_available(service_type):
                # Обновляем внутреннее состояние
                self._current_service = service_type
                logger.info(f"✅ {service_type.value} активен и доступен, пропускаем переключение")
                return True
            else:
                logger.warning(f"⚠️ {service_type.value} активен, но недоступен, требуется перезапуск...")
        elif force_restart and current_active_service == service_type:
            logger.info(f"🔄 Принудительный перезапуск {service_type.value} (для смены модели)...")
        
        try:
            service_name = service_type.value
            logger.info(f"🔄 Переключение на {service_name}...")
            
            # Если требуется принудительный перезапуск, сначала останавливаем сервис
            if force_restart and service_type == ServiceType.OLLAMA:
                logger.info(f"🛑 Принудительная остановка Ollama перед перезапуском (для смены модели)...")
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        stop_response = await client.post(
                            f"{self.api_url}/process/stop",
                            params={"service": "ollama"}
                        )
                        if stop_response.status_code == 200:
                            logger.info(f"✅ Ollama остановлен, ожидание освобождения VRAM...")
                            await asyncio.sleep(3)  # Даем время на освобождение VRAM
                            # Сбрасываем текущий сервис, чтобы гарантировать перезапуск
                            self._current_service = None
                        else:
                            logger.warning(f"⚠️ Не удалось остановить Ollama перед перезапуском: {stop_response.status_code}")
                except Exception as stop_error:
                    logger.warning(f"⚠️ Ошибка при остановке Ollama перед перезапуском: {stop_error}")
                    # Продолжаем переключение, возможно процесс уже остановлен
            
            async with httpx.AsyncClient(timeout=self.switch_timeout) as client:
                response = await client.post(
                    f"{self.api_url}/process/switch",
                    params={"service": service_name}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    switch_time = result.get("switch_time", 0)
                    logger.info(f"✅ Переключено на {service_name} за {switch_time:.2f}s")
                    
                    # Обновляем состояние
                    self._previous_service = self._current_service
                    self._current_service = service_type
                    
                    # Ждем готовности сервиса (увеличено время ожидания для надежности)
                    service_ready = await self._wait_for_service_ready(service_type, max_wait=45)
                    if not service_ready:
                        logger.warning(f"⚠️ {service_name} переключен, но не готов после ожидания")
                        # Даем дополнительное время на инициализацию
                        logger.info(f"⏳ Дополнительное ожидание инициализации {service_name} (5 секунд)...")
                        await asyncio.sleep(5)
                        # Проверяем еще раз
                        if await self.check_service_available(service_type):
                            logger.info(f"✅ {service_name} стал доступен после дополнительного ожидания")
                        else:
                            logger.warning(f"⚠️ {service_name} все еще недоступен, но продолжаем работу")
                    
                    return True
                else:
                    error_msg = response.text
                    logger.error(f"❌ Ошибка переключения на {service_name}: {error_msg}")
                    # Fallback: проверяем, может сервис уже доступен
                    if await self.check_service_available(service_type):
                        logger.info(f"✅ {service_name} уже доступен, используем его")
                        self._current_service = service_type
                        return True
                    return False
                    
        except httpx.TimeoutException:
            logger.error(f"❌ Таймаут переключения на {service_type.value}")
            # Fallback: проверяем доступность сервиса
            if await self.check_service_available(service_type):
                logger.info(f"✅ {service_type.value} доступен после таймаута")
                self._current_service = service_type
                return True
            return False
        except httpx.ConnectError:
            logger.error(f"❌ Не удалось подключиться к Process Management API")
            # Fallback: проверяем доступность сервиса напрямую
            if await self.check_service_available(service_type):
                logger.info(f"✅ {service_type.value} доступен, используем fallback")
                self._current_service = service_type
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка переключения процесса: {e}")
            # Fallback: проверяем доступность сервиса
            if await self.check_service_available(service_type):
                logger.info(f"✅ {service_type.value} доступен, используем fallback")
                self._current_service = service_type
                return True
            return False
    
    async def _wait_for_service_ready(self, service_type: ServiceType, max_wait: int = 30) -> bool:
        """
        Ожидает готовности сервиса после запуска
        
        Args:
            service_type: Тип сервиса
            max_wait: Максимальное время ожидания в секундах
            
        Returns:
            True если сервис готов, False при таймауте
        """
        start_time = asyncio.get_event_loop().time()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= max_wait:
                logger.warning(f"⚠️ Таймаут ожидания готовности {service_type.value}")
                return False
            
            # Проверяем доступность сервиса
            if service_type == ServiceType.OLLAMA:
                available = await self._check_ollama_available()
            elif service_type == ServiceType.COMFYUI:
                available = await self._check_comfyui_available()
            else:
                return True  # Для других типов считаем готовым
            
            if available:
                logger.info(f"✅ {service_type.value} готов (ожидание: {elapsed:.1f}s)")
                return True
            
            await asyncio.sleep(2)
    
    async def _check_ollama_available(self) -> bool:
        """Проверяет доступность Ollama API"""
        try:
            # При использовании Process Manager Ollama запускается локально на 127.0.0.1:11434
            # Используем localhost вместо внешнего IP из настроек
            ollama_url = "http://127.0.0.1:11434"
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{ollama_url}/api/tags")
                return response.status_code == 200
        except:
            return False
    
    async def _check_comfyui_available(self) -> bool:
        """Проверяет доступность ComfyUI API"""
        try:
            from ..config import settings
            # Определяем URL ComfyUI (приоритет локальному, если Process Manager активен)
            comfyui_url = "http://127.0.0.1:8188"
            if settings.COMFYUI_URL:
                comfyui_url = settings.COMFYUI_URL
            elif await self.check_api_available():
                # Если Process Manager активен, используем локальный URL
                comfyui_url = "http://127.0.0.1:8188"
            
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{comfyui_url}/system_stats")
                return response.status_code == 200
        except:
            return False
    
    async def restore_previous_service(self) -> bool:
        """
        Восстанавливает предыдущий сервис (если был активен до запроса)
        
        Returns:
            True если восстановление успешно или не требуется
        """
        if not self.restore_on_release:
            return True
        
        if not self._service_before_request:
            return True
        
        # Если текущий сервис совпадает с предыдущим, ничего не делаем
        if self._current_service == self._service_before_request:
            self._service_before_request = None
            return True
        
        logger.info(f"🔄 Восстановление предыдущего сервиса: {self._service_before_request.value}")
        try:
            success = await self.switch_to_service(self._service_before_request)
            
            if success:
                self._service_before_request = None
            else:
                logger.warning(f"⚠️ Не удалось восстановить {self._service_before_request.value}")
            
            return success
        except Exception as e:
            logger.error(f"❌ Ошибка восстановления процесса: {e}")
            # Не критично, продолжаем работу
            return False
    
    async def check_service_available(self, service_type: ServiceType) -> bool:
        """
        Проверяет доступность указанного сервиса
        
        Args:
            service_type: Тип сервиса
            
        Returns:
            True если сервис доступен
        """
        if service_type == ServiceType.OLLAMA:
            return await self._check_ollama_available()
        elif service_type == ServiceType.COMFYUI:
            return await self._check_comfyui_available()
        else:
            return False
    
    async def ensure_ollama_active(self) -> bool:
        """
        Явно переключается на Ollama (используется после освобождения ComfyUI)
        
        Returns:
            True если переключение успешно
        """
        logger.info("🔄 Принудительное переключение на Ollama...")
        try:
            success = await self.switch_to_service(ServiceType.OLLAMA)
            if success:
                logger.info("✅ Ollama активирован")
                # Сбрасываем _service_before_request, так как это явное переключение
                self._service_before_request = None
            return success
        except Exception as e:
            logger.error(f"❌ Ошибка принудительного переключения на Ollama: {e}")
            return False


# Глобальный экземпляр сервиса
process_manager_service = ProcessManagerService()

