"""
Process Management API для управления процессами Ollama и ComfyUI на Windows ПК
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Tuple
import subprocess
import os
import time
import logging
from pathlib import Path
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Process Management API", version="1.0.0")

# CORS для доступа с backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ServiceType(str, Enum):
    """Типы сервисов"""
    OLLAMA = "ollama"
    COMFYUI = "comfyui"


class ProcessStatus(BaseModel):
    """Статус процесса"""
    service: str
    running: bool
    pid: Optional[int] = None
    error: Optional[str] = None


class SwitchResponse(BaseModel):
    """Ответ на переключение процесса"""
    success: bool
    message: str
    previous_service: Optional[str] = None
    current_service: Optional[str] = None
    switch_time: float


# Конфигурация (можно вынести в .env)
COMFYUI_PATH = os.getenv("COMFYUI_PATH", r"C:\ComfyUI_windows_portable")
OLLAMA_PATH = os.getenv("OLLAMA_PATH", "")  # Путь к папке с ollama.exe
PROCESS_STARTUP_WAIT = int(os.getenv("PROCESS_STARTUP_WAIT", "10"))  # секунды

# Хранение PID процессов
_process_pids: Dict[str, int] = {}
_current_service: Optional[ServiceType] = None


def check_process_running(process_name: str) -> Tuple[bool, Optional[int]]:
    """
    Проверяет, запущен ли процесс
    
    Args:
        process_name: Имя процесса (например, 'ollama.exe' или 'python.exe')
        
    Returns:
        Tuple (is_running, pid)
    """
    try:
        result = subprocess.run(
            ['tasklist', '/fi', f'imagename eq {process_name}'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if process_name in result.stdout:
            # Пытаемся извлечь PID из вывода
            lines = result.stdout.split('\n')
            for line in lines:
                if process_name in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            return True, pid
                        except (ValueError, IndexError):
                            pass
            return True, None
        return False, None
    except Exception as e:
        logger.error(f"Ошибка проверки процесса {process_name}: {e}")
        return False, None


def stop_ollama() -> bool:
    """Останавливает процесс Ollama"""
    try:
        logger.info("🛑 Остановка Ollama...")
        result = subprocess.run(
            ['taskkill', '/f', '/im', 'ollama.exe'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # taskkill возвращает код 0 если процесс найден и остановлен
        # или код 128 если процесс не найден (это нормально)
        if result.returncode == 0 or result.returncode == 128:
            logger.info("✅ Ollama остановлен")
            if 'ollama' in _process_pids:
                del _process_pids['ollama']
            return True
        else:
            logger.warning(f"⚠️ Неожиданный код возврата taskkill: {result.returncode}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка остановки Ollama: {e}")
        return False


def start_ollama() -> Tuple[bool, Optional[int]]:
    """Запускает процесс Ollama"""
    try:
        logger.info("🚀 Запуск Ollama...")
        
        # Проверяем, не запущен ли уже
        is_running, pid = check_process_running('ollama.exe')
        if is_running:
            logger.info(f"✅ Ollama уже запущен (PID: {pid})")
            _process_pids['ollama'] = pid
            return True, pid
        
        # Находим ollama.exe
        ollama_exe = None
        if OLLAMA_PATH:
            ollama_exe = Path(OLLAMA_PATH) / "ollama.exe"
            if not ollama_exe.exists():
                # Пробуем найти в PATH
                ollama_exe = "ollama.exe"
        else:
            # Пробуем найти в PATH
            ollama_exe = "ollama.exe"
        
        # Устанавливаем переменные окружения
        env = os.environ.copy()
        env['OLLAMA_ORIGINS'] = '*'
        env['OLLAMA_HOST'] = '0.0.0.0:11434'
        
        # Запускаем процесс
        cwd = Path(OLLAMA_PATH) if OLLAMA_PATH else None
        process = subprocess.Popen(
            [str(ollama_exe), 'serve'],
            env=env,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        _process_pids['ollama'] = process.pid
        logger.info(f"✅ Ollama запущен (PID: {process.pid})")
        
        # Ждем инициализацию и проверяем доступность
        logger.info("⏳ Ожидание инициализации Ollama...")
        time.sleep(3)
        
        # Проверяем доступность Ollama API
        max_wait = 15  # Максимум 15 секунд на проверку
        check_interval = 1
        elapsed = 0
        
        while elapsed < max_wait:
            try:
                import httpx
                with httpx.Client(timeout=2.0) as client:
                    response = client.get("http://127.0.0.1:11434/api/tags")
                    if response.status_code == 200:
                        logger.info(f"✅ Ollama доступен (PID: {process.pid})")
                        return True, process.pid
            except:
                pass
            
            elapsed += check_interval
            if elapsed < max_wait:
                time.sleep(check_interval)
        
        logger.warning("⚠️ Ollama запущен, но API не отвечает после ожидания")
        return True, process.pid  # Возвращаем True, так как процесс запущен
    except Exception as e:
        logger.error(f"❌ Ошибка запуска Ollama: {e}")
        return False, None


def stop_comfyui() -> bool:
    """Останавливает процесс ComfyUI"""
    try:
        logger.info("🛑 Остановка ComfyUI...")
        
        # Сначала проверяем, запущен ли ComfyUI
        is_running, _ = check_comfyui_running()
        if not is_running:
            logger.info("✅ ComfyUI уже остановлен")
            if 'comfyui' in _process_pids:
                del _process_pids['comfyui']
            return True
        
        # Пытаемся остановить через PID, если он известен
        if 'comfyui' in _process_pids:
            pid = _process_pids['comfyui']
            try:
                result = subprocess.run(
                    ['taskkill', '/f', '/pid', str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    logger.info(f"✅ ComfyUI остановлен по PID {pid}")
                    del _process_pids['comfyui']
                    time.sleep(1)
                    return True
            except Exception as e:
                logger.debug(f"Не удалось остановить по PID: {e}")
        
        # Если PID не помог, ищем процессы python.exe, которые могут быть ComfyUI
        # Используем более безопасный подход - ищем процессы по командной строке
        try:
            # Получаем список процессов python.exe
            result = subprocess.run(
                ['wmic', 'process', 'where', 'name="python.exe"', 'get', 'processid,commandline'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                comfyui_pids = []
                
                for line in lines:
                    if 'ComfyUI' in line or 'main.py' in line:
                        # Извлекаем PID из строки
                        parts = line.split()
                        for part in parts:
                            if part.isdigit():
                                comfyui_pids.append(int(part))
                                break
                
                # Останавливаем найденные процессы
                for pid in comfyui_pids:
                    try:
                        subprocess.run(
                            ['taskkill', '/f', '/pid', str(pid)],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        logger.info(f"✅ Остановлен процесс ComfyUI (PID: {pid})")
                    except:
                        pass
                
                if comfyui_pids:
                    time.sleep(2)
                    is_running, _ = check_comfyui_running()
                    if not is_running:
                        if 'comfyui' in _process_pids:
                            del _process_pids['comfyui']
                        logger.info("✅ ComfyUI остановлен")
                        return True
        except Exception as e:
            logger.debug(f"Ошибка при поиске процессов ComfyUI: {e}")
        
        # Fallback: используем netstat для поиска процесса на порту 8188
        try:
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                port_8188_pids = []
                current_pid = os.getpid()  # PID текущего процесса (Process Management API)
                
                for line in lines:
                    if ':8188' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            try:
                                pid = int(parts[-1])
                                # Не останавливаем сам Process Management API
                                if pid != current_pid:
                                    port_8188_pids.append(pid)
                            except:
                                pass
                
                # Останавливаем процессы на порту 8188 (скорее всего это ComfyUI)
                stopped = False
                for pid in port_8188_pids:
                    try:
                        result = subprocess.run(
                            ['taskkill', '/f', '/pid', str(pid)],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0:
                            logger.info(f"✅ Остановлен процесс на порту 8188 (PID: {pid})")
                            stopped = True
                    except Exception as e:
                        logger.debug(f"Ошибка остановки PID {pid}: {e}")
                
                if stopped:
                    time.sleep(2)
                    is_running, _ = check_comfyui_running()
                    if not is_running:
                        if 'comfyui' in _process_pids:
                            del _process_pids['comfyui']
                        logger.info("✅ ComfyUI остановлен")
                        return True
        except FileNotFoundError:
            logger.warning("⚠️ netstat не найден")
        except Exception as e:
            logger.debug(f"Ошибка при поиске через netstat: {e}")
        
        logger.warning("⚠️ Не удалось найти и остановить ComfyUI процесс")
        return False
            
    except Exception as e:
        logger.error(f"❌ Критическая ошибка остановки ComfyUI: {e}")
        # Не падаем, возвращаем False
        return False


def check_comfyui_running() -> Tuple[bool, Optional[int]]:
    """Проверяет, запущен ли ComfyUI"""
    try:
        # Проверяем доступность API ComfyUI
        import httpx
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get("http://127.0.0.1:8188/system_stats")
                if response.status_code == 200:
                    logger.debug("✅ ComfyUI API доступен на http://127.0.0.1:8188")
                    # ComfyUI запущен, но нужно найти PID
                    # Для простоты возвращаем True без PID
                    return True, None
                else:
                    logger.debug(f"⚠️ ComfyUI API вернул статус {response.status_code}")
        except httpx.ConnectError:
            logger.debug("⚠️ Не удалось подключиться к ComfyUI API (ConnectionError)")
        except httpx.TimeoutException:
            logger.debug("⚠️ Таймаут подключения к ComfyUI API")
        except Exception as e:
            logger.debug(f"⚠️ Ошибка проверки ComfyUI API: {e}")
        
        # Также проверяем python.exe процессы (но это не очень точно)
        is_running, pid = check_process_running('python.exe')
        if is_running:
            logger.debug(f"⚠️ Найден процесс python.exe (PID: {pid}), но ComfyUI API недоступен")
        return False, None  # Возвращаем False, если API недоступен
    except Exception as e:
        logger.debug(f"Ошибка проверки ComfyUI: {e}")
        return False, None


def start_comfyui() -> Tuple[bool, Optional[int]]:
    """Запускает процесс ComfyUI"""
    try:
        logger.info("🚀 Запуск ComfyUI...")
        
        # Проверяем, не запущен ли уже
        is_running, pid = check_comfyui_running()
        if is_running:
            logger.info(f"✅ ComfyUI уже запущен (PID: {pid})")
            if pid:
                _process_pids['comfyui'] = pid
            return True, pid
        
        # Проверяем существование пути
        comfyui_path = Path(COMFYUI_PATH)
        if not comfyui_path.exists():
            logger.error(f"❌ Путь к ComfyUI не существует: {COMFYUI_PATH}")
            return False, None
        
        python_exe = comfyui_path / "python_embeded" / "python.exe"
        if not python_exe.exists():
            logger.error(f"❌ Python.exe не найден: {python_exe}")
            return False, None
        
        main_py = comfyui_path / "ComfyUI" / "main.py"
        if not main_py.exists():
            logger.error(f"❌ main.py не найден: {main_py}")
            return False, None
        
        # Формируем команду запуска (как в run_nvidia_gpu.bat)
        # Используем относительный путь к main.py от рабочей директории
        main_py_relative = "ComfyUI\\main.py"
        
        command = [
            str(python_exe),
            '-s',
            main_py_relative,
            '--windows-standalone-build',
            '--listen', '0.0.0.0',
            '--port', '8188'
        ]
        shell = False
        
        # Проверяем наличие batch файла для справки
        batch_file = comfyui_path / "run_nvidia_gpu.bat"
        if batch_file.exists():
            logger.info(f"📋 Найден batch файл для справки: {batch_file}")
            try:
                with open(batch_file, 'r', encoding='utf-8') as f:
                    batch_content = f.read().strip()
                    logger.info(f"   Содержимое: {batch_content}")
            except:
                pass
        
        logger.info(f"🚀 Запуск ComfyUI...")
        logger.info(f"   Путь: {COMFYUI_PATH}")
        logger.info(f"   Python: {python_exe}")
        logger.info(f"   Main.py: ComfyUI\\main.py")
        logger.info(f"   Команда: {' '.join(command) if isinstance(command, list) else command}")
        logger.info(f"   Рабочая директория: {comfyui_path}")
        
        # Инициализируем переменные для логирования вывода
        import threading
        output_lines = []
        output_lock = threading.Lock()
        process = None
        
        # Запускаем процесс
        try:
            process = subprocess.Popen(
                command,
                cwd=str(comfyui_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Объединяем stderr в stdout
                shell=shell,
                text=True,  # Текстовый режим для лучшего логирования
                bufsize=1  # Строковая буферизация
            )
            
            _process_pids['comfyui'] = process.pid
            logger.info(f"✅ ComfyUI процесс запущен (PID: {process.pid})")
            
            # Запускаем поток для чтения вывода в реальном времени
            def read_output():
                """Читает вывод процесса в реальном времени"""
                try:
                    for line in process.stdout:
                        line = line.strip()
                        if line:
                            with output_lock:
                                output_lines.append(line)
                            # Логируем важные сообщения
                            if any(keyword in line.lower() for keyword in ['error', 'exception', 'traceback', 'failed']):
                                logger.warning(f"⚠️ ComfyUI: {line}")
                            elif any(keyword in line.lower() for keyword in ['starting', 'listening', 'server']):
                                logger.info(f"ℹ️ ComfyUI: {line}")
                except Exception as e:
                    logger.debug(f"Ошибка чтения вывода: {e}")
            
            output_thread = threading.Thread(target=read_output, daemon=True)
            output_thread.start()
            
            # Проверяем, что процесс не завершился сразу
            time.sleep(3)  # Даем время на запуск
            if process.poll() is not None:
                # Процесс завершился, читаем оставшийся вывод
                try:
                    remaining_output, _ = process.communicate(timeout=5)
                    if remaining_output:
                        with output_lock:
                            output_lines.extend(remaining_output.strip().split('\n'))
                except subprocess.TimeoutExpired:
                    pass
                
                logger.error(f"❌ ComfyUI завершился сразу после запуска (PID: {process.pid})")
                logger.error(f"   Код возврата: {process.returncode}")
                
                # Выводим последние строки вывода
                with output_lock:
                    if output_lines:
                        logger.error(f"   Последние строки вывода ({len(output_lines)} строк):")
                        for line in output_lines[-20:]:  # Последние 20 строк
                            logger.error(f"      {line}")
                    else:
                        logger.error(f"   Вывод недоступен (процесс завершился слишком быстро)")
                
                # Очищаем PID
                if 'comfyui' in _process_pids:
                    del _process_pids['comfyui']
                return False, None
            
            # Ждем инициализацию (увеличено время для ComfyUI)
            logger.info(f"⏳ Ожидание инициализации ComfyUI ({PROCESS_STARTUP_WAIT}s)...")
            time.sleep(PROCESS_STARTUP_WAIT)
        except Exception as e:
            logger.error(f"❌ Ошибка при запуске процесса ComfyUI: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return False, None
        
        # Проверяем, что процесс был создан
        if process is None:
            logger.error("❌ Процесс ComfyUI не был создан")
            return False, None
        
        # Проверяем, что процесс все еще запущен
        if process.poll() is not None:
            logger.error(f"❌ ComfyUI процесс завершился во время ожидания (PID: {process.pid}, код: {process.returncode})")
            try:
                remaining_output, _ = process.communicate(timeout=5)
                with output_lock:
                    if remaining_output:
                        output_lines.extend(remaining_output.strip().split('\n'))
                    if output_lines:
                        logger.error(f"   Последние строки вывода:")
                        for line in output_lines[-20:]:
                            logger.error(f"      {line}")
            except:
                pass
            if 'comfyui' in _process_pids:
                del _process_pids['comfyui']
            return False, None
        
        # Проверяем доступность API ComfyUI
        max_wait = 60  # Увеличено до 60 секунд для ComfyUI
        check_interval = 3
        elapsed = 0
        
        logger.info(f"⏳ Проверка доступности ComfyUI API (максимум {max_wait}s)...")
        while elapsed < max_wait:
            # Проверяем, что процесс все еще запущен
            if process.poll() is not None:
                logger.error(f"❌ ComfyUI процесс завершился во время ожидания (PID: {process.pid}, код: {process.returncode})")
                try:
                    remaining_output, _ = process.communicate(timeout=2)
                    with output_lock:
                        if remaining_output:
                            output_lines.extend(remaining_output.strip().split('\n'))
                        if output_lines:
                            logger.error(f"   Последние строки вывода:")
                            for line in output_lines[-10:]:
                                logger.error(f"      {line}")
                except:
                    pass
                if 'comfyui' in _process_pids:
                    del _process_pids['comfyui']
                return False, None
            
            is_running, _ = check_comfyui_running()
            if is_running:
                logger.info(f"✅ ComfyUI запущен и доступен (PID: {process.pid})")
                return True, process.pid
            
            elapsed += check_interval
            if elapsed < max_wait:
                logger.info(f"⏳ Ожидание доступности ComfyUI API... ({elapsed}s/{max_wait}s, процесс жив: PID {process.pid})")
                time.sleep(check_interval)
        
        # Проверяем финальный статус процесса
        if process.poll() is not None:
            logger.error(f"❌ ComfyUI процесс завершился (PID: {process.pid}, код: {process.returncode})")
            try:
                remaining_output, _ = process.communicate(timeout=2)
                with output_lock:
                    if remaining_output:
                        output_lines.extend(remaining_output.strip().split('\n'))
                    if output_lines:
                        logger.error(f"   Последние строки вывода:")
                        for line in output_lines[-20:]:
                            logger.error(f"      {line}")
            except:
                pass
            if 'comfyui' in _process_pids:
                del _process_pids['comfyui']
            return False, None
        
        # Выводим информацию о выводе процесса
        with output_lock:
            if output_lines:
                logger.info(f"ℹ️ ComfyUI вывод ({len(output_lines)} строк), последние строки:")
                for line in output_lines[-5:]:
                    logger.info(f"      {line}")
        
        logger.warning(f"⚠️ ComfyUI процесс запущен (PID: {process.pid}), но API не отвечает после ожидания {max_wait}s")
        logger.warning("   Возможно, ComfyUI еще инициализируется или есть проблемы с сетью")
        logger.warning(f"   Проверьте логи Process Manager для деталей")
        return True, process.pid  # Возвращаем True, так как процесс запущен
    except Exception as e:
        logger.error(f"❌ Ошибка запуска ComfyUI: {e}")
        return False, None


@app.get("/")
async def root():
    """Корневой эндпоинт"""
    return {
        "service": "Process Management API",
        "version": "1.0.0",
        "endpoints": {
            "switch": "POST /process/switch?service={ollama|comfyui}",
            "status": "GET /process/status",
            "stop": "POST /process/stop?service={ollama|comfyui}",
            "start": "POST /process/start?service={ollama|comfyui}"
        }
    }


@app.get("/process/status")
async def get_status() -> Dict:
    """Получает статус всех процессов"""
    ollama_running, ollama_pid = check_process_running('ollama.exe')
    comfyui_running, comfyui_pid = check_comfyui_running()
    
    return {
        "ollama": {
            "running": ollama_running,
            "pid": ollama_pid or _process_pids.get('ollama')
        },
        "comfyui": {
            "running": comfyui_running,
            "pid": comfyui_pid or _process_pids.get('comfyui')
        },
        "current_service": _current_service.value if _current_service else None
    }


@app.post("/process/switch")
async def switch_process(
    service: ServiceType = Query(..., description="Тип сервиса для переключения")
) -> SwitchResponse:
    """Переключает на указанный сервис (останавливает другой, запускает нужный)"""
    global _current_service
    start_time = time.time()
    previous_service = _current_service.value if _current_service else None
    
    try:
        if service == ServiceType.OLLAMA:
            # Останавливаем ComfyUI (всегда, даже если не отслежен)
            comfyui_running, _ = check_comfyui_running()
            if comfyui_running:
                logger.info("🛑 Остановка ComfyUI перед переключением на Ollama...")
                stop_comfyui()
                # Даем время на остановку
                time.sleep(2)
            
            # Также останавливаем Ollama, если он уже запущен (для перезапуска)
            ollama_running, _ = check_process_running('ollama.exe')
            if ollama_running and _current_service != ServiceType.OLLAMA:
                logger.info("🛑 Остановка текущего Ollama для перезапуска...")
                stop_ollama()
                time.sleep(1)
            
            # Запускаем Ollama
            success, pid = start_ollama()
            if success:
                _current_service = ServiceType.OLLAMA
                switch_time = time.time() - start_time
                logger.info(f"✅ Переключено на Ollama за {switch_time:.2f}s")
                return SwitchResponse(
                    success=True,
                    message="Переключено на Ollama",
                    previous_service=previous_service,
                    current_service="ollama",
                    switch_time=switch_time
                )
            else:
                raise HTTPException(status_code=500, detail="Не удалось запустить Ollama")
                
        elif service == ServiceType.COMFYUI:
            logger.info("🔄 Начало переключения на ComfyUI...")
            
            # Останавливаем Ollama (всегда, даже если не отслежен)
            ollama_running, _ = check_process_running('ollama.exe')
            if ollama_running:
                logger.info("🛑 Остановка Ollama перед переключением на ComfyUI...")
                stop_ollama()
                # Даем время на остановку
                time.sleep(2)
            else:
                logger.info("ℹ️ Ollama не запущен, пропускаем остановку")
            
            # Также останавливаем ComfyUI, если он уже запущен (для перезапуска)
            comfyui_running, _ = check_comfyui_running()
            if comfyui_running and _current_service != ServiceType.COMFYUI:
                logger.info("🛑 Остановка текущего ComfyUI для перезапуска...")
                stop_comfyui()
                time.sleep(1)
            else:
                logger.info("ℹ️ ComfyUI не запущен или уже активен, пропускаем остановку")
            
            # Запускаем ComfyUI
            logger.info("🚀 Попытка запуска ComfyUI...")
            success, pid = start_comfyui()
            logger.info(f"📊 Результат запуска ComfyUI: success={success}, pid={pid}")
            
            if success:
                _current_service = ServiceType.COMFYUI
                switch_time = time.time() - start_time
                logger.info(f"✅ Переключено на ComfyUI за {switch_time:.2f}s (PID: {pid})")
                return SwitchResponse(
                    success=True,
                    message="Переключено на ComfyUI",
                    previous_service=previous_service,
                    current_service="comfyui",
                    switch_time=switch_time
                )
            else:
                error_msg = f"Не удалось запустить ComfyUI (PID: {pid})"
                logger.error(f"❌ {error_msg}")
                raise HTTPException(status_code=500, detail=error_msg)
        else:
            raise HTTPException(status_code=400, detail="Неизвестный тип сервиса")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка переключения процесса: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка переключения: {str(e)}")


@app.post("/process/stop")
async def stop_process(
    service: ServiceType = Query(..., description="Тип сервиса для остановки")
) -> Dict:
    """Останавливает указанный процесс"""
    try:
        if service == ServiceType.OLLAMA:
            success = stop_ollama()
            if success:
                if _current_service == ServiceType.OLLAMA:
                    _current_service = None
                return {"success": True, "message": "Ollama остановлен"}
            else:
                raise HTTPException(status_code=500, detail="Не удалось остановить Ollama")
        elif service == ServiceType.COMFYUI:
            success = stop_comfyui()
            if success:
                if _current_service == ServiceType.COMFYUI:
                    _current_service = None
                return {"success": True, "message": "ComfyUI остановлен"}
            else:
                raise HTTPException(status_code=500, detail="Не удалось остановить ComfyUI")
        else:
            raise HTTPException(status_code=400, detail="Неизвестный тип сервиса")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка остановки процесса: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка остановки: {str(e)}")


@app.post("/process/start")
async def start_process(
    service: ServiceType = Query(..., description="Тип сервиса для запуска")
) -> Dict:
    """Запускает указанный процесс"""
    global _current_service
    try:
        if service == ServiceType.OLLAMA:
            success, pid = start_ollama()
            if success:
                _current_service = ServiceType.OLLAMA
                return {"success": True, "message": "Ollama запущен", "pid": pid}
            else:
                raise HTTPException(status_code=500, detail="Не удалось запустить Ollama")
        elif service == ServiceType.COMFYUI:
            success, pid = start_comfyui()
            if success:
                _current_service = ServiceType.COMFYUI
                return {"success": True, "message": "ComfyUI запущен", "pid": pid}
            else:
                raise HTTPException(status_code=500, detail="Не удалось запустить ComfyUI")
        else:
            raise HTTPException(status_code=400, detail="Неизвестный тип сервиса")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Ошибка запуска процесса: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка запуска: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PROCESS_API_PORT", "8888"))
    uvicorn.run(app, host="0.0.0.0", port=port)

