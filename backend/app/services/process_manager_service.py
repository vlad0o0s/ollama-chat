"""
Сервис для управления процессами Ollama и ComfyUI через Process Management API
"""
import httpx
import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Dict
from ..config import settings
from .service_types import ServiceType

logger = logging.getLogger(__name__)

def _log_with_time(level: str, message: str, elapsed: Optional[float] = None):
    """Логирует сообщение с временной меткой и опциональным временем выполнения"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # HH:MM:SS.mmm
    if elapsed is not None:
        logger.log(getattr(logging, level.upper()), f"[{timestamp}] [{elapsed:.2f}s] {message}")
    else:
        logger.log(getattr(logging, level.upper()), f"[{timestamp}] {message}")


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
                # Новый API использует /health вместо /process/status
                response = await client.get(f"{self.api_url}/health")
                if response.status_code == 200:
                    data = response.json()
                    # Преобразуем формат ответа нового API в старый формат для совместимости
                    services = data.get("services", {})
                    # Новый API не управляет Ollama/ComfyUI, поэтому возвращаем пустой статус
                    # но проверяем доступность Ollama напрямую
                    ollama_available = await self._check_ollama_available()
                    comfyui_available = await self._check_comfyui_available()
                    
                    return {
                        "ollama": {
                            "running": ollama_available,
                            "pid": None  # Новый API не отслеживает Ollama
                        },
                        "comfyui": {
                            "running": comfyui_available,
                            "pid": None  # Новый API не отслеживает ComfyUI
                        }
                    }
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
        # Это нужно для восстановления после завершения работы с GPU
        # ВАЖНО: При переключении на ComfyUI всегда сохраняем текущий сервис (Ollama),
        # чтобы после ComfyUI вернуться к Ollama
        current = await self.get_current_service()
        
        # Если переключаемся на ComfyUI, всегда обновляем _service_before_request на текущий сервис
        # (чтобы после ComfyUI вернуться к Ollama)
        if service_type == ServiceType.COMFYUI and current:
            self._service_before_request = current
            logger.debug(f"💾 Сохранен текущий сервис ({current.value}) перед переключением на ComfyUI")
        # Если _service_before_request еще не установлен, сохраняем текущий сервис
        elif not self._service_before_request:
            self._service_before_request = current
            if current:
                logger.debug(f"💾 Сохранен предыдущий сервис для восстановления: {current.value}")
            else:
                # Если текущий сервис не определен, предполагаем что это Ollama (по умолчанию)
                logger.debug(f"💾 Текущий сервис не определен, предполагаем Ollama по умолчанию")
                self._service_before_request = ServiceType.OLLAMA
        
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
            switch_start_time = time.time()
            service_name = service_type.value
            _log_with_time("info", f"🔄 Переключение на {service_name}...")
            
            # Если требуется принудительный перезапуск, сначала останавливаем сервис
            if force_restart and service_type == ServiceType.OLLAMA:
                logger.info(f"🛑 Принудительная остановка Ollama перед перезапуском (для смены модели)...")
                try:
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        stop_response = await client.post(
                            f"{self.api_url}/stop/ollama"
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
            
            # Новый Process Manager API не управляет Ollama/ComfyUI напрямую
            # Вместо этого проверяем доступность и запускаем напрямую, если нужно
            if service_type == ServiceType.OLLAMA:
                # Проверяем доступность Ollama
                if await self._check_ollama_available():
                    elapsed = time.time() - switch_start_time
                    _log_with_time("info", f"✅ Ollama уже доступен", elapsed)
                    self._current_service = service_type
                    return True
                
                # Если Ollama недоступна, пытаемся запустить через Process Manager API
                if await self.check_api_available():
                    try:
                        async with httpx.AsyncClient(timeout=15.0) as client:
                            start_response = await client.post(
                                f"{self.api_url}/process/start",
                                params={"service": "ollama"}
                            )
                            if start_response.status_code == 200:
                                elapsed = time.time() - switch_start_time
                                _log_with_time("info", "✅ Запрос на запуск Ollama отправлен", elapsed)
                            else:
                                elapsed = time.time() - switch_start_time
                                _log_with_time("warning", f"⚠️ Не удалось запустить Ollama через API: {start_response.status_code}", elapsed)
                    except Exception as e:
                        elapsed = time.time() - switch_start_time
                        _log_with_time("warning", f"⚠️ Ошибка запуска Ollama через API: {e}", elapsed)
                
                # Если Ollama недоступна, ждем некоторое время (она может запускаться)
                elapsed = time.time() - switch_start_time
                _log_with_time("info", f"🔄 Ollama недоступна, ожидаем запуска (до 30 секунд)...", elapsed)
                max_wait = 30
                waited = 0
                check_interval = 2
                
                while waited < max_wait:
                    await asyncio.sleep(check_interval)
                    waited += check_interval
                    
                    if await self._check_ollama_available():
                        elapsed = time.time() - switch_start_time
                        _log_with_time("info", f"✅ Ollama стала доступна (ожидание: {waited}s)", elapsed)
                        self._current_service = service_type
                        return True
                    
                    if waited % 10 == 0:
                        elapsed = time.time() - switch_start_time
                        _log_with_time("info", f"⏳ Ожидание Ollama... ({waited}s/{max_wait}s)", elapsed)
                
                elapsed = time.time() - switch_start_time
                _log_with_time("warning", f"⚠️ Ollama все еще недоступна после ожидания {max_wait}s", elapsed)
                # Все равно возвращаем True, чтобы пользователь мог попробовать отправить сообщение
                # (возможно, Ollama запустится позже)
                self._current_service = service_type
                return True
            elif service_type == ServiceType.COMFYUI:
                start_time = time.time()
                # Для ComfyUI нужно сначала остановить Ollama, чтобы освободить VRAM
                # Проверяем, запущена ли Ollama
                ollama_running = await self._check_ollama_available()
                
                # Проверяем доступность ComfyUI ПЕРЕД остановкой Ollama (может быть уже запущен)
                if await self._check_comfyui_available():
                    elapsed = time.time() - start_time
                    _log_with_time("info", f"✅ ComfyUI уже доступен", elapsed)
                    # Если ComfyUI уже доступен, но Ollama тоже запущена, останавливаем Ollama для освобождения VRAM
                    if ollama_running:
                        _log_with_time("info", f"🛑 Останавливаем Ollama для освобождения VRAM...")
                        try:
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                await client.post(f"{self.api_url}/stop/ollama")
                        except Exception:
                            pass  # Не критично, если не удалось остановить
                    self._current_service = service_type
                    return True
                
                # Запускаем ComfyUI и останавливаем Ollama параллельно для ускорения
                stop_ollama_task = None
                if ollama_running:
                    elapsed = time.time() - start_time
                    _log_with_time("info", f"🛑 Останавливаем Ollama перед переключением на ComfyUI...", elapsed)
                    async def stop_ollama():
                        stop_start = time.time()
                        try:
                            async with httpx.AsyncClient(timeout=10.0) as client:
                                stop_response = await client.post(f"{self.api_url}/stop/ollama")
                                if stop_response.status_code == 200:
                                    stop_elapsed = time.time() - stop_start
                                    _log_with_time("info", f"✅ Ollama остановлен", stop_elapsed)
                                    # Минимальное ожидание освобождения VRAM (уменьшено с 5 до 2 секунд)
                                    await asyncio.sleep(2)
                                else:
                                    stop_elapsed = time.time() - stop_start
                                    _log_with_time("warning", f"⚠️ Не удалось остановить Ollama: {stop_response.status_code}", stop_elapsed)
                        except Exception as stop_error:
                            stop_elapsed = time.time() - stop_start
                            _log_with_time("warning", f"⚠️ Ошибка при остановке Ollama: {stop_error}", stop_elapsed)
                    
                    stop_ollama_task = asyncio.create_task(stop_ollama())
                
                # Пытаемся запустить ComfyUI через Process Manager API (параллельно с остановкой Ollama)
                elapsed = time.time() - start_time
                _log_with_time("info", f"🔄 ComfyUI недоступен, пытаемся запустить через Process Manager API...", elapsed)
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        start_request_time = time.time()
                        start_response = await client.post(
                            f"{self.api_url}/process/start",
                            params={"service": "comfyui"}
                        )
                        start_request_elapsed = time.time() - start_request_time
                        
                        if start_response.status_code == 200:
                            elapsed = time.time() - start_time
                            _log_with_time("info", f"✅ Запрос на запуск ComfyUI отправлен (запрос: {start_request_elapsed:.2f}s), ожидание...", elapsed)
                            
                            # Проверяем статус процесса через Process Manager API для более точного определения запуска
                            # Ждем запуска ComfyUI с более частыми проверками
                            max_wait = 30  # Уменьшено с 60 до 30 секунд
                            check_interval = 0.5  # Уменьшено до 0.5 секунды для более быстрого обнаружения
                            process_running = False
                            last_log_time = 0.0
                            wait_start = time.monotonic()
                            min_api_wait_after_running = 2.0  # после запуска процесса не держим ожидание дольше
                            
                            while True:
                                await asyncio.sleep(check_interval)
                                elapsed_wait = time.monotonic() - wait_start
                                
                                if elapsed_wait >= max_wait:
                                    break
                                
                                # Сначала проверяем статус процесса через Process Manager API
                                if not process_running:
                                    try:
                                        health_response = await client.get(f"{self.api_url}/health", timeout=2.0)
                                        if health_response.status_code == 200:
                                            health_data = health_response.json()
                                            comfyui_status = health_data.get("services", {}).get("comfyui", {})
                                            status = comfyui_status.get("status")
                                            if status == "Running":
                                                process_running = True
                                                elapsed = time.time() - start_time
                                                _log_with_time("info", f"✅ ComfyUI процесс запущен (ожидание: {elapsed_wait:.1f}s)", elapsed)
                                            elif status:
                                                # Логируем другие статусы для отладки
                                                logger.debug(f"ComfyUI статус: {status}")
                                    except Exception as e:
                                        logger.debug(f"⚠️ Ошибка проверки статуса процесса: {e}")
                                        pass  # Игнорируем ошибки проверки статуса
                                
                                # Проверяем доступность API (это может занять больше времени после запуска процесса)
                                # Проверяем только если процесс уже запущен (чтобы не тратить время на проверку до запуска)
                                if process_running:
                                    api_available = await self._check_comfyui_available()
                                    if api_available:
                                        elapsed = time.time() - start_time
                                        _log_with_time("info", f"✅ ComfyUI стал доступен (ожидание: {elapsed_wait:.1f}s)", elapsed)
                                        # Ждем завершения остановки Ollama, если она еще выполняется
                                        if stop_ollama_task and not stop_ollama_task.done():
                                            await asyncio.sleep(1)  # Даем еще секунду на освобождение VRAM
                                        self._current_service = service_type
                                        return True
                                    
                                    # Если процесс уже запущен, не держим ожидание дольше минимального окна
                                    if elapsed_wait >= min_api_wait_after_running:
                                        elapsed = time.time() - start_time
                                        _log_with_time(
                                            "info",
                                            "✅ ComfyUI процесс запущен, продолжаем без ожидания API",
                                            elapsed
                                        )
                                        self._current_service = service_type
                                        return True
                                
                                if elapsed_wait - last_log_time >= 2.0:  # Логируем каждые 2 секунды
                                    last_log_time = elapsed_wait
                                    elapsed = time.time() - start_time
                                    _log_with_time(
                                        "info",
                                        f"⏳ Ожидание ComfyUI... ({elapsed_wait:.1f}s/{max_wait}s, процесс: {'запущен' if process_running else 'запускается'})",
                                        elapsed
                                    )
                            
                            # Ждем завершения остановки Ollama перед возвратом
                            if stop_ollama_task and not stop_ollama_task.done():
                                await stop_ollama_task
                            
                            elapsed = time.time() - start_time
                            _log_with_time(
                                "warning",
                                f"⚠️ ComfyUI все еще недоступен после ожидания {max_wait}s (процесс: {'запущен' if process_running else 'не запущен'})",
                                elapsed
                            )
                            # Все равно возвращаем True, чтобы попробовать использовать
                            self._current_service = service_type
                            return True
                        else:
                            elapsed = time.time() - start_time
                            _log_with_time("warning", f"⚠️ Не удалось запустить ComfyUI через API: {start_response.status_code}", elapsed)
                            _log_with_time("warning", f"⚠️ ComfyUI недоступен, требуется ручной запуск")
                            return False
                except Exception as e:
                    elapsed = time.time() - start_time
                    _log_with_time("warning", f"⚠️ Ошибка при запуске ComfyUI через API: {e}", elapsed)
                    _log_with_time("warning", f"⚠️ ComfyUI недоступен, требуется ручной запуск")
                    return False
            
            # Для других сервисов используем старый API (если он еще существует)
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
            if settings.PROCESS_MANAGER_API_URL:
                comfyui_url = "http://127.0.0.1:8188"
            elif settings.COMFYUI_URL:
                comfyui_url = settings.COMFYUI_URL
            else:
                comfyui_url = "http://127.0.0.1:8188"
            
            async with httpx.AsyncClient(timeout=2.0) as client:
                # Пробуем несколько endpoints для более надежной проверки
                # Сначала пробуем /system_stats (основной endpoint)
                try:
                    response = await client.get(f"{comfyui_url}/system_stats", timeout=2.0)
                    if response.status_code == 200:
                        return True
                except httpx.TimeoutException:
                    return False
                except httpx.ConnectError:
                    return False
                except Exception as e:
                    # Логируем только неожиданные ошибки
                    logger.debug(f"⚠️ Ошибка проверки /system_stats: {e}")
                    pass
                
                # Если /system_stats не работает, пробуем / (корневой endpoint)
                try:
                    response = await client.get(f"{comfyui_url}/", timeout=2.0)
                    if response.status_code == 200:
                        return True
                except httpx.TimeoutException:
                    return False
                except httpx.ConnectError:
                    return False
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка проверки /: {e}")
                    pass
                
                return False
        except Exception as e:
            logger.debug(f"⚠️ Общая ошибка проверки ComfyUI: {e}")
            return False
    
    async def restore_previous_service(self) -> bool:
        """
        Восстанавливает предыдущий сервис (если был активен до запроса)
        
        Returns:
            True если восстановление успешно или не требуется
        """
        if not self.restore_on_release:
            logger.debug("🔄 Восстановление отключено в настройках")
            return True
        
        if not self._service_before_request:
            logger.debug("🔄 Нет сохраненного предыдущего сервиса для восстановления")
            return True
        
        # Если текущий сервис совпадает с предыдущим, ничего не делаем
        if self._current_service == self._service_before_request:
            logger.debug(f"🔄 Текущий сервис ({self._current_service.value if self._current_service else 'None'}) уже совпадает с предыдущим ({self._service_before_request.value}), пропускаем восстановление")
            self._service_before_request = None
            return True
        
        previous_service = self._service_before_request
        logger.info(f"🔄 Восстановление предыдущего сервиса: {previous_service.value}")
        try:
            # Временно сбрасываем _service_before_request, чтобы не создавать рекурсию
            self._service_before_request = None
            
            # Переключаемся на предыдущий сервис
            success = await self.switch_to_service(previous_service, force_restart=False)
            
            if success:
                logger.info(f"✅ Предыдущий сервис {previous_service.value} восстановлен")
            else:
                logger.warning(f"⚠️ Не удалось восстановить {previous_service.value}")
                # Восстанавливаем значение, чтобы попробовать позже
                self._service_before_request = previous_service
            
            return success
        except Exception as e:
            logger.error(f"❌ Ошибка восстановления процесса: {e}", exc_info=True)
            # Восстанавливаем значение для возможной повторной попытки
            self._service_before_request = previous_service
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
        Явно запускает Ollama через Process Manager API, если она недоступна
        
        Returns:
            True если переключение успешно
        """
        start_time = time.monotonic()
        _log_with_time("info", "🔄 Принудительное переключение на Ollama...")
        try:
            # Временно сохраняем текущий сервис, чтобы не перезаписать _service_before_request
            temp_before = self._service_before_request
            
            # Сначала проверяем доступность Ollama
            if await self._check_ollama_available():
                elapsed = time.monotonic() - start_time
                _log_with_time("info", "✅ Ollama уже доступна", elapsed)
                self._current_service = ServiceType.OLLAMA
                self._service_before_request = None
                return True
            
            # Если Ollama недоступна, пытаемся запустить через Process Manager API
            if await self.check_api_available():
                elapsed = time.monotonic() - start_time
                _log_with_time("info", "🔄 Ollama недоступна, пытаемся запустить через Process Manager API...", elapsed)
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        request_start = time.monotonic()
                        start_response = await client.post(
                            f"{self.api_url}/process/start",
                            params={"service": "ollama"}
                        )
                        request_elapsed = time.monotonic() - request_start
                        
                        if start_response.status_code == 200:
                            elapsed = time.monotonic() - start_time
                            _log_with_time("info", f"✅ Запрос на запуск Ollama отправлен (запрос: {request_elapsed:.2f}s), ожидание...", elapsed)
                            # Ждем запуска Ollama
                            max_wait = 30
                            waited = 0.0
                            check_interval = 2.0
                            
                            while waited < max_wait:
                                await asyncio.sleep(check_interval)
                                waited += check_interval
                                
                                if await self._check_ollama_available():
                                    elapsed = time.monotonic() - start_time
                                    _log_with_time("info", f"✅ Ollama стала доступна (ожидание: {waited:.1f}s)", elapsed)
                                    self._current_service = ServiceType.OLLAMA
                                    self._service_before_request = None
                                    return True
                                
                                if waited % 10 == 0:
                                    elapsed = time.monotonic() - start_time
                                    _log_with_time("info", f"⏳ Ожидание Ollama... ({waited:.1f}s/{max_wait}s)", elapsed)
                            
                            elapsed = time.monotonic() - start_time
                            _log_with_time("warning", f"⚠️ Ollama все еще недоступна после ожидания {max_wait}s", elapsed)
                            # Все равно возвращаем True, чтобы попробовать использовать
                            self._current_service = ServiceType.OLLAMA
                            self._service_before_request = None
                            return True
                        else:
                            elapsed = time.monotonic() - start_time
                            _log_with_time("warning", f"⚠️ Не удалось запустить Ollama через API: {start_response.status_code}", elapsed)
                            try:
                                response_text = start_response.text[:200]  # Первые 200 символов
                                _log_with_time("debug", f"Ответ API: {response_text}", elapsed)
                            except:
                                pass
                except httpx.TimeoutException as e:
                    elapsed = time.monotonic() - start_time
                    _log_with_time("warning", f"⚠️ Таймаут при запуске Ollama через API: {e}", elapsed)
                except httpx.ConnectError as e:
                    elapsed = time.monotonic() - start_time
                    _log_with_time("warning", f"⚠️ Ошибка подключения к Process Manager API: {e}", elapsed)
                except Exception as e:
                    elapsed = time.monotonic() - start_time
                    _log_with_time("warning", f"⚠️ Ошибка при запуске Ollama через API: {e}", elapsed)
                    logger.exception("Детали ошибки:")
            else:
                elapsed = time.monotonic() - start_time
                _log_with_time("warning", "⚠️ Process Manager API недоступен, используем fallback", elapsed)
            
            # Fallback: используем стандартный switch_to_service
            elapsed = time.monotonic() - start_time
            _log_with_time("info", "🔄 Используем fallback: switch_to_service", elapsed)
            success = await self.switch_to_service(ServiceType.OLLAMA, force_restart=False)
            
            elapsed = time.monotonic() - start_time
            if success:
                _log_with_time("info", "✅ Ollama активирован", elapsed)
                # Сбрасываем _service_before_request только если это было явное переключение
                # (не восстанавливаем предыдущий сервис, так как мы явно хотим Ollama)
                self._service_before_request = None
                self._current_service = ServiceType.OLLAMA
            else:
                _log_with_time("warning", "⚠️ Не удалось активировать Ollama через fallback", elapsed)
                # Если переключение не удалось, восстанавливаем предыдущее значение
                self._service_before_request = temp_before
            
            return success
        except Exception as e:
            elapsed = time.monotonic() - start_time
            _log_with_time("error", f"❌ Ошибка принудительного переключения на Ollama: {e}", elapsed)
            logger.exception("Детали ошибки:")
            return False

    async def stop_service(self, service_type: ServiceType) -> bool:
        """
        Останавливает указанный сервис через Process Manager API.
        """
        start_time = time.monotonic()
        if not await self.check_api_available():
            elapsed = time.monotonic() - start_time
            _log_with_time("warning", "⚠️ Process Manager API недоступен, остановка сервиса пропущена", elapsed)
            return False

        service_name = service_type.value
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                stop_response = await client.post(f"{self.api_url}/stop/{service_name}")

                # Fallback для старого API
                if stop_response.status_code == 404:
                    stop_response = await client.post(
                        f"{self.api_url}/process/stop",
                        params={"service": service_name}
                    )

                elapsed = time.monotonic() - start_time
                if stop_response.status_code == 200:
                    _log_with_time("info", f"✅ Сервис {service_name} остановлен", elapsed)
                    return True

                _log_with_time("warning", f"⚠️ Не удалось остановить {service_name}: {stop_response.status_code}", elapsed)
                return False
        except Exception as e:
            elapsed = time.monotonic() - start_time
            _log_with_time("warning", f"⚠️ Ошибка при остановке {service_name}: {e}", elapsed)
            return False


# Глобальный экземпляр сервиса
process_manager_service = ProcessManagerService()

