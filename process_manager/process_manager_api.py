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
        logger.debug(f"🔍 [CHECK_PROCESS] Проверка процесса: {process_name}")
        result = subprocess.run(
            ['tasklist', '/fi', f'imagename eq {process_name}'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        logger.debug(f"📊 [CHECK_PROCESS] tasklist returncode: {result.returncode}")
        logger.debug(f"📊 [CHECK_PROCESS] tasklist stdout длина: {len(result.stdout)} символов")
        
        if process_name in result.stdout:
            logger.debug(f"✅ [CHECK_PROCESS] Процесс {process_name} найден в выводе tasklist")
            # Пытаемся извлечь PID из вывода
            lines = result.stdout.split('\n')
            logger.debug(f"📊 [CHECK_PROCESS] Количество строк в выводе: {len(lines)}")
            for line_num, line in enumerate(lines):
                if process_name in line:
                    logger.debug(f"📊 [CHECK_PROCESS] Найдена строка с процессом (строка {line_num}): {line[:100]}")
                    parts = line.split()
                    logger.debug(f"📊 [CHECK_PROCESS] Разделенные части строки: {parts}")
                    if len(parts) >= 2:
                        try:
                            pid = int(parts[1])
                            logger.info(f"✅ [CHECK_PROCESS] Процесс {process_name} запущен, PID: {pid}")
                            return True, pid
                        except (ValueError, IndexError) as parse_error:
                            logger.warning(f"⚠️ [CHECK_PROCESS] Ошибка парсинга PID из строки: {parse_error}, строка: {line}")
                            pass
            logger.warning(f"⚠️ [CHECK_PROCESS] Процесс {process_name} найден в выводе, но не удалось извлечь PID")
            return True, None
        else:
            logger.debug(f"ℹ️ [CHECK_PROCESS] Процесс {process_name} не найден в выводе tasklist")
            return False, None
    except subprocess.TimeoutExpired:
        logger.error(f"❌ [CHECK_PROCESS] Таймаут проверки процесса {process_name}")
        return False, None
    except Exception as e:
        logger.error(f"❌ [CHECK_PROCESS] Ошибка проверки процесса {process_name}: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"❌ [CHECK_PROCESS] Трассировка:\n{traceback.format_exc()}")
        return False, None


def stop_ollama() -> bool:
    """Останавливает процесс Ollama"""
    try:
        logger.info("🛑 [STOP_OLLAMA] Начало остановки Ollama...")
        
        # Сначала проверяем, запущен ли процесс
        logger.info("🔍 [STOP_OLLAMA] Шаг 1: Проверка существующих процессов Ollama...")
        is_running, pid = check_process_running('ollama.exe')
        logger.info(f"📊 [STOP_OLLAMA] Результат проверки: is_running={is_running}, pid={pid}")
        
        if not is_running:
            logger.info("ℹ️ [STOP_OLLAMA] Ollama не запущен, пропускаем остановку")
            if 'ollama' in _process_pids:
                logger.info(f"📊 [STOP_OLLAMA] Удаляем PID из _process_pids: {_process_pids.get('ollama')}")
                del _process_pids['ollama']
            return True
        
        logger.info(f"🛑 [STOP_OLLAMA] Остановка Ollama (PID: {pid})...")
        logger.info(f"📊 [STOP_OLLAMA] Текущий PID в _process_pids: {_process_pids.get('ollama')}")
        
        # Пробуем остановить через taskkill
        logger.info("🔍 [STOP_OLLAMA] Шаг 2: Выполнение taskkill /f /im ollama.exe...")
        try:
            result = subprocess.run(
                ['taskkill', '/f', '/im', 'ollama.exe'],
                capture_output=True,
                text=True,
                timeout=10
            )
            logger.info(f"📊 [STOP_OLLAMA] taskkill завершен: returncode={result.returncode}")
            logger.info(f"📊 [STOP_OLLAMA] taskkill stdout: {result.stdout[:200] if result.stdout else 'пусто'}")
            if result.stderr:
                logger.warning(f"⚠️ [STOP_OLLAMA] taskkill stderr: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            logger.error(f"❌ [STOP_OLLAMA] Таймаут выполнения taskkill")
            return False
        except Exception as taskkill_error:
            logger.error(f"❌ [STOP_OLLAMA] Ошибка выполнения taskkill: {type(taskkill_error).__name__}: {taskkill_error}")
            return False
        
        # Ждем немного, чтобы процесс завершился
        logger.info("🔍 [STOP_OLLAMA] Шаг 3: Ожидание завершения процесса (1 секунда)...")
        time.sleep(1)
        
        # Проверяем, действительно ли процесс остановлен
        logger.info("🔍 [STOP_OLLAMA] Шаг 4: Проверка, остановлен ли процесс...")
        is_still_running, remaining_pid = check_process_running('ollama.exe')
        logger.info(f"📊 [STOP_OLLAMA] Результат проверки: is_still_running={is_still_running}, remaining_pid={remaining_pid}")
        
        if is_still_running:
            logger.warning(f"⚠️ [STOP_OLLAMA] Ollama все еще запущен после taskkill, пробуем остановить по PID {remaining_pid}...")
            # Пробуем остановить по PID
            try:
                logger.info(f"🔍 [STOP_OLLAMA] Шаг 5: Выполнение taskkill /f /pid {remaining_pid}...")
                pid_result = subprocess.run(
                    ['taskkill', '/f', '/pid', str(remaining_pid)],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                logger.info(f"📊 [STOP_OLLAMA] taskkill по PID завершен: returncode={pid_result.returncode}")
                logger.info(f"📊 [STOP_OLLAMA] taskkill по PID stdout: {pid_result.stdout[:200] if pid_result.stdout else 'пусто'}")
                if pid_result.stderr:
                    logger.warning(f"⚠️ [STOP_OLLAMA] taskkill по PID stderr: {pid_result.stderr[:200]}")
                time.sleep(1)
            except Exception as pid_kill_error:
                logger.error(f"❌ [STOP_OLLAMA] Ошибка остановки по PID: {type(pid_kill_error).__name__}: {pid_kill_error}")
        
        # Финальная проверка
        logger.info("🔍 [STOP_OLLAMA] Шаг 6: Финальная проверка остановки процесса...")
        is_still_running, final_pid = check_process_running('ollama.exe')
        logger.info(f"📊 [STOP_OLLAMA] Финальная проверка: is_still_running={is_still_running}, final_pid={final_pid}")
        
        if is_still_running:
            logger.error(f"❌ [STOP_OLLAMA] Не удалось остановить Ollama, процесс все еще запущен (PID: {final_pid})")
            return False
        
        logger.info("✅ [STOP_OLLAMA] Ollama успешно остановлен")
        if 'ollama' in _process_pids:
            logger.info(f"📊 [STOP_OLLAMA] Удаляем PID из _process_pids: {_process_pids.get('ollama')}")
            del _process_pids['ollama']
        return True
        
    except Exception as e:
        logger.error(f"❌ [STOP_OLLAMA] Критическая ошибка остановки Ollama: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"❌ [STOP_OLLAMA] Трассировка ошибки:\n{traceback.format_exc()}")
        return False


def start_ollama() -> Tuple[bool, Optional[int]]:
    """Запускает процесс Ollama"""
    try:
        logger.info("🚀 [START_OLLAMA] Начало запуска Ollama...")
        
        # Проверяем, не запущен ли уже
        logger.info("🔍 [START_OLLAMA] Шаг 1: Проверка существующих процессов Ollama...")
        is_running, pid = check_process_running('ollama.exe')
        logger.info(f"📊 [START_OLLAMA] Результат проверки: is_running={is_running}, pid={pid}")
        
        if is_running:
            logger.info(f"ℹ️ [START_OLLAMA] Ollama уже запущен (PID: {pid}), проверяем доступность API...")
            _process_pids['ollama'] = pid
            
            # Проверяем, действительно ли API доступен
            try:
                logger.info("🔍 [START_OLLAMA] Шаг 2: Проверка доступности API существующего процесса...")
                import httpx
                with httpx.Client(timeout=3.0) as client:
                    response = client.get("http://127.0.0.1:11434/api/tags")
                    logger.info(f"📊 [START_OLLAMA] Ответ API: статус={response.status_code}")
                    if response.status_code == 200:
                        logger.info(f"✅ [START_OLLAMA] Ollama уже запущен и доступен (PID: {pid})")
                        return True, pid
                    else:
                        logger.warning(f"⚠️ [START_OLLAMA] Ollama запущен, но API не отвечает (статус: {response.status_code}), перезапускаем...")
                        # Останавливаем и перезапускаем
                        stop_ollama()
                        time.sleep(2)
            except Exception as api_check_error:
                logger.warning(f"⚠️ [START_OLLAMA] Ollama запущен, но API недоступен: {api_check_error}, перезапускаем...")
                logger.error(f"❌ [START_OLLAMA] Детали ошибки API: {type(api_check_error).__name__}: {str(api_check_error)}")
                # Останавливаем и перезапускаем
                stop_ollama()
                time.sleep(2)
        
        # Находим ollama.exe
        logger.info("🔍 [START_OLLAMA] Шаг 3: Поиск исполняемого файла ollama.exe...")
        logger.info(f"📊 [START_OLLAMA] OLLAMA_PATH из env: {OLLAMA_PATH}")
        
        ollama_exe = None
        if OLLAMA_PATH:
            ollama_exe = Path(OLLAMA_PATH) / "ollama.exe"
            logger.info(f"📊 [START_OLLAMA] Путь из OLLAMA_PATH: {ollama_exe}")
            if not ollama_exe.exists():
                logger.warning(f"⚠️ [START_OLLAMA] Файл не найден по пути OLLAMA_PATH, пробуем найти в PATH...")
                # Пробуем найти в PATH
                ollama_exe = "ollama.exe"
            else:
                logger.info(f"✅ [START_OLLAMA] Файл найден: {ollama_exe}")
        else:
            logger.info("📊 [START_OLLAMA] OLLAMA_PATH не установлен, пробуем найти в PATH...")
            # Пробуем найти в PATH
            ollama_exe = "ollama.exe"
        
        logger.info(f"📊 [START_OLLAMA] Финальный путь к ollama.exe: {ollama_exe}")
        
        # Устанавливаем переменные окружения
        logger.info("🔍 [START_OLLAMA] Шаг 4: Настройка переменных окружения...")
        env = os.environ.copy()
        env['OLLAMA_ORIGINS'] = '*'
        env['OLLAMA_HOST'] = '0.0.0.0:11434'
        logger.info(f"📊 [START_OLLAMA] Переменные окружения: OLLAMA_ORIGINS={env.get('OLLAMA_ORIGINS')}, OLLAMA_HOST={env.get('OLLAMA_HOST')}")
        
        # Запускаем процесс
        logger.info("🔍 [START_OLLAMA] Шаг 5: Запуск процесса Ollama...")
        cwd = Path(OLLAMA_PATH) if OLLAMA_PATH else None
        logger.info(f"📊 [START_OLLAMA] Рабочая директория: {cwd}")
        logger.info(f"📊 [START_OLLAMA] Команда запуска: {ollama_exe} serve")
        
        try:
            process = subprocess.Popen(
                [str(ollama_exe), 'serve'],
                env=env,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logger.info(f"✅ [START_OLLAMA] Процесс запущен, PID: {process.pid}")
            logger.info(f"📊 [START_OLLAMA] Статус процесса: returncode={process.returncode}")
        except FileNotFoundError as fnf_error:
            logger.error(f"❌ [START_OLLAMA] Файл не найден: {fnf_error}")
            logger.error(f"❌ [START_OLLAMA] Путь, который пытались использовать: {ollama_exe}")
            return False, None
        except PermissionError as perm_error:
            logger.error(f"❌ [START_OLLAMA] Ошибка прав доступа: {perm_error}")
            return False, None
        except Exception as start_error:
            logger.error(f"❌ [START_OLLAMA] Ошибка запуска процесса: {type(start_error).__name__}: {start_error}")
            return False, None
        
        _process_pids['ollama'] = process.pid
        logger.info(f"✅ [START_OLLAMA] PID сохранен в _process_pids: {_process_pids.get('ollama')}")
        
        # Проверяем, что процесс действительно запустился
        logger.info("🔍 [START_OLLAMA] Шаг 6: Проверка статуса запущенного процесса...")
        time.sleep(1)  # Даем время процессу запуститься
        process_status = process.poll()
        logger.info(f"📊 [START_OLLAMA] Статус процесса после запуска: poll()={process_status} (None=работает, число=завершен)")
        
        if process_status is not None:
            # Процесс завершился сразу после запуска
            logger.error(f"❌ [START_OLLAMA] Процесс завершился сразу после запуска! Код возврата: {process_status}")
            try:
                stdout, stderr = process.communicate(timeout=5)
                if stdout:
                    logger.error(f"❌ [START_OLLAMA] STDOUT процесса: {stdout.decode('utf-8', errors='ignore')[:500]}")
                if stderr:
                    logger.error(f"❌ [START_OLLAMA] STDERR процесса: {stderr.decode('utf-8', errors='ignore')[:500]}")
            except Exception as comm_error:
                logger.error(f"❌ [START_OLLAMA] Ошибка чтения вывода процесса: {comm_error}")
            return False, None
        
        # Ждем инициализацию и проверяем доступность
        logger.info("🔍 [START_OLLAMA] Шаг 7: Ожидание инициализации Ollama (3 секунды)...")
        time.sleep(3)
        
        # Проверяем доступность Ollama API
        logger.info("🔍 [START_OLLAMA] Шаг 8: Проверка доступности Ollama API...")
        max_wait = 15  # Максимум 15 секунд на проверку
        check_interval = 1
        elapsed = 0
        
        while elapsed < max_wait:
            try:
                import httpx
                logger.info(f"📊 [START_OLLAMA] Попытка подключения к API (попытка {elapsed + 1}/{max_wait})...")
                with httpx.Client(timeout=2.0) as client:
                    response = client.get("http://127.0.0.1:11434/api/tags")
                    logger.info(f"📊 [START_OLLAMA] Ответ API: статус={response.status_code}")
                    if response.status_code == 200:
                        logger.info(f"✅ [START_OLLAMA] Ollama доступен (PID: {process.pid}, время ожидания: {elapsed}s)")
                        return True, process.pid
                    else:
                        logger.warning(f"⚠️ [START_OLLAMA] API вернул статус {response.status_code}, продолжаем ожидание...")
            except httpx.ConnectError as conn_error:
                logger.debug(f"🔍 [START_OLLAMA] Ошибка подключения (попытка {elapsed + 1}): {conn_error}")
            except httpx.TimeoutException as timeout_error:
                logger.debug(f"🔍 [START_OLLAMA] Таймаут подключения (попытка {elapsed + 1}): {timeout_error}")
            except Exception as api_error:
                logger.warning(f"⚠️ [START_OLLAMA] Ошибка проверки API (попытка {elapsed + 1}): {type(api_error).__name__}: {api_error}")
            
            elapsed += check_interval
            if elapsed < max_wait:
                time.sleep(check_interval)
        
        # Проверяем статус процесса после таймаута
        process_status_after = process.poll()
        logger.warning(f"⚠️ [START_OLLAMA] Таймаут ожидания API. Статус процесса: poll()={process_status_after}")
        if process_status_after is not None:
            logger.error(f"❌ [START_OLLAMA] Процесс завершился во время ожидания! Код возврата: {process_status_after}")
            try:
                stdout, stderr = process.communicate(timeout=5)
                if stdout:
                    logger.error(f"❌ [START_OLLAMA] STDOUT: {stdout.decode('utf-8', errors='ignore')[:500]}")
                if stderr:
                    logger.error(f"❌ [START_OLLAMA] STDERR: {stderr.decode('utf-8', errors='ignore')[:500]}")
            except:
                pass
            return False, None
        
        logger.warning("⚠️ [START_OLLAMA] Ollama запущен, но API не отвечает после ожидания")
        return True, process.pid  # Возвращаем True, так как процесс запущен
    except Exception as e:
        logger.error(f"❌ [START_OLLAMA] Критическая ошибка запуска Ollama: {type(e).__name__}: {e}")
        import traceback
        logger.error(f"❌ [START_OLLAMA] Трассировка ошибки:\n{traceback.format_exc()}")
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
    
    logger.info(f"🔄 [SWITCH_PROCESS] ========== НАЧАЛО ПЕРЕКЛЮЧЕНИЯ ==========")
    logger.info(f"📊 [SWITCH_PROCESS] Текущий сервис: {previous_service}")
    logger.info(f"📊 [SWITCH_PROCESS] Целевой сервис: {service.value}")
    logger.info(f"📊 [SWITCH_PROCESS] Время начала: {time.strftime('%H:%M:%S')}")
    
    try:
        if service == ServiceType.OLLAMA:
            logger.info("🔄 [SWITCH_PROCESS] Переключение на Ollama...")
            
            # Останавливаем ComfyUI (всегда, даже если не отслежен)
            logger.info("🔍 [SWITCH_PROCESS] Шаг 1: Проверка ComfyUI...")
            comfyui_running, comfyui_pid = check_comfyui_running()
            logger.info(f"📊 [SWITCH_PROCESS] ComfyUI запущен: {comfyui_running}, PID: {comfyui_pid}")
            if comfyui_running:
                logger.info("🛑 [SWITCH_PROCESS] Остановка ComfyUI перед переключением на Ollama...")
                stop_result = stop_comfyui()
                logger.info(f"📊 [SWITCH_PROCESS] Результат остановки ComfyUI: {stop_result}")
                # Даем время на остановку
                logger.info("⏳ [SWITCH_PROCESS] Ожидание остановки ComfyUI (2 секунды)...")
                time.sleep(2)
            
            # Проверяем, запущена ли Ollama и доступна ли она
            logger.info("🔍 [SWITCH_PROCESS] Шаг 2: Проверка текущего состояния Ollama...")
            ollama_running, ollama_pid = check_process_running('ollama.exe')
            logger.info(f"📊 [SWITCH_PROCESS] Ollama запущен: {ollama_running}, PID: {ollama_pid}")
            
            # Проверяем доступность Ollama API
            ollama_available = False
            if ollama_running:
                try:
                    import httpx
                    with httpx.Client(timeout=3.0) as client:
                        response = client.get("http://127.0.0.1:11434/api/tags")
                        if response.status_code == 200:
                            ollama_available = True
                            logger.info("✅ [SWITCH_PROCESS] Ollama уже запущена и доступна, пропускаем перезапуск")
                except Exception as e:
                    logger.warning(f"⚠️ [SWITCH_PROCESS] Ollama запущена, но API недоступна: {e}")
            
            # Если Ollama уже запущена и доступна, просто обновляем состояние
            if ollama_available:
                _current_service = ServiceType.OLLAMA
                switch_time = time.time() - start_time
                logger.info(f"✅ [SWITCH_PROCESS] ========== OLLAMA УЖЕ АКТИВНА ==========")
                logger.info(f"📊 [SWITCH_PROCESS] Время проверки: {switch_time:.2f}s")
                logger.info(f"📊 [SWITCH_PROCESS] PID процесса: {ollama_pid}")
                return SwitchResponse(
                    success=True,
                    message="Ollama уже активна",
                    previous_service=previous_service,
                    current_service="ollama",
                    switch_time=switch_time
                )
            
            # Если Ollama не запущена или недоступна, запускаем/перезапускаем
            if ollama_running:
                logger.info("🛑 [SWITCH_PROCESS] Ollama запущена, но недоступна. Остановка перед перезапуском...")
                stop_result = stop_ollama()
                logger.info(f"📊 [SWITCH_PROCESS] Результат остановки Ollama: {stop_result}")
                # Даем время на полную остановку
                logger.info("⏳ [SWITCH_PROCESS] Ожидание остановки Ollama (2 секунды)...")
                time.sleep(2)
                
                # Проверяем, что Ollama действительно остановлен
                ollama_still_running, still_running_pid = check_process_running('ollama.exe')
                if ollama_still_running:
                    logger.warning("⚠️ [SWITCH_PROCESS] Ollama все еще запущен после остановки, ждем еще...")
                    time.sleep(2)
                    stop_ollama()
                    time.sleep(1)
            
            # Запускаем Ollama
            logger.info("🔍 [SWITCH_PROCESS] Шаг 3: Запуск Ollama...")
            success, pid = start_ollama()
            logger.info(f"📊 [SWITCH_PROCESS] Результат запуска Ollama: success={success}, pid={pid}")
            
            if success:
                _current_service = ServiceType.OLLAMA
                switch_time = time.time() - start_time
                logger.info(f"✅ [SWITCH_PROCESS] ========== ПЕРЕКЛЮЧЕНО НА OLLAMA ==========")
                logger.info(f"📊 [SWITCH_PROCESS] Время переключения: {switch_time:.2f}s")
                logger.info(f"📊 [SWITCH_PROCESS] PID процесса: {pid}")
                return SwitchResponse(
                    success=True,
                    message="Переключено на Ollama",
                    previous_service=previous_service,
                    current_service="ollama",
                    switch_time=switch_time
                )
            else:
                logger.error(f"❌ [SWITCH_PROCESS] ========== ОШИБКА ПЕРЕКЛЮЧЕНИЯ НА OLLAMA ==========")
                logger.error(f"❌ [SWITCH_PROCESS] start_ollama() вернул success=False, pid={pid}")
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
                
                # Проверяем, что Ollama действительно остановлен
                ollama_still_running, _ = check_process_running('ollama.exe')
                if ollama_still_running:
                    logger.warning("⚠️ Ollama все еще запущен после остановки, пробуем еще раз...")
                    stop_ollama()
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
        logger.error(f"❌ [SWITCH_PROCESS] ========== КРИТИЧЕСКАЯ ОШИБКА ПЕРЕКЛЮЧЕНИЯ ==========")
        logger.error(f"❌ [SWITCH_PROCESS] Тип ошибки: {type(e).__name__}")
        logger.error(f"❌ [SWITCH_PROCESS] Сообщение: {str(e)}")
        import traceback
        logger.error(f"❌ [SWITCH_PROCESS] Трассировка:\n{traceback.format_exc()}")
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

