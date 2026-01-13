"""
Сервис для мониторинга использования VRAM GPU
"""
import subprocess
import logging
import asyncio
from typing import Dict, List, Optional
from ..config import settings

logger = logging.getLogger(__name__)


class VRAMMonitor:
    """Класс для мониторинга использования VRAM"""
    
    def __init__(self):
        """Инициализация монитора VRAM"""
        self.enabled = settings.GPU_MONITOR_ENABLED
        self.monitor_interval = settings.GPU_MONITOR_INTERVAL
        self.vram_threshold = settings.GPU_VRAM_THRESHOLD
        self.min_free_vram_mb = settings.GPU_MIN_FREE_VRAM_MB
        self._pynvml_available = False
        self._nvidia_smi_available = False
        
        # Пытаемся инициализировать nvidia-ml-py (замена устаревшего pynvml)
        try:
            import warnings
            # Подавляем предупреждение о deprecated pynvml, так как мы используем nvidia-ml-py
            # который предоставляет интерфейс pynvml для обратной совместимости
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=FutureWarning, message=".*pynvml.*")
                import pynvml  # nvidia-ml-py предоставляет интерфейс pynvml
            # nvidia-ml-py использует тот же интерфейс pynvml, но это современная версия
            pynvml.nvmlInit()
            self._pynvml_available = True
            self._pynvml = pynvml
            logger.info("✅ nvidia-ml-py инициализирован для мониторинга VRAM")
        except ImportError:
            logger.debug("nvidia-ml-py не установлен, будет использован nvidia-smi")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось инициализировать nvidia-ml-py: {e}")
        
        # Проверяем доступность nvidia-smi
        if not self._pynvml_available:
            self._check_nvidia_smi()
    
    def _check_nvidia_smi(self) -> bool:
        """Проверяет доступность nvidia-smi"""
        try:
            result = subprocess.run(
                ['nvidia-smi', '--version'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                self._nvidia_smi_available = True
                logger.info("✅ nvidia-smi доступен для мониторинга VRAM")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        except Exception as e:
            logger.debug(f"Ошибка проверки nvidia-smi: {e}")
        
        self._nvidia_smi_available = False
        logger.warning("⚠️ nvidia-smi недоступен, мониторинг VRAM будет ограничен")
        return False
    
    def get_vram_usage(self) -> Dict:
        """
        Получает текущее использование VRAM
        
        Returns:
            Словарь с информацией о VRAM:
            {
                "used_mb": int,
                "total_mb": int,
                "free_mb": int,
                "usage_percent": float,
                "available": bool,
                "method": str  # "pynvml", "nvidia-smi", или "unavailable"
            }
        """
        if not self.enabled:
            return {
                "used_mb": 0,
                "total_mb": 0,
                "free_mb": 0,
                "usage_percent": 0.0,
                "available": True,
                "method": "disabled"
            }
        
        # Пытаемся использовать pynvml
        if self._pynvml_available:
            try:
                handle = self._pynvml.nvmlDeviceGetHandleByIndex(0)
                info = self._pynvml.nvmlDeviceGetMemoryInfo(handle)
                
                used_mb = info.used // (1024 * 1024)
                total_mb = info.total // (1024 * 1024)
                free_mb = info.free // (1024 * 1024)
                usage_percent = (info.used / info.total) * 100
                
                return {
                    "used_mb": used_mb,
                    "total_mb": total_mb,
                    "free_mb": free_mb,
                    "usage_percent": round(usage_percent, 2),
                    "available": True,
                    "method": "pynvml"
                }
            except Exception as e:
                logger.error(f"❌ Ошибка получения VRAM через pynvml: {e}")
        
        # Fallback на nvidia-smi
        if self._nvidia_smi_available:
            try:
                result = subprocess.run(
                    ['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    if lines:
                        # Берем первую строку (первый GPU)
                        parts = lines[0].strip().split(',')
                        if len(parts) >= 2:
                            used_mb = int(parts[0].strip())
                            total_mb = int(parts[1].strip())
                            free_mb = total_mb - used_mb
                            usage_percent = (used_mb / total_mb) * 100 if total_mb > 0 else 0
                            
                            return {
                                "used_mb": used_mb,
                                "total_mb": total_mb,
                                "free_mb": free_mb,
                                "usage_percent": round(usage_percent, 2),
                                "available": True,
                                "method": "nvidia-smi"
                            }
            except Exception as e:
                logger.error(f"❌ Ошибка получения VRAM через nvidia-smi: {e}")
        
        # Если ничего не работает, возвращаем недоступность
        logger.warning("⚠️ Мониторинг VRAM недоступен")
        return {
            "used_mb": 0,
            "total_mb": 0,
            "free_mb": 0,
            "usage_percent": 0.0,
            "available": False,
            "method": "unavailable"
        }
    
    def get_gpu_processes(self) -> List[Dict]:
        """
        Получает список процессов, использующих GPU
        
        Returns:
            Список словарей с информацией о процессах:
            [
                {
                    "pid": int,
                    "name": str,
                    "memory_mb": int
                },
                ...
            ]
        """
        processes = []
        
        if not self.enabled:
            return processes
        
        # Пытаемся использовать nvidia-smi для получения процессов
        if self._nvidia_smi_available:
            try:
                result = subprocess.run(
                    ['nvidia-smi', '--query-compute-apps=pid,process_name,used_memory', '--format=csv,noheader,nounits'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        if line.strip():
                            parts = line.strip().split(',')
                            if len(parts) >= 3:
                                try:
                                    processes.append({
                                        "pid": int(parts[0].strip()),
                                        "name": parts[1].strip(),
                                        "memory_mb": int(parts[2].strip())
                                    })
                                except ValueError:
                                    continue
            except Exception as e:
                logger.debug(f"Ошибка получения процессов GPU: {e}")
        
        return processes
    
    def is_vram_available(self, required_mb: Optional[int] = None) -> bool:
        """
        Проверяет доступность VRAM для новой задачи
        
        Args:
            required_mb: Требуемое количество VRAM в МБ (опционально)
            
        Returns:
            True, если VRAM доступна, False в противном случае
        """
        if not self.enabled:
            return True  # Если мониторинг отключен, считаем что доступно
        
        vram_info = self.get_vram_usage()
        
        if not vram_info.get("available"):
            # Если мониторинг недоступен, разрешаем использование
            logger.warning("⚠️ Мониторинг VRAM недоступен, разрешаем использование GPU")
            return True
        
        # Проверяем процент использования
        usage_percent = vram_info.get("usage_percent", 0)
        if usage_percent >= self.vram_threshold:
            logger.warning(f"⚠️ VRAM перегружена: {usage_percent:.1f}% >= {self.vram_threshold}%")
            return False
        
        # Проверяем минимальное свободное место
        free_mb = vram_info.get("free_mb", 0)
        min_required = required_mb or self.min_free_vram_mb
        
        if free_mb < min_required:
            logger.warning(f"⚠️ Недостаточно свободной VRAM: {free_mb}MB < {min_required}MB")
            return False
        
        return True
    
    async def wait_for_vram(self, timeout: int, required_mb: Optional[int] = None) -> bool:
        """
        Ожидает освобождения VRAM
        
        Args:
            timeout: Максимальное время ожидания в секундах
            required_mb: Требуемое количество VRAM в МБ (опционально)
            
        Returns:
            True, если VRAM стала доступна, False при таймауте
        """
        if not self.enabled:
            return True
        
        start_time = asyncio.get_event_loop().time()
        check_interval = self.monitor_interval
        
        while True:
            if self.is_vram_available(required_mb):
                elapsed = asyncio.get_event_loop().time() - start_time
                logger.info(f"✅ VRAM стала доступна через {elapsed:.1f} секунд")
                return True
            
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                logger.warning(f"⚠️ Таймаут ожидания VRAM ({timeout}s)")
                return False
            
            # Логируем каждые 10 секунд
            if int(elapsed) % 10 == 0 and int(elapsed) > 0:
                vram_info = self.get_vram_usage()
                logger.info(f"⏳ Ожидание VRAM... ({elapsed:.0f}s/{timeout}s, использование: {vram_info.get('usage_percent', 0):.1f}%)")
            
            await asyncio.sleep(check_interval)


# Глобальный экземпляр монитора
vram_monitor = VRAMMonitor()

