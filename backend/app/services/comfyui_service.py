"""
Сервис для работы с ComfyUI API для генерации изображений
"""
import httpx
import json
import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple
from ..config import settings
from .resource_manager import resource_manager
from .service_types import ServiceType

logger = logging.getLogger(__name__)


class ComfyUIService:
    """Сервис для генерации изображений через ComfyUI API"""
    
    def __init__(self):
        """Инициализация сервиса ComfyUI"""
        self.base_url = self._detect_comfyui_url()
        self.model = settings.COMFYUI_MODEL
        self.timeout = settings.COMFYUI_TIMEOUT
        self.retry_attempts = settings.COMFYUI_RETRY_ATTEMPTS
        self.workflow_path = settings.COMFYUI_WORKFLOW_PATH
        self.workflow_template = self._load_workflow_template()
        
    def _detect_comfyui_url(self) -> str:
        """
        Определяет доступный URL ComfyUI из настроек или автоматически
        """
        # Список адресов для проверки (в порядке приоритета)
        urls_to_try = []
        
        # 1. Если указан COMFYUI_URL в настройках, используем его первым
        if settings.COMFYUI_URL:
            urls_to_try.append(settings.COMFYUI_URL)
        
        # 2. Проверяем, используется ли Process Manager API
        # Если используется, ComfyUI запускается локально на 127.0.0.1:8188
        if settings.PROCESS_MANAGER_API_URL:
            local_url = "http://127.0.0.1:8188"
            if local_url not in urls_to_try:
                urls_to_try.append(local_url)
        
        # 3. Добавляем локальный адрес по умолчанию
        default_local = "http://127.0.0.1:8188"
        if default_local not in urls_to_try:
            urls_to_try.append(default_local)
        
        # Если ничего не указано, используем локальный адрес
        if not urls_to_try:
            urls_to_try.append(default_local)
        
        # Проверяем доступность каждого адреса
        import httpx
        for url in urls_to_try:
            try:
                with httpx.Client(timeout=2.0) as client:
                    response = client.get(f"{url}/system_stats")
                    if response.status_code == 200:
                        logger.info(f"✅ ComfyUI обнаружен на {url}")
                        return url
            except httpx.ConnectError:
                logger.debug(f"⚠️ ComfyUI недоступен на {url} (ConnectionError)")
                continue
            except httpx.TimeoutException:
                logger.debug(f"⚠️ Таймаут подключения к {url}")
                continue
            except Exception as e:
                logger.debug(f"⚠️ Ошибка проверки {url}: {e}")
                continue
        
        # Если ни один адрес не доступен, выбираем приоритетный
        # Если Process Manager используется, используем локальный адрес
        if settings.PROCESS_MANAGER_API_URL:
            selected_url = "http://127.0.0.1:8188"
            logger.info(f"ℹ️ ComfyUI недоступен сейчас, но будет запущен через Process Manager на {selected_url}")
            return selected_url
        
        # Иначе используем первый из списка (из настроек или локальный)
        selected_url = urls_to_try[0]
        logger.warning(f"⚠️ ComfyUI недоступен на всех проверенных адресах, используем {selected_url}")
        return selected_url
    
    def _load_workflow_template(self) -> Optional[Dict]:
        """
        Загружает шаблон workflow из JSON файла
        
        Returns:
            Словарь с workflow или None если файл не найден
        """
        if not self.workflow_path:
            logger.warning("⚠️ COMFYUI_WORKFLOW_PATH не установлен, будет использован программный workflow")
            return None
        
        workflow_file = Path(self.workflow_path)
        if not workflow_file.exists():
            logger.warning(f"⚠️ Файл workflow не найден: {self.workflow_path}, будет использован программный workflow")
            return None
        
        try:
            with open(workflow_file, 'r', encoding='utf-8') as f:
                workflow_data = json.load(f)
                logger.info(f"✅ Workflow шаблон загружен из {self.workflow_path}")
                
                # ComfyUI экспортирует workflow в формате API, где есть поле "prompt"
                if "prompt" in workflow_data:
                    return workflow_data["prompt"]
                elif isinstance(workflow_data, dict) and any(isinstance(v, dict) for v in workflow_data.values()):
                    # Если это уже формат prompt (словарь с нодами)
                    return workflow_data
                else:
                    logger.warning("⚠️ Неизвестный формат workflow, будет использован программный workflow")
                    return None
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки workflow шаблона: {e}")
            return None
    
    def _update_url_if_needed(self) -> bool:
        """
        Обновляет base_url если ComfyUI стал доступен на другом адресе
        (например, был запущен через Process Manager)
        
        Returns:
            True если URL был обновлен
        """
        # Проверяем локальный адрес, если используется Process Manager
        if settings.PROCESS_MANAGER_API_URL:
            local_url = "http://127.0.0.1:8188"
            if self.base_url != local_url:
                try:
                    import httpx
                    with httpx.Client(timeout=2.0) as client:
                        response = client.get(f"{local_url}/system_stats")
                        if response.status_code == 200:
                            logger.info(f"✅ ComfyUI доступен на {local_url}, обновляем URL")
                            self.base_url = local_url
                            return True
                        else:
                            logger.debug(f"⚠️ ComfyUI на {local_url} вернул статус {response.status_code}")
                except httpx.ConnectError as e:
                    logger.debug(f"⚠️ Не удалось подключиться к ComfyUI на {local_url}: {e}")
                except httpx.TimeoutException:
                    logger.debug(f"⚠️ Таймаут подключения к ComfyUI на {local_url}")
                except Exception as e:
                    logger.debug(f"⚠️ Ошибка проверки ComfyUI на {local_url}: {e}")
        
        return False
    
    async def check_connection(self) -> bool:
        """Проверяет доступность ComfyUI сервера"""
        # Сначала пытаемся обновить URL, если нужно
        self._update_url_if_needed()
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/system_stats")
                if response.status_code == 200:
                    logger.debug(f"✅ ComfyUI доступен на {self.base_url}")
                    return True
                else:
                    logger.warning(f"⚠️ ComfyUI на {self.base_url} вернул статус {response.status_code}")
                    # Если текущий URL не работает, пытаемся найти рабочий
                    if self._update_url_if_needed():
                        # Повторная проверка с новым URL
                        response = await client.get(f"{self.base_url}/system_stats")
                        if response.status_code == 200:
                            logger.info(f"✅ ComfyUI доступен после обновления URL на {self.base_url}")
                            return True
                    return False
        except httpx.ConnectError as e:
            logger.error(f"❌ Ошибка подключения к ComfyUI на {self.base_url}: {e}")
            # Если подключение не удалось, пытаемся обновить URL
            if self._update_url_if_needed():
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        response = await client.get(f"{self.base_url}/system_stats")
                        if response.status_code == 200:
                            logger.info(f"✅ ComfyUI доступен после обновления URL на {self.base_url}")
                            return True
                except Exception as retry_e:
                    logger.error(f"❌ Повторная попытка подключения к ComfyUI не удалась: {retry_e}")
            return False
        except httpx.TimeoutException:
            logger.error(f"❌ Таймаут подключения к ComfyUI на {self.base_url}")
            return False
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при проверке подключения к ComfyUI на {self.base_url}: {e}")
            return False
    
    def create_workflow(self, prompt: str, negative_prompt: str, width: int = 1024, height: int = 1024) -> Dict:
        """
        Создает workflow JSON для ComfyUI, используя шаблон или программное создание
        
        Args:
            prompt: Положительный промпт на английском
            negative_prompt: Негативный промпт на английском
            width: Ширина изображения (по умолчанию 1024)
            height: Высота изображения (по умолчанию 1024)
            
        Returns:
            Словарь с workflow для ComfyUI
        """
        # Если есть шаблон, используем его
        if self.workflow_template:
            return self._create_workflow_from_template(prompt, negative_prompt, width, height)
        else:
            # Fallback на программное создание
            return self._create_workflow_programmatic(prompt, negative_prompt, width, height)
    
    def _create_workflow_from_template(self, prompt: str, negative_prompt: str, width: int, height: int) -> Dict:
        """
        Создает workflow из шаблона, обновляя промпты и размеры
        
        Args:
            prompt: Положительный промпт
            negative_prompt: Негативный промпт
            width: Ширина изображения
            height: Высота изображения
            
        Returns:
            Обновленный workflow
        """
        import copy
        workflow = copy.deepcopy(self.workflow_template)
        
        # Ищем ноды CLIPTextEncode для обновления промптов
        positive_node = None
        negative_node = None
        
        for node_id, node_data in workflow.items():
            if isinstance(node_data, dict) and node_data.get("class_type") == "CLIPTextEncode":
                inputs = node_data.get("inputs", {})
                text = inputs.get("text", "")
                
                # Определяем положительный или негативный промпт по содержимому или позиции
                # Обычно негативный промпт содержит слова типа "negative", "bad", "blurry"
                if not positive_node:
                    # Первая найденная нода - обычно положительная
                    positive_node = node_id
                elif not negative_node:
                    # Вторая найденная нода - обычно негативная
                    negative_node = node_id
                    # Проверяем содержимое для уверенности
                    if any(word in text.lower() for word in ["negative", "bad", "blurry", "low quality"]):
                        # Меняем местами
                        positive_node, negative_node = negative_node, positive_node
        
        # Если не нашли две ноды, используем первую для positive, вторую для negative
        if not negative_node:
            nodes = [node_id for node_id, node_data in workflow.items() 
                    if isinstance(node_data, dict) and node_data.get("class_type") == "CLIPTextEncode"]
            if len(nodes) >= 2:
                positive_node = nodes[0]
                negative_node = nodes[1]
            elif len(nodes) == 1:
                positive_node = nodes[0]
                logger.warning("⚠️ Найдена только одна CLIPTextEncode нода, используем её для positive промпта")
        
        # Обновляем промпты
        if positive_node:
            workflow[positive_node]["inputs"]["text"] = prompt
            logger.debug(f"✅ Обновлен positive промпт в ноде {positive_node[:8]}")
        
        if negative_node:
            workflow[negative_node]["inputs"]["text"] = negative_prompt
            logger.debug(f"✅ Обновлен negative промпт в ноде {negative_node[:8]}")
        elif positive_node:
            logger.warning("⚠️ Не найдена нода для negative промпта")
        
        # Ищем ноды, которые могут содержать размеры изображения
        # EmptyLatentImage - стандартная нода для размеров
        # Также могут быть другие ноды с width/height
        size_updated = False
        
        # Список возможных типов нод, которые могут содержать размеры
        size_node_types = [
            "EmptyLatentImage",
            "LatentUpscale",
            "ImageUpscale",
            "VAEDecode",
            "VAEEncode",
            "KSampler",
            "KSamplerAdvanced"
        ]
        
        # Сначала ищем EmptyLatentImage (приоритет)
        for node_id, node_data in workflow.items():
            if isinstance(node_data, dict) and node_data.get("class_type") == "EmptyLatentImage":
                if "inputs" in node_data:
                    node_data["inputs"]["width"] = width
                    node_data["inputs"]["height"] = height
                    logger.info(f"✅ Обновлены размеры в EmptyLatentImage ноде {node_id[:8]}: {width}x{height}")
                    size_updated = True
                    break
        
        # Если не нашли EmptyLatentImage, ищем любую ноду с width/height в inputs
        if not size_updated:
            logger.debug(f"🔍 EmptyLatentImage не найдена, ищем другие ноды с width/height...")
            nodes_with_size = []
            for node_id, node_data in workflow.items():
                if isinstance(node_data, dict) and "inputs" in node_data:
                    inputs = node_data.get("inputs", {})
                    if "width" in inputs or "height" in inputs:
                        class_type = node_data.get("class_type", "unknown")
                        current_w = inputs.get("width", "N/A")
                        current_h = inputs.get("height", "N/A")
                        nodes_with_size.append({
                            "node_id": node_id,
                            "class_type": class_type,
                            "width": current_w,
                            "height": current_h
                        })
            
            if nodes_with_size:
                logger.debug(f"🔍 Найдено {len(nodes_with_size)} нод(ы) с размерами:")
                for node_info in nodes_with_size:
                    logger.debug(f"   - {node_info['class_type']} ({node_info['node_id'][:8]}): {node_info['width']}x{node_info['height']}")
                
                # Обновляем первую найденную ноду с размерами
                first_node = nodes_with_size[0]
                node_id = first_node["node_id"]
                workflow[node_id]["inputs"]["width"] = width
                workflow[node_id]["inputs"]["height"] = height
                logger.info(f"✅ Обновлены размеры в ноде {first_node['class_type']} ({node_id[:8]}): {width}x{height}")
                size_updated = True
            else:
                logger.warning(f"⚠️ Не найдено ни одной ноды с width/height в workflow")
        
        if not size_updated:
            logger.error(f"❌ Не удалось обновить размеры в workflow (width={width}, height={height})")
            logger.debug(f"🔍 Доступные ноды в workflow:")
            for node_id, node_data in workflow.items():
                if isinstance(node_data, dict):
                    class_type = node_data.get("class_type", "unknown")
                    logger.debug(f"   - {class_type} ({node_id[:8]})")
        
        # Обновляем seed в KSampler (если есть)
        for node_id, node_data in workflow.items():
            if isinstance(node_data, dict) and node_data.get("class_type") == "KSampler":
                if "seed" in node_data.get("inputs", {}):
                    # Устанавливаем seed в 0 для случайной генерации
                    node_data["inputs"]["seed"] = 0
                    logger.debug(f"✅ Обновлен seed в ноде {node_id[:8]}")
                break
        
        return workflow
    
    def _create_workflow_programmatic(self, prompt: str, negative_prompt: str, width: int, height: int) -> Dict:
        """
        Создает workflow программно (fallback метод)
        
        Args:
            prompt: Положительный промпт на английском
            negative_prompt: Негативный промпт на английском
            width: Ширина изображения
            height: Высота изображения
            
        Returns:
            Словарь с workflow для ComfyUI
        """
        # Генерируем уникальные ID для нод
        import uuid
        
        # Создаем базовые ID для нод
        checkpoint_loader = str(uuid.uuid4())
        clip_text_encode_pos = str(uuid.uuid4())
        clip_text_encode_neg = str(uuid.uuid4())
        empty_latent = str(uuid.uuid4())
        ksampler = str(uuid.uuid4())
        vae_decode = str(uuid.uuid4())
        save_image = str(uuid.uuid4())
        
        workflow = {
            checkpoint_loader: {
                "inputs": {
                    "ckpt_name": f"{self.model}.safetensors"
                },
                "class_type": "CheckpointLoaderSimple"
            },
            clip_text_encode_pos: {
                "inputs": {
                    "text": prompt,
                    "clip": [checkpoint_loader, 1]
                },
                "class_type": "CLIPTextEncode"
            },
            clip_text_encode_neg: {
                "inputs": {
                    "text": negative_prompt,
                    "clip": [checkpoint_loader, 1]
                },
                "class_type": "CLIPTextEncode"
            },
            empty_latent: {
                "inputs": {
                    "width": width,
                    "height": height,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            ksampler: {
                "inputs": {
                    "seed": 0,  # 0 = случайный seed (ComfyUI не принимает -1)
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": [checkpoint_loader, 0],
                    "positive": [clip_text_encode_pos, 0],
                    "negative": [clip_text_encode_neg, 0],
                    "latent_image": [empty_latent, 0]
                },
                "class_type": "KSampler"
            },
            vae_decode: {
                "inputs": {
                    "samples": [ksampler, 0],
                    "vae": [checkpoint_loader, 2]
                },
                "class_type": "VAEDecode"
            },
            save_image: {
                "inputs": {
                    "filename_prefix": "ComfyUI",
                    "images": [vae_decode, 0]
                },
                "class_type": "SaveImage"
            }
        }
        
        return workflow
    
    async def queue_prompt(self, workflow: Dict) -> Optional[str]:
        """
        Добавляет workflow в очередь ComfyUI
        
        Args:
            workflow: Workflow JSON для генерации
            
        Returns:
            prompt_id или None в случае ошибки
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                payload = {"prompt": workflow}
                response = await client.post(
                    f"{self.base_url}/prompt",
                    json=payload
                )
                
                if response.status_code == 200:
                    result = response.json()
                    prompt_id = result.get("prompt_id")
                    if prompt_id:
                        logger.info(f"✅ Workflow добавлен в очередь, prompt_id: {prompt_id}")
                        return prompt_id
                    else:
                        logger.error(f"❌ Не получен prompt_id из ответа: {result}")
                        return None
                else:
                    logger.error(f"❌ Ошибка при добавлении в очередь: {response.status_code} - {response.text}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error("❌ Таймаут при добавлении workflow в очередь")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при добавлении workflow в очередь: {e}")
            return None
    
    async def get_image(self, prompt_id: str) -> Optional[Tuple[bytes, str]]:
        """
        Получает готовое изображение по prompt_id
        
        Args:
            prompt_id: ID промпта из очереди
            
        Returns:
            Кортеж (изображение в bytes, имя файла) или None
        """
        max_wait_time = self.timeout
        check_interval = 2  # Проверяем каждые 2 секунды
        elapsed_time = 0
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                while elapsed_time < max_wait_time:
                    # Проверяем историю
                    response = await client.get(f"{self.base_url}/history/{prompt_id}")
                    
                    if response.status_code == 200:
                        history = response.json()
                        
                        # Ищем завершенные задачи
                        if prompt_id in history:
                            outputs = history[prompt_id].get("outputs", {})
                            
                            # Ищем ноду SaveImage
                            for node_id, node_output in outputs.items():
                                if "images" in node_output:
                                    images = node_output["images"]
                                    if images:
                                        image_info = images[0]
                                        filename = image_info.get("filename", "")
                                        subfolder = image_info.get("subfolder", "")
                                        
                                        # Получаем изображение
                                        image_url = f"{self.base_url}/view"
                                        params = {
                                            "filename": filename,
                                            "subfolder": subfolder,
                                            "type": "output"
                                        }
                                        
                                        image_response = await client.get(image_url, params=params)
                                        
                                        if image_response.status_code == 200:
                                            logger.info(f"✅ Изображение получено: {filename}")
                                            return (image_response.content, filename)
                    
                    # Если не готово, ждем и проверяем снова
                    await asyncio.sleep(check_interval)
                    elapsed_time += check_interval
                    
                    if elapsed_time % 10 == 0:
                        logger.info(f"⏳ Ожидание генерации изображения... ({elapsed_time}s/{max_wait_time}s)")
                
                logger.error(f"❌ Таймаут ожидания изображения (>{max_wait_time}s)")
                return None
                
        except httpx.TimeoutException:
            logger.error("❌ Таймаут при получении изображения")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка при получении изображения: {e}")
            return None
    
    async def generate_image(
        self, 
        prompt: str, 
        negative_prompt: str, 
        width: int = 1024, 
        height: int = 1024,
        user_id: Optional[int] = None
    ) -> Dict:
        """
        Полный цикл генерации изображения с управлением ресурсами GPU
        
        Args:
            prompt: Положительный промпт
            negative_prompt: Негативный промпт
            width: Ширина изображения
            height: Высота изображения
            user_id: ID пользователя (для приоритизации)
            
        Returns:
            Словарь с результатом:
            {
                "success": bool,
                "image": Optional[bytes],
                "filename": Optional[str],
                "prompt_id": Optional[str],
                "error": Optional[str]
            }
        """
        # Оцениваем требуемую VRAM (примерно 4-6GB для flux1-dev-fp8)
        # Уменьшаем требования, так как процесс будет переключен перед использованием
        estimated_vram_mb = 4096  # 4GB - после переключения процессов VRAM будет свободна
        
        # Получаем блокировку GPU через Resource Manager
        # Это автоматически переключит процесс на ComfyUI
        try:
            async with await resource_manager.acquire_gpu(
                service_type=ServiceType.COMFYUI,
                user_id=user_id,
                required_vram_mb=estimated_vram_mb,
                timeout=self.timeout
            ) as gpu_lock:
                logger.info(f"🔒 GPU заблокирован для ComfyUI (ID: {gpu_lock.lock_id[:8]})")
                
                # После переключения процесса обновляем URL и проверяем подключение
                logger.info(f"🔄 Проверка доступности ComfyUI после переключения процесса...")
                logger.info(f"   Текущий URL: {self.base_url}")
                self._update_url_if_needed()
                
                # Даем время на запуск ComfyUI после переключения процесса
                logger.info(f"⏳ Ожидание запуска ComfyUI (5 секунд)...")
                await asyncio.sleep(5)
                
                # Проверяем подключение (теперь процесс уже переключен на ComfyUI)
                logger.info(f"🔄 Проверка подключения к ComfyUI на {self.base_url}...")
                max_retries = 3
                retry_delay = 3
                connection_ok = False
                
                for attempt in range(max_retries):
                    connection_ok = await self.check_connection()
                    if connection_ok:
                        break
                    if attempt < max_retries - 1:
                        logger.warning(f"⚠️ Попытка {attempt + 1}/{max_retries}: ComfyUI еще не доступен, повтор через {retry_delay}s...")
                        await asyncio.sleep(retry_delay)
                
                if not connection_ok:
                    error_msg = f"ComfyUI сервер недоступен на {self.base_url} после переключения процесса"
                    logger.error(f"❌ {error_msg}")
                    logger.error(f"   Проверьте, что ComfyUI запущен и доступен на этом адресе")
                    if settings.PROCESS_MANAGER_API_URL:
                        logger.error(f"   Process Manager настроен: {settings.PROCESS_MANAGER_API_URL}")
                        logger.error(f"   Проверьте логи Process Manager для деталей запуска ComfyUI")
                    return {
                        "success": False,
                        "image": None,
                        "filename": None,
                        "prompt_id": None,
                        "error": error_msg
                    }
                
                logger.info(f"✅ ComfyUI доступен и готов к работе")
                
                # Создаем workflow
                logger.info(f"🔄 Создание workflow с размерами: {width}x{height}")
                workflow = self.create_workflow(prompt, negative_prompt, width, height)
                
                # Проверяем, что размеры действительно установлены в workflow
                size_found = False
                for node_id, node_data in workflow.items():
                    if isinstance(node_data, dict) and "inputs" in node_data:
                        inputs = node_data.get("inputs", {})
                        if "width" in inputs and "height" in inputs:
                            w = inputs.get("width")
                            h = inputs.get("height")
                            if w == width and h == height:
                                size_found = True
                                logger.info(f"✅ Подтверждено: размеры {width}x{height} установлены в ноде {node_id[:8]} (класс: {node_data.get('class_type', 'unknown')})")
                                break
                
                if not size_found:
                    logger.warning(f"⚠️ Размеры {width}x{height} не найдены в workflow после создания. Проверьте шаблон.")
                
                # Добавляем в очередь ComfyUI
                prompt_id = await self.queue_prompt(workflow)
                if not prompt_id:
                    return {
                        "success": False,
                        "image": None,
                        "filename": None,
                        "prompt_id": None,
                        "error": "Не удалось добавить workflow в очередь ComfyUI"
                    }
                
                # Получаем изображение
                result = await self.get_image(prompt_id)
                
                if result:
                    image_bytes, filename = result
                    return {
                        "success": True,
                        "image": image_bytes,
                        "filename": filename,
                        "prompt_id": prompt_id,
                        "error": None
                    }
                else:
                    return {
                        "success": False,
                        "image": None,
                        "filename": None,
                        "prompt_id": prompt_id,
                        "error": "Таймаут ожидания генерации изображения"
                    }
                    
        except TimeoutError as e:
            logger.error(f"❌ Таймаут ожидания GPU для ComfyUI: {e}")
            return {
                "success": False,
                "image": None,
                "filename": None,
                "prompt_id": None,
                "error": f"Таймаут ожидания GPU: {str(e)}"
            }
        except Exception as e:
            logger.error(f"❌ Ошибка при работе с Resource Manager: {e}")
            return {
                "success": False,
                "image": None,
                "filename": None,
                "prompt_id": None,
                "error": f"Ошибка управления ресурсами: {str(e)}"
            }


# Глобальный экземпляр сервиса
comfyui_service = ComfyUIService()

