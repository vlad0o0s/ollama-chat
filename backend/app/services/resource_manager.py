"""
Диспетчер ресурсов GPU для управления одновременным использованием Ollama и ComfyUI
"""
import asyncio
import heapq
import time
import uuid
import logging
from datetime import datetime
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from ..config import settings
from .vram_monitor import vram_monitor
from .service_types import ServiceType

logger = logging.getLogger(__name__)

def _log_with_time(level: str, message: str, elapsed: Optional[float] = None):
    """Логирует сообщение с временной меткой и опциональным временем выполнения"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]  # HH:MM:SS.mmm
    if elapsed is not None:
        logger.log(getattr(logging, level.upper()), f"[{timestamp}] [{elapsed:.2f}s] {message}")
    else:
        logger.log(getattr(logging, level.upper()), f"[{timestamp}] {message}")

# Импортируем process_manager_service после определения ServiceType
# чтобы избежать циклического импорта
from .process_manager_service import process_manager_service


@dataclass
class GPURequest:
    """Запрос на использование GPU"""
    request_id: str
    service_type: ServiceType
    priority: int
    user_id: Optional[int]
    created_at: float
    required_vram_mb: Optional[int] = None
    
    def __lt__(self, other):
        """Для работы с приоритетной очередью (heapq)"""
        # Высший приоритет = меньшее значение в очереди
        if self.priority != other.priority:
            return self.priority > other.priority  # Больше приоритет = меньше в heap
        return self.created_at < other.created_at  # FIFO для одинакового приоритета


@dataclass
class ResourceLock:
    """Блокировка ресурсов GPU"""
    lock_id: str
    request: GPURequest
    acquired_at: float
    _released: bool = False
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await resource_manager.release_gpu(self.lock_id)


class ResourceManager:
    """Диспетчер ресурсов GPU"""
    
    def __init__(self):
        """Инициализация диспетчера ресурсов"""
        self._lock = asyncio.Lock()  # Блокировка для синхронизации
        self._gpu_lock: Optional[ResourceLock] = None  # Текущая блокировка GPU
        self._queue: List[GPURequest] = []  # Приоритетная очередь запросов
        self._active_locks: Dict[str, ResourceLock] = {}  # Активные блокировки
        self._wait_conditions: Dict[str, asyncio.Event] = {}  # События для ожидания
        
        # Настройки приоритетов
        self.priority_comfyui = settings.GPU_PRIORITY_COMFYUI
        self.priority_ollama = settings.GPU_PRIORITY_OLLAMA
        self.wait_timeout = settings.GPU_WAIT_TIMEOUT
        self.service_availability_timeout = settings.GPU_SERVICE_AVAILABILITY_TIMEOUT
        self.always_restore_ollama_after_comfyui = settings.GPU_ALWAYS_RESTORE_OLLAMA_AFTER_COMFYUI
        
        # Метрики
        self._total_requests = 0
        self._total_timeouts = 0
        self._total_wait_time = 0.0
        self._total_usage_time = 0.0
        
        # Fallback режим: если мониторинг VRAM недоступен, используем простую блокировку
        self._fallback_mode = False
        self._check_fallback_mode()
        
        logger.info("✅ Resource Manager инициализирован")
    
    def _check_fallback_mode(self):
        """Проверяет, нужно ли использовать fallback режим"""
        vram_info = vram_monitor.get_vram_usage()
        if not vram_info.get("available"):
            self._fallback_mode = True
            logger.warning("⚠️ Режим fallback: мониторинг VRAM недоступен, используется простая блокировка")
        else:
            self._fallback_mode = False
    
    def _get_priority(self, service_type: ServiceType) -> int:
        """Получает приоритет для типа сервиса"""
        if service_type == ServiceType.COMFYUI:
            return self.priority_comfyui
        elif service_type == ServiceType.OLLAMA:
            return self.priority_ollama
        else:
            return 1
    
    async def acquire_gpu(
        self, 
        service_type: ServiceType, 
        user_id: Optional[int] = None,
        required_vram_mb: Optional[int] = None,
        timeout: Optional[int] = None
    ) -> ResourceLock:
        """
        Получает блокировку GPU для сервиса
        
        Args:
            service_type: Тип сервиса (COMFYUI, OLLAMA, OTHER)
            user_id: ID пользователя (опционально)
            required_vram_mb: Требуемое количество VRAM в МБ (опционально)
            timeout: Таймаут ожидания в секундах (по умолчанию из настроек)
            
        Returns:
            ResourceLock для использования в context manager
            
        Raises:
            TimeoutError: Если не удалось получить блокировку в течение таймаута
        """
        timeout = timeout or self.wait_timeout
        priority = self._get_priority(service_type)
        
        request = GPURequest(
            request_id=str(uuid.uuid4()),
            service_type=service_type,
            priority=priority,
            user_id=user_id,
            created_at=time.time(),
            required_vram_mb=required_vram_mb
        )
        
        request_start_time = time.time()
        self._total_requests += 1
        _log_with_time("info", f"🔄 Запрос GPU для {service_type.value} (приоритет: {priority}, ID: {request.request_id[:8]}, всего запросов: {self._total_requests})")
        
        # Проверяем доступность Process Manager API
        # Если Process Manager доступен, сервис будет запущен при переключении процесса
        api_available = await process_manager_service.check_api_available()
        if not api_available:
            # Если Process Manager недоступен, проверяем доступность сервиса напрямую
            service_available = await process_manager_service.check_service_available(service_type)
            if not service_available:
                elapsed = time.time() - request_start_time
                error_msg = f"Сервис {service_type.value} недоступен и Process Manager API не доступен"
                _log_with_time("error", f"❌ {error_msg}", elapsed)
                raise RuntimeError(error_msg)
        
        async with self._lock:
            # Проверяем, можем ли сразу получить блокировку
            if self._gpu_lock is None:
                # Сначала переключаем процесс на нужный сервис (это освободит VRAM)
                # Для LLaVA требуется принудительный перезапуск Ollama (чтобы освободить VRAM от gpt-oss)
                force_restart = False
                switch_start = time.time()
                await self._switch_process_if_needed(service_type, force_restart=force_restart)
                switch_elapsed = time.time() - switch_start
                _log_with_time("info", f"🔄 Переключение процесса завершено", switch_elapsed)
                
                # После переключения процесса проверяем доступность VRAM
                # Даем немного времени на освобождение VRAM после остановки процесса
                await asyncio.sleep(2)
                
                # Проверяем доступность VRAM (или пропускаем проверку в fallback режиме)
                if self._fallback_mode or vram_monitor.is_vram_available(required_vram_mb):
                    lock = ResourceLock(
                        lock_id=request.request_id,
                        request=request,
                        acquired_at=time.time()
                    )
                    self._gpu_lock = lock
                    self._active_locks[lock.lock_id] = lock
                    elapsed = time.time() - request_start_time
                    _log_with_time("info", f"✅ GPU выделен для {service_type.value} (ID: {request.request_id[:8]})", elapsed)
                    return lock
                else:
                    elapsed = time.time() - request_start_time
                    _log_with_time("info", f"⏳ VRAM недоступна после переключения процесса, ожидание...", elapsed)
            
            # Если GPU занят, добавляем в очередь
            heapq.heappush(self._queue, request)
            wait_event = asyncio.Event()
            self._wait_conditions[request.request_id] = wait_event
            
            queue_position = len(self._queue)
            elapsed = time.time() - request_start_time
            _log_with_time("info", f"📋 Запрос добавлен в очередь (позиция: {queue_position}, ID: {request.request_id[:8]})", elapsed)
        
        # Ждем освобождения GPU или таймаута
        wait_start = time.time()  # Инициализируем в начале для использования в except блоке
        try:
            # Ждем освобождения VRAM, если она перегружена (только если не в fallback режиме)
            if not self._fallback_mode and not vram_monitor.is_vram_available(required_vram_mb):
                logger.info(f"⏳ Ожидание освобождения VRAM...")
                vram_available = await vram_monitor.wait_for_vram(timeout, required_vram_mb)
                if not vram_available:
                    async with self._lock:
                        # Удаляем из очереди
                        self._queue = [r for r in self._queue if r.request_id != request.request_id]
                        if request.request_id in self._wait_conditions:
                            del self._wait_conditions[request.request_id]
                    
                    wait_time = time.time() - wait_start
                    self._total_timeouts += 1
                    logger.warning(f"⚠️ Таймаут ожидания VRAM ({timeout}s) для {service_type.value} (ID: {request.request_id[:8]}, всего таймаутов: {self._total_timeouts})")
                    raise TimeoutError(f"Таймаут ожидания VRAM ({timeout}s)")
            
            # Ждем освобождения GPU
            await asyncio.wait_for(wait_event.wait(), timeout=timeout)
            
            async with self._lock:
                # Проверяем, что блокировка действительно получена
                if request.request_id in self._active_locks:
                    lock = self._active_locks[request.request_id]
                    wait_time = time.time() - wait_start
                    self._total_wait_time += wait_time
                    
                    # Переключаем процесс на нужный сервис (если еще не переключен)
                    switch_start = time.time()
                    await self._switch_process_if_needed(service_type)
                    switch_elapsed = time.time() - switch_start
                    
                    # Даем время на освобождение VRAM
                    await asyncio.sleep(2)
                    
                    total_elapsed = time.time() - request.created_at
                    _log_with_time("info", f"✅ GPU получен после ожидания {wait_time:.1f}s для {service_type.value} (ID: {request.request_id[:8]}, переключение: {switch_elapsed:.2f}s, всего: {total_elapsed:.2f}s, среднее ожидание: {self._total_wait_time / max(1, self._total_requests - self._total_timeouts):.1f}s)", total_elapsed)
                    return lock
                else:
                    raise RuntimeError("Блокировка была отменена")
                    
        except asyncio.TimeoutError:
            async with self._lock:
                # Удаляем из очереди
                self._queue = [r for r in self._queue if r.request_id != request.request_id]
                if request.request_id in self._wait_conditions:
                    del self._wait_conditions[request.request_id]
            
            wait_time = time.time() - wait_start
            self._total_timeouts += 1
            logger.warning(f"⚠️ Таймаут ожидания GPU ({timeout}s) для {service_type.value} (ID: {request.request_id[:8]}, всего таймаутов: {self._total_timeouts})")
            raise TimeoutError(f"Таймаут ожидания GPU ({timeout}s)")
    
    async def release_gpu(self, lock_id: str):
        """
        Освобождает блокировку GPU
        
        Args:
            lock_id: ID блокировки для освобождения
        """
        async with self._lock:
            if lock_id not in self._active_locks:
                logger.warning(f"⚠️ Попытка освободить несуществующую блокировку: {lock_id[:8]}")
                return
            
            lock = self._active_locks[lock_id]
            
            # Проверяем, что это текущая активная блокировка
            if self._gpu_lock and self._gpu_lock.lock_id == lock_id:
                service_type = lock.request.service_type
                service_type_value = service_type.value
                usage_time = time.time() - lock.acquired_at
                self._total_usage_time += usage_time
                avg_usage = self._total_usage_time / max(1, self._total_requests - self._total_timeouts)
                _log_with_time("info", f"🔓 GPU освобожден от {service_type_value} (использовано: {usage_time:.1f}s, ID: {lock_id[:8]}, среднее использование: {avg_usage:.1f}s)", usage_time)
                
                # Сохраняем информацию о сервисе перед освобождением
                released_service = service_type
                
                self._gpu_lock = None
                del self._active_locks[lock_id]
                lock._released = True
                
                # Восстанавливаем предыдущий процесс (если нужно)
                await self._restore_previous_process(released_service)
                
                # Обрабатываем очередь
                await self._process_queue()
            else:
                logger.warning(f"⚠️ Попытка освободить неактивную блокировку: {lock_id[:8]}")
    
    async def _process_queue(self):
        """Обрабатывает очередь запросов"""
        while self._queue and self._gpu_lock is None:
            # Берем запрос с наивысшим приоритетом
            request = heapq.heappop(self._queue)
            
            # Проверяем доступность сервиса перед обработкой
            service_available = await process_manager_service.check_service_available(request.service_type)
            if not service_available:
                # Проверяем, доступен ли Process Manager
                api_available = await process_manager_service.check_api_available()
                if api_available:
                    logger.info(f"⏳ Сервис {request.service_type.value} недоступен для запроса из очереди. Ожидание запуска...")
                    # Ждем доступности сервиса
                    service_available = await self._wait_for_service_availability(
                        request.service_type, 
                        self.service_availability_timeout
                    )
                    if not service_available:
                        logger.warning(f"⚠️ Сервис {request.service_type.value} не стал доступен. Возвращаем запрос в очередь")
                        # Возвращаем запрос в очередь (в конец)
                        heapq.heappush(self._queue, request)
                        break
                else:
                    logger.warning(f"⚠️ Process Manager недоступен. Возвращаем запрос в очередь")
                    heapq.heappush(self._queue, request)
                    break
            
            # Сначала переключаем процесс на нужный сервис (это освободит VRAM)
            await self._switch_process_if_needed(request.service_type)
            
            # Даем время на освобождение VRAM после остановки процесса
            await asyncio.sleep(2)
            
            # После переключения процесса проверяем доступность VRAM
            if self._fallback_mode or vram_monitor.is_vram_available(request.required_vram_mb):
                lock = ResourceLock(
                    lock_id=request.request_id,
                    request=request,
                    acquired_at=time.time()
                )
                self._gpu_lock = lock
                self._active_locks[lock.lock_id] = lock
                
                # Уведомляем ожидающий запрос
                if request.request_id in self._wait_conditions:
                    self._wait_conditions[request.request_id].set()
                    del self._wait_conditions[request.request_id]
                
                wait_time = time.time() - request.created_at
                logger.info(f"✅ GPU выделен из очереди для {request.service_type.value} (ожидание: {wait_time:.1f}s, ID: {request.request_id[:8]})")
                break
            else:
                # Если VRAM все еще недоступна, возвращаем запрос в очередь
                heapq.heappush(self._queue, request)
                logger.debug(f"⏳ VRAM недоступна для {request.service_type.value} после переключения, пропускаем")
                break
    
    def get_queue_status(self) -> Dict:
        """
        Получает статус очереди и использования GPU
        
        Returns:
            Словарь со статусом:
            {
                "gpu_locked": bool,
                "current_service": Optional[str],
                "queue_length": int,
                "queue": List[Dict],
                "vram_info": Dict
            }
        """
        vram_info = vram_monitor.get_vram_usage()
        
        async def _get_status():
            async with self._lock:
                current_service = None
                if self._gpu_lock:
                    current_service = self._gpu_lock.request.service_type.value
                
                queue_info = []
                for request in self._queue[:10]:  # Первые 10 в очереди
                    queue_info.append({
                        "request_id": request.request_id[:8],
                        "service_type": request.service_type.value,
                        "priority": request.priority,
                        "waiting_time": time.time() - request.created_at
                    })
                
                return {
                    "gpu_locked": self._gpu_lock is not None,
                    "current_service": current_service,
                    "queue_length": len(self._queue),
                    "queue": queue_info,
                    "vram_info": vram_info,
                    "metrics": {
                        "total_requests": self._total_requests,
                        "total_timeouts": self._total_timeouts,
                        "timeout_rate": self._total_timeouts / max(1, self._total_requests),
                        "avg_wait_time": self._total_wait_time / max(1, self._total_requests - self._total_timeouts),
                        "avg_usage_time": self._total_usage_time / max(1, self._total_requests - self._total_timeouts),
                        "fallback_mode": self._fallback_mode
                    }
                }
        
        # Синхронный вызов для получения статуса
        # Используем новый event loop для синхронного вызова
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если loop уже запущен, создаем новую задачу
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _get_status())
                    return future.result(timeout=1)
            else:
                return loop.run_until_complete(_get_status())
        except RuntimeError:
            # Если нет event loop, создаем новый
            return asyncio.run(_get_status())
    
    async def _switch_process_if_needed(self, service_type: ServiceType, force_restart: bool = False):
        """
        Переключает процесс на нужный сервис, если требуется
        
        Args:
            service_type: Тип сервиса для переключения
            force_restart: Если True, принудительно перезапускает сервис (для смены модели в Ollama)
        """
        switch_start = time.time()
        # Проверяем доступность Process Management API
        api_available = await process_manager_service.check_api_available()
        if not api_available:
            _log_with_time("warning", "⚠️ Process Management API недоступен, пропускаем переключение процесса")
            return
        
        # Переключаем процесс
        try:
            if force_restart:
                _log_with_time("info", f"🔄 Переключение процесса на {service_type.value} (принудительный перезапуск)...")
            else:
                _log_with_time("info", f"🔄 Переключение процесса на {service_type.value}...")
            success = await process_manager_service.switch_to_service(service_type, force_restart=force_restart)
            elapsed = time.time() - switch_start
            if success:
                _log_with_time("info", f"✅ Процесс переключен на {service_type.value}", elapsed)
            else:
                _log_with_time("warning", f"⚠️ Не удалось переключить процесс на {service_type.value}", elapsed)
        except Exception as e:
            elapsed = time.time() - switch_start
            _log_with_time("error", f"❌ Ошибка переключения процесса: {e}", elapsed)
            # Продолжаем работу даже если переключение не удалось (fallback)
    
    async def _restore_previous_process(self, released_service: ServiceType):
        """
        Восстанавливает предыдущий процесс после освобождения GPU
        
        Args:
            released_service: Тип сервиса, который был освобожден
        """
        restore_start = time.monotonic()
        try:
            # Если освобождается ComfyUI и включена настройка - всегда переключаться на Ollama
            if released_service == ServiceType.COMFYUI and self.always_restore_ollama_after_comfyui:
                _log_with_time("info", "🔄 Освобождается ComfyUI, переключаемся на Ollama...")
                try:
                    success = await process_manager_service.ensure_ollama_active()
                    elapsed = time.monotonic() - restore_start
                    if success:
                        _log_with_time("info", "✅ Ollama восстановлен после ComfyUI", elapsed)
                    else:
                        _log_with_time("warning", "⚠️ Не удалось восстановить Ollama после ComfyUI", elapsed)
                except Exception as restore_error:
                    elapsed = time.monotonic() - restore_start
                    _log_with_time("error", f"❌ Ошибка при восстановлении Ollama: {restore_error}", elapsed)
                    logger.exception("Детали ошибки восстановления Ollama:")
            elif released_service == ServiceType.OLLAMA:
                # Если освобождается Ollama, проверяем, нужно ли восстанавливать предыдущий сервис
                # Но обычно после Ollama мы хотим оставить Ollama активной для дальнейшей работы
                elapsed = time.monotonic() - restore_start
                _log_with_time("debug", "🔄 Освобождается Ollama, проверяем необходимость восстановления...", elapsed)
                # Не восстанавливаем автоматически, так как Ollama обычно должна оставаться активной
                # Если нужен другой сервис, он будет запрошен через Resource Manager
            else:
                # Для других случаев используем стандартную логику восстановления
                elapsed = time.monotonic() - restore_start
                _log_with_time("info", f"🔄 Восстановление предыдущего сервиса после {released_service.value}...", elapsed)
                try:
                    await process_manager_service.restore_previous_service()
                    elapsed = time.monotonic() - restore_start
                    _log_with_time("info", "✅ Предыдущий сервис восстановлен", elapsed)
                except Exception as restore_error:
                    elapsed = time.monotonic() - restore_start
                    _log_with_time("warning", f"⚠️ Ошибка при восстановлении предыдущего сервиса: {restore_error}", elapsed)
                    logger.exception("Детали ошибки восстановления:")
        except Exception as e:
            elapsed = time.monotonic() - restore_start
            _log_with_time("error", f"❌ Критическая ошибка восстановления процесса: {e}", elapsed)
            logger.exception("Детали критической ошибки:")
    
    async def _wait_for_service_availability(self, service_type: ServiceType, timeout: int) -> bool:
        """
        Ожидает доступности сервиса с таймаутом
        
        Args:
            service_type: Тип сервиса для проверки
            timeout: Таймаут ожидания в секундах
            
        Returns:
            True если сервис стал доступен, False при таймауте
        """
        start_time = time.time()
        check_interval = 2  # Проверяем каждые 2 секунды
        
        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                logger.warning(f"⚠️ Таймаут ожидания доступности {service_type.value} ({timeout}s)")
                return False
            
            # Проверяем доступность сервиса
            available = await process_manager_service.check_service_available(service_type)
            if available:
                logger.info(f"✅ Сервис {service_type.value} стал доступен (ожидание: {elapsed:.1f}s)")
                return True
            
            # Ждем перед следующей проверкой
            await asyncio.sleep(check_interval)


# Глобальный экземпляр диспетчера
resource_manager = ResourceManager()

